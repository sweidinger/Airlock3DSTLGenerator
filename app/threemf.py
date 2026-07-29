"""Bambu-tauglicher 3MF-Export (Mehrfarbe) ohne Zusatz-Abhängigkeiten.

Baut aus je einem Body-Mesh (Schloss, schwarz) und einem Code-Mesh je Airlock
(Nummer, weiß) eine 3MF-Datei. Die beiden Teile sind komplementär
(Body = Vorlage mit Aussparung, Code = füllt die Aussparung), überlappen also
nicht — jeder Punkt gehört genau einer Farbe.

Farbzuordnung über `basematerials` + `displaycolor` (schwarz/weiß). Keine
AMS-Slot-Zuweisung: der Slicer zeigt nur die Farben, die Zuordnung zu Filamenten
passiert beim Slicen in Bambu Studio.

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
        # 3 floats Normale überspringen, dann 3 Ecken (je 3 floats)
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
    '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
    'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
    "</Relationships>"
)


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
    body_stl: Path   # Vorlage mit Code-Aussparung (schwarz) — pro Code eigen
    code_stl: Path   # erhabene Nummer, füllt die Aussparung (weiß)


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


def build_3mf(
    items: list[Airlock3MFItem],
    out_path: str | Path,
    *,
    plate: float = 256.0,
    margin: float = 8.0,
    gap: float = 6.0,
    color_body: str = "#111111",
    color_code: str = "#FFFFFF",
) -> ThreeMFResult:
    """Baut die 3MF aus je einem Body- und Code-Mesh pro Airlock.

    Body (schwarz) und Code (weiß) sind komplementär (Body trägt die Aussparung,
    Code füllt sie) und überlappen nicht.
    """
    if not items:
        raise ValueError("Keine Airlocks für den 3MF-Export übergeben.")

    # Grundfläche aus dem ersten Body (alle Bodies haben dieselbe Vorlage → gleiche Außenmaße)
    b0v, _ = load_binary_stl(items[0].body_stl)
    b = _xy_bounds(b0v)
    item_w = b.xmax - b.xmin
    item_h = b.ymax - b.ymin

    # Rasterberechnung auf der Bauplatte
    usable = plate - 2 * margin
    cols = max(1, int((usable + gap) // (item_w + gap)))
    rows_needed = (len(items) + cols - 1) // cols
    rows_fit = max(1, int((usable + gap) // (item_h + gap)))
    fits = rows_needed <= rows_fit

    # XML zusammensetzen
    xml: list[str] = []
    xml.append('<?xml version="1.0" encoding="UTF-8"?>\n')
    xml.append(
        f'<model unit="millimeter" xml:lang="en-US" xmlns="{_NS}" xmlns:m="{_NS_M}">'
    )
    xml.append("<resources>")
    # Basismaterialien: 0 = Body (schwarz), 1 = Code (weiß)
    xml.append('<basematerials id="1">')
    xml.append(f'<base name="Lock" displaycolor="{color_body}FF"/>')
    xml.append(f'<base name="Code" displaycolor="{color_code}FF"/>')
    xml.append("</basematerials>")

    # Je Airlock: Body-Objekt (schwarz) + Code-Objekt (weiß) + Verbund
    next_id = 2
    build_items: list[tuple[int, float, float]] = []
    for i, it in enumerate(items):
        body_v, body_f = load_binary_stl(it.body_stl)
        body_id = next_id
        next_id += 1
        xml.append(f'<object id="{body_id}" type="model" pid="1" pindex="0">')
        _mesh_xml(body_v, body_f, xml)
        xml.append("</object>")

        code_v, code_f = load_binary_stl(it.code_stl)
        code_id = next_id
        next_id += 1
        xml.append(f'<object id="{code_id}" type="model" pid="1" pindex="1">')
        _mesh_xml(code_v, code_f, xml)
        xml.append("</object>")

        comp_id = next_id
        next_id += 1
        xml.append(f'<object id="{comp_id}" type="model" name="Airlock {it.code}">')
        xml.append("<components>")
        xml.append(f'<component objectid="{body_id}"/>')
        xml.append(f'<component objectid="{code_id}"/>')
        xml.append("</components>")
        xml.append("</object>")

        col = i % cols
        row = i // cols
        # Body-Ecke (b.xmin/ymin) auf Rasterzelle setzen
        tx = margin + col * (item_w + gap) - b.xmin
        ty = margin + row * (item_h + gap) - b.ymin
        build_items.append((comp_id, tx, ty))

    xml.append("</resources>")
    xml.append("<build>")
    for comp_id, tx, ty in build_items:
        transform = f"1 0 0 0 1 0 0 0 1 {_fmt(tx)} {_fmt(ty)} 0"
        xml.append(f'<item objectid="{comp_id}" transform="{transform}"/>')
    xml.append("</build>")
    xml.append("</model>")

    model_xml = "".join(xml)

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
