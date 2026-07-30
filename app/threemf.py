"""Mehrfarb-Export (3MF und OBJ) ohne Zusatz-Abhängigkeiten.

Aus je einem Body-Mesh (Schloss) und einem Code-Mesh je Airlock entsteht eine
zweifarbige Datei, die Bambu Studio direkt einliest (Schloss schwarz, Nummer
weiss). Die Farbe haengt jeweils an der GEOMETRIE, nicht am Objekt — dadurch
werden alle Locks eines Batches konsistent eingefaerbt:

  * ``build_3mf``: 3MF-Material-Erweiterung ``<m:colorgroup>`` mit Farb-Index je
    Dreieck (``p1``). Bambu liest das ueber „Standard 3MF Color Parsing".
  * ``build_obj``: Per-Vertex-Farben (``v x y z r g b``). Bambu liest das ueber
    den Obj-Import-Farbdialog (NICHT ueber .mtl).

Beim Import mappt Bambu die zwei erkannten Farben auf die Filament-Slots.
Die Airlocks werden im Raster auf der Bauplatte (Default 256×256, X1/P1/A1)
angeordnet.
"""
from __future__ import annotations

import struct
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------- STL einlesen

def load_binary_stl(path: str | Path) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    """Liest ein binäres STL und liefert (vertices, faces) mit deduplizierten Ecken."""
    data = Path(path).read_bytes()
    if len(data) < 84:
        raise ValueError(f"STL zu kurz: {path}")
    (n_tri,) = struct.unpack_from("<I", data, 80)
    expected = 84 + n_tri * 50
    if len(data) < expected:
        raise ValueError(f"STL beschädigt ({path}): {len(data)} < {expected}")

    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    index: dict[tuple[int, int, int], int] = {}
    q = 100000.0  # Quantisierung auf 1e-5 mm für die Dedup

    off = 84
    for _ in range(n_tri):
        tri = struct.unpack_from("<12f", data, off)
        off += 50  # 12 floats (48) + 2 Byte Attribut
        idx = []
        for k in range(3):
            x, y, z = tri[3 + k * 3], tri[4 + k * 3], tri[5 + k * 3]
            key = (round(x * q), round(y * q), round(z * q))
            vi = index.get(key)
            if vi is None:
                vi = len(verts)
                index[key] = vi
                verts.append((x, y, z))
            idx.append(vi)
        faces.append((idx[0], idx[1], idx[2]))
    return verts, faces


# ------------------------------------------------------------------ 3MF-Aufbau

_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
_NS_M = "http://schemas.microsoft.com/3dmanufacturing/material/2015/02"
_BAMBU_NS = "http://schemas.bambulab.com/package/2021"

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
    "</Types>"
)

_RELS = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Target="/3D/3dmodel.model" Id="rel-1" '
    'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
    "</Relationships>"
)

_MESH_STAT = ('<mesh_stat face_count="{n}" edges_fixed="0" degenerate_facets="0" '
              'facets_removed="0" facets_reversed="0" backwards_edges="0"/>')


def _fmt(v: float) -> str:
    """Kompakte, aber verlustarme Zahldarstellung."""
    return f"{v:.5f}".rstrip("0").rstrip(".") or "0"


def _mesh_xml(verts, faces, out: list[str]) -> None:
    out.append("<mesh><vertices>")
    for x, y, z in verts:
        out.append(f'<vertex x="{_fmt(x)}" y="{_fmt(y)}" z="{_fmt(z)}"/>')
    out.append("</vertices><triangles>")
    for a, b, c in faces:
        out.append(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>')
    out.append("</triangles></mesh>")


@dataclass
class Airlock3MFItem:
    code: str
    body_stl: Path   # Vorlage mit Code-Aussparung -> Part 1 / Extruder 1
    code_stl: Path   # erhabene Nummer, füllt die Aussparung -> Part 2 / Extruder 2


@dataclass
class ThreeMFResult:
    path: Path
    count: int
    cols: int
    rows: int
    item_w: float
    item_h: float
    plate: float
    fits_on_plate: bool
    sha256: str = ""
    bytes: int = 0


@dataclass
class _Bounds:
    xmin: float = field(default=0.0)
    ymin: float = field(default=0.0)
    xmax: float = field(default=0.0)
    ymax: float = field(default=0.0)


def _xy_bounds(verts) -> _Bounds:
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    return _Bounds(min(xs), min(ys), max(xs), max(ys))


def _merge_colored(body_stl, code_stl):
    """Body + Code zu einem Mesh mit Farb-Index je Dreieck (0=Body, 1=Code)."""
    bv, bf = load_binary_stl(body_stl)
    cv, cf = load_binary_stl(code_stl)
    verts = bv + cv
    off = len(bv)
    tris = [(a, b, c, 0) for (a, b, c) in bf]
    tris += [(a + off, b + off, c + off, 1) for (a, b, c) in cf]
    return verts, tris, len(bf), len(cf)


def build_3mf(
    items: list[Airlock3MFItem],
    out_path: str | Path,
    *,
    plate: float = 256.0,
    margin: float = 8.0,
    gap: float = 6.0,
    color_body: str = "#000000",   # Farbgruppe 0 -> Slot 1
    color_code: str = "#FFFFFF",   # Farbgruppe 1 -> Slot 2
) -> ThreeMFResult:
    """Baut eine Mehrfarb-3MF mit Pro-Dreieck-Farben (3MF-Material-Erweiterung).

    Bambu Studio (und Orca) lesen `<m:colorgroup>` + `p1`-Index je Dreieck über
    das „Standard 3MF Color Parsing". Da die Farbe an der Geometrie hängt, werden
    ALLE Locks konsistent zweifarbig — Body=Farbe 0 (schwarz), Code=Farbe 1
    (weiss). Beim Import mappt Bambu Gruppe 0 -> Slot 1, Gruppe 1 -> Slot 2.
    """
    if not items:
        raise ValueError("Keine Airlocks für den 3MF-Export übergeben.")

    b0v, _ = load_binary_stl(items[0].body_stl)
    b = _xy_bounds(b0v)
    item_w = b.xmax - b.xmin
    item_h = b.ymax - b.ymin

    usable = plate - 2 * margin
    cols = max(1, int((usable + gap) // (item_w + gap)))
    rows_needed = (len(items) + cols - 1) // cols
    rows_fit = max(1, int((usable + gap) // (item_h + gap)))
    fits = rows_needed <= rows_fit

    m: list[str] = []
    m.append('<?xml version="1.0" encoding="UTF-8"?>\n')
    m.append(f'<model unit="millimeter" xml:lang="en-US" xmlns="{_NS}" xmlns:m="{_NS_M}">')
    m.append("<resources>")
    # Farbgruppe: Index 0 = Body-Farbe, Index 1 = Code-Farbe
    m.append('<m:colorgroup id="1">')
    m.append(f'<m:color color="{color_body}FF"/>')
    m.append(f'<m:color color="{color_code}FF"/>')
    m.append("</m:colorgroup>")

    next_id = 2
    placed: list[tuple[int, float, float]] = []
    for i, it in enumerate(items):
        verts, tris, _, _ = _merge_colored(it.body_stl, it.code_stl)
        oid = next_id
        next_id += 1
        # pid/pindex: Standard-Farbe des Objekts = Gruppe 1, Index 0 (Body)
        m.append(f'<object id="{oid}" type="model" pid="1" pindex="0" name="Airlock {it.code}">')
        m.append("<mesh><vertices>")
        for x, y, z in verts:
            m.append(f'<vertex x="{_fmt(x)}" y="{_fmt(y)}" z="{_fmt(z)}"/>')
        m.append("</vertices><triangles>")
        for a, bb, c, p in tris:
            m.append(f'<triangle v1="{a}" v2="{bb}" v3="{c}" p1="{p}"/>')
        m.append("</triangles></mesh></object>")

        col = i % cols
        row = i // cols
        tx = margin + col * (item_w + gap) - b.xmin
        ty = margin + row * (item_h + gap) - b.ymin
        placed.append((oid, tx, ty))

    m.append("</resources>")
    m.append("<build>")
    for oid, tx, ty in placed:
        transform = f"1 0 0 0 1 0 0 0 1 {_fmt(tx)} {_fmt(ty)} 0"
        m.append(f'<item objectid="{oid}" transform="{transform}" printable="1"/>')
    m.append("</build>")
    m.append("</model>")
    model_xml = "".join(m)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _CONTENT_TYPES)
        zf.writestr("_rels/.rels", _RELS)
        zf.writestr("3D/3dmodel.model", model_xml)

    import hashlib

    raw = out_path.read_bytes()
    return ThreeMFResult(
        path=out_path,
        count=len(items),
        cols=cols,
        rows=rows_needed,
        item_w=item_w,
        item_h=item_h,
        plate=plate,
        fits_on_plate=fits,
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
    )


def _hex_to_rgb(h: str) -> tuple[float, float, float]:
    """#RRGGBB -> (r, g, b) mit 0..1."""
    h = h.lstrip("#")
    if len(h) >= 6:
        return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0)
    return (0.0, 0.0, 0.0)


def _col(c: tuple[float, float, float]) -> str:
    return f"{c[0]:g} {c[1]:g} {c[2]:g}"


def build_obj(
    items: list[Airlock3MFItem],
    out_path: str | Path,
    *,
    plate: float = 256.0,
    margin: float = 8.0,
    gap: float = 6.0,
    color_body: str = "#000000",   # schwarz
    color_code: str = "#FFFFFF",   # weiss
) -> ThreeMFResult:
    """Erzeugt eine einzelne OBJ mit Per-Vertex-Farben.

    Bambu Studio liest Farben aus `v x y z r g b` (RGB 0..1), NICHT aus .mtl.
    Body-Vertices werden schwarz, Code-Vertices weiss eingefaerbt. Da die Farbe
    am Vertex haengt, faerbt Bambu ALLE Locks konsistent (nicht nur das erste).
    Die Locks werden im Raster auf der Bauplatte angeordnet.
    """
    if not items:
        raise ValueError("Keine Airlocks für den OBJ-Export übergeben.")

    b0v, _ = load_binary_stl(items[0].body_stl)
    b = _xy_bounds(b0v)
    item_w = b.xmax - b.xmin
    item_h = b.ymax - b.ymin

    usable = plate - 2 * margin
    cols = max(1, int((usable + gap) // (item_w + gap)))
    rows_needed = (len(items) + cols - 1) // cols
    rows_fit = max(1, int((usable + gap) // (item_h + gap)))
    fits = rows_needed <= rows_fit

    body_col = _col(_hex_to_rgb(color_body))
    code_col = _col(_hex_to_rgb(color_code))

    lines: list[str] = [
        "# Airlock-STL-Generator - OBJ mit Per-Vertex-Farben",
        "# Body = schwarz, Code = weiss (Bambu Studio: Obj-Import-Farbdialog)",
    ]
    voff = 0
    for i, it in enumerate(items):
        col = i % cols
        row = i // cols
        dx = margin + col * (item_w + gap) - b.xmin
        dy = margin + row * (item_h + gap) - b.ymin
        lines.append(f"o Airlock_{it.code}")
        for part_stl, colstr in ((it.body_stl, body_col), (it.code_stl, code_col)):
            verts, faces = load_binary_stl(part_stl)
            for (x, y, z) in verts:
                lines.append(f"v {_fmt(x + dx)} {_fmt(y + dy)} {_fmt(z)} {colstr}")
            for (a, bb, c) in faces:
                lines.append(f"f {a + 1 + voff} {bb + 1 + voff} {c + 1 + voff}")
            voff += len(verts)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines) + "\n"
    out_path.write_text(text, encoding="utf-8")

    import hashlib

    raw = out_path.read_bytes()
    return ThreeMFResult(
        path=out_path, count=len(items), cols=cols, rows=rows_needed,
        item_w=item_w, item_h=item_h, plate=plate, fits_on_plate=fits,
        sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw),
    )
