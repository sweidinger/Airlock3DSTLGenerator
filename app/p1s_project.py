"""Baut ein druckfertiges **Bambu-Studio-P1S-Projekt-3MF** mit Pause bei 3 mm.

Im Gegensatz zu `threemf.build_3mf` (reines Modell-3MF) ist das Ergebnis ein
vollwertiges Bambu-Projekt: eingebettetes P1S-0.4-Druckerprofil, zweifarbig
(Body/Nummer via `paint_color`) und eine Druck-Pause bei 3 mm Hoehe
(`M400 U1`, Displaymeldung) — der Drucker haelt an, man legt die NFC-Tags ein
und setzt fort. Fix auf den P1S; die statischen Profilteile stammen aus einem
eingebetteten Golden Template (`templates/p1s/`).

Deterministisch: gleiche Codes + gleiches Template -> bytegleiche 3MF.
"""
from __future__ import annotations

import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import threemf

_P1S_DIR = Path(__file__).resolve().parent / "templates" / "p1s"

# Zentrum des normalisierten Locks (bbox-Mitte 39.9 x 55.854 x 4.0) -> lokale,
# im Ursprung zentrierte Objekt-Koordinaten (wie es Bambu beim Import ablegt).
_CENTER = (19.9499950, 27.9270401, 2.0)
_PAINT_BODY = "1C"   # paint_color: Korpus
_PAINT_CODE = "0C"   # paint_color: erhabene/buendige Nummer
_UUID_NS = uuid.UUID("6f9619ff-8b86-d011-b42d-00cf4fc964ff")  # fester Namespace -> deterministisch

# P1S-Bauraum / Layout
_BED = 256.0
_MARGIN = 8.0
_GAP = 6.0
_TOWER_X_MIN = 197.0   # Prime Tower sitzt rechts (x=205); Locks bleiben links davon
_LOCK_W = 39.9
_LOCK_H = 55.854
# Vordere-linke Exclusion-Zone des P1S (bed_exclude_area 18x28, Abputz-Ecke).
# Lock-Flaeche startet mit Puffer dahinter, damit die erste Spalte nicht kollidiert.
_ORIGIN_X = 10.0       # linker Rand der Lock-Flaeche
_ORIGIN_Y = 38.0       # vorderer Rand: > 28 (Exclusion) + Puffer


@dataclass
class P1SResult:
    path: Path
    count: int
    cols: int
    rows: int
    fits: bool


def _uid(*parts: object) -> str:
    return str(uuid.uuid5(_UUID_NS, "|".join(str(p) for p in parts)))


def _grid(n: int) -> tuple[list[tuple[float, float]], int, int, bool]:
    """Rasterpositionen (Zentren) fuer n Locks links vom Prime Tower."""
    x_max = _TOWER_X_MIN - _MARGIN     # rechter Rand der Lock-Flaeche (links vom Tower)
    y_max = _BED - _MARGIN             # hinterer Rand
    cols = max(1, int((x_max - _ORIGIN_X + _GAP) // (_LOCK_W + _GAP)))
    rows_fit = max(1, int((y_max - _ORIGIN_Y + _GAP) // (_LOCK_H + _GAP)))
    rows_needed = (n + cols - 1) // cols
    fits = rows_needed <= rows_fit
    pos = []
    for i in range(n):
        c, r = i % cols, i // cols
        x = _ORIGIN_X + _LOCK_W / 2 + c * (_LOCK_W + _GAP)
        y = _ORIGIN_Y + _LOCK_H / 2 + r * (_LOCK_H + _GAP)
        pos.append((round(x, 5), round(y, 5)))
    return pos, cols, rows_needed, fits


def _object_model_xml(oid: int, verts, tris) -> str:
    cx, cy, cz = _CENTER
    out = ['<?xml version="1.0" encoding="UTF-8"?>\n',
           '<model unit="millimeter" xml:lang="en-US" '
           'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
           'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
           'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" '
           'requiredextensions="p">\n',
           '<metadata name="BambuStudio:3mfVersion">1</metadata>\n',
           '<resources>\n',
           f'<object id="{oid}" p:UUID="{_uid("obj", oid)}" type="model">\n<mesh>\n<vertices>\n']
    for x, y, z in verts:
        out.append(f'<vertex x="{x - cx:.6f}" y="{y - cy:.6f}" z="{z - cz:.6f}"/>\n')
    out.append('</vertices>\n<triangles>\n')
    for a, b, c, p in tris:
        pc = _PAINT_CODE if p else _PAINT_BODY
        out.append(f'<triangle v1="{a}" v2="{b}" v3="{c}" paint_color="{pc}"/>\n')
    out.append('</triangles>\n</mesh>\n</object>\n</resources>\n</model>\n')
    return "".join(out)


def _assembly_model_xml(objs: list[tuple[int, str, int, float, float]]) -> str:
    # objs: (comp_oid, code, obj_oid, px, py)  ; comp_oid = object-id im Objektfile
    m = ['<?xml version="1.0" encoding="UTF-8"?>\n',
         '<model unit="millimeter" xml:lang="en-US" '
         'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
         'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
         'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" '
         'requiredextensions="p">\n',
         '<metadata name="Application">BambuStudio-02.07.01.62</metadata>\n',
         '<metadata name="BambuStudio:3mfVersion">1</metadata>\n',
         '<metadata name="CreationDate">2026-01-01</metadata>\n',
         '<metadata name="ModificationDate">2026-01-01</metadata>\n',
         '<resources>\n']
    for comp_oid, code, obj_oid, px, py in objs:
        # Objektdatei ist object_{k}.model (k = Lauf-Index), NICHT object_{comp_oid}.
        # comp_oid = 2k-1  ->  k = (comp_oid + 1) // 2.
        file_k = (comp_oid + 1) // 2
        m.append(f'<object id="{obj_oid}" p:UUID="{_uid("wrap", obj_oid)}" type="model">\n'
                 f'<components>\n<component p:path="/3D/Objects/object_{file_k}.model" '
                 f'objectid="{comp_oid}" p:UUID="{_uid("comp", comp_oid)}" '
                 f'transform="1 0 0 0 1 0 0 0 1 0 0 0"/>\n</components>\n</object>\n')
    m.append(f'</resources>\n<build p:UUID="{_uid("build")}">\n')
    for comp_oid, code, obj_oid, px, py in objs:
        m.append(f'<item objectid="{obj_oid}" p:UUID="{_uid("item", obj_oid)}" '
                 f'transform="1 0 0 0 1 0 0 0 1 {px} {py} 2" printable="1"/>\n')
    m.append('</build>\n</model>\n')
    return "".join(m)


def _model_settings_xml(objs, facecounts, positions) -> str:
    cx, cy, cz = _CENTER
    m = ['<?xml version="1.0" encoding="UTF-8"?>\n<config>\n']
    for (comp_oid, code, obj_oid, px, py), nf in zip(objs, facecounts):
        m.append(f'  <object id="{obj_oid}">\n'
                 f'    <metadata key="name" value="Airlock {code}"/>\n'
                 f'    <metadata key="extruder" value="1"/>\n'
                 f'    <metadata face_count="{nf}"/>\n'
                 f'    <part id="{comp_oid}" subtype="normal_part">\n'
                 f'      <metadata key="name" value="Airlock {code}"/>\n'
                 f'      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>\n'
                 f'      <metadata key="source_file" value="airlock_generator"/>\n'
                 f'      <metadata key="source_object_id" value="{comp_oid}"/>\n'
                 f'      <metadata key="source_volume_id" value="0"/>\n'
                 f'      <metadata key="source_offset_x" value="{cx}"/>\n'
                 f'      <metadata key="source_offset_y" value="{cy}"/>\n'
                 f'      <metadata key="source_offset_z" value="{cz}"/>\n'
                 f'      <mesh_stat face_count="{nf}" edges_fixed="0" degenerate_facets="0" '
                 f'facets_removed="0" facets_reversed="0" backwards_edges="0"/>\n'
                 f'    </part>\n  </object>\n')
    m.append('  <plate>\n'
             '    <metadata key="plater_id" value="1"/>\n'
             '    <metadata key="plater_name" value=""/>\n'
             '    <metadata key="locked" value="false"/>\n'
             '    <metadata key="filament_map_mode" value="Auto For Flush"/>\n'
             '    <metadata key="filament_maps" value="1 1 1 1"/>\n'
             '    <metadata key="thumbnail_file" value="Metadata/plate_1.png"/>\n'
             '    <metadata key="thumbnail_no_light_file" value="Metadata/plate_no_light_1.png"/>\n'
             '    <metadata key="top_file" value="Metadata/top_1.png"/>\n'
             '    <metadata key="pick_file" value="Metadata/pick_1.png"/>\n')
    for i, (comp_oid, code, obj_oid, px, py) in enumerate(objs):
        m.append(f'    <model_instance>\n'
                 f'      <metadata key="object_id" value="{obj_oid}"/>\n'
                 f'      <metadata key="instance_id" value="0"/>\n'
                 f'      <metadata key="identify_id" value="{1000 + i}"/>\n'
                 f'    </model_instance>\n')
    m.append('  </plate>\n  <assemble>\n')
    for comp_oid, code, obj_oid, px, py in objs:
        m.append(f'   <assemble_item object_id="{obj_oid}" instance_id="0" '
                 f'transform="1 0 0 0 1 0 0 0 1 {px} {py} 2" offset="0 0 0" />\n')
    m.append('  </assemble>\n</config>\n')
    return "".join(m)


def _plate_json(objs, positions) -> str:
    import json
    hw, hh = _LOCK_W / 2, _LOCK_H / 2
    bboxes = []
    for (comp_oid, code, obj_oid, px, py), (x, y) in zip(objs, positions):
        bboxes.append({
            "area": 715.14, "bbox": [x - hw, y - hh, x + hw, y + hh],
            "id": 1000 + comp_oid, "layer_height": 0.08, "name": f"Airlock {code}",
        })
    allx0 = min(b["bbox"][0] for b in bboxes); ally0 = min(b["bbox"][1] for b in bboxes)
    allx1 = max(b["bbox"][2] for b in bboxes); ally1 = max(b["bbox"][3] for b in bboxes)
    return json.dumps({
        "bbox_all": [allx0, ally0, allx1, ally1], "bbox_objects": bboxes,
        "bed_type": "cool_plate", "filament_colors": [], "filament_ids": [],
        "first_extruder": 1, "nozzle_diameter": 0.4, "is_seq_print": False, "version": 2,
    }, ensure_ascii=False)


def _rels_xml(n: int) -> str:
    out = ['<?xml version="1.0" encoding="UTF-8"?>\n',
           '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n']
    for k in range(1, n + 1):
        out.append(f' <Relationship Target="/3D/Objects/object_{k}.model" Id="rel-{k}" '
                   'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n')
    out.append('</Relationships>\n')
    return "".join(out)


def _cut_info_xml(n_objects: int) -> str:
    # No-Op (keine Schnitt-Connectors), aber je Objekt-ID ein Eintrag -> passt zur Objektzahl.
    out = ['<?xml version="1.0" encoding="utf-8"?>\n<objects>\n']
    for oid in range(1, n_objects + 1):
        out.append(f' <object id="{oid}">\n  <cut_id id="0" check_sum="1" connectors_cnt="0"/>\n </object>\n')
    out.append('</objects>\n')
    return "".join(out)


def _pause_xml(top_z: float, message: str) -> str:
    return ('<?xml version="1.0" encoding="utf-8"?>\n<custom_gcodes_per_layer>\n<plate>\n'
            '<plate_info id="1"/>\n'
            f'<layer top_z="{top_z:g}" type="1" extruder="1" color="" '
            f'extra="{message}" gcode="M400 U1"/>\n'
            '<mode value="MultiAsSingle"/>\n</plate>\n</custom_gcodes_per_layer>\n')


def build_p1s_project_3mf(
    items: list[threemf.Airlock3MFItem],
    out_path: str | Path,
    *,
    pause_z: float = 3.0,
    pause_message: str = "Tag(s) einlegen, dann fortsetzen",
) -> P1SResult:
    if not items:
        raise ValueError("Keine Airlocks fuer den P1S-Projekt-Export uebergeben.")
    positions, cols, rows, fits = _grid(len(items))

    objs = []            # (comp_oid, code, obj_oid, px, py)
    object_files = {}    # "3D/Objects/object_K.model" -> xml
    facecounts = []
    for k, (it, (px, py)) in enumerate(zip(items, positions), start=1):
        comp_oid = 2 * k - 1
        obj_oid = 2 * k
        verts, tris, _, _ = threemf._merge_colored(it.body_stl, it.code_stl)
        object_files[f"3D/Objects/object_{k}.model"] = _object_model_xml(comp_oid, verts, tris)
        objs.append((comp_oid, it.code, obj_oid, px, py))
        facecounts.append(len(tris))

    parts: dict[str, bytes] = {}
    # statische Template-Bausteine (flach mit __ abgelegt) zurueckmappen
    for f in _P1S_DIR.iterdir():
        if f.is_file():
            parts[f.name.replace("__", "/")] = f.read_bytes()
    # generierte Teile
    parts["3D/3dmodel.model"] = _assembly_model_xml(objs).encode()
    parts["3D/_rels/3dmodel.model.rels"] = _rels_xml(len(items)).encode()
    parts["Metadata/model_settings.config"] = _model_settings_xml(objs, facecounts, positions).encode()
    parts["Metadata/plate_1.json"] = _plate_json(objs, positions).encode()
    parts["Metadata/custom_gcode_per_layer.xml"] = _pause_xml(pause_z, pause_message).encode()
    parts["Metadata/cut_information.xml"] = _cut_info_xml(2 * len(items)).encode()
    for name, xml in object_files.items():
        parts[name] = xml.encode()

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in parts.items():
            zf.writestr(name, data)

    return P1SResult(path=out_path, count=len(items), cols=cols, rows=rows, fits=fits)
