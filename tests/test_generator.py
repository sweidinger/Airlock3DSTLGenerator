"""Tests des Generator-Cores inkl. Vergleich gegen das Original-Sample."""
import struct

import pytest

from app.generator import Generator, validate_code
from tests.conftest import SAMPLE_BOUNDS_MAX, SAMPLE_BOUNDS_MIN


def _stl_bounds(path):
    """Bounding-Box einer STL lesen (erkennt ASCII und binaer, ohne externe Libs)."""
    data = open(path, "rb").read()
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    n = 0
    # Binaer erkennen: Groesse == 84 + 50 * Dreieckszahl
    if len(data) >= 84:
        (tri,) = struct.unpack("<I", data[80:84])
        if len(data) == 84 + 50 * tri:
            n = tri
            off = 84
            for _ in range(tri):
                for _v in range(3):
                    x, y, z = struct.unpack_from("<3f", data, off + 12 + _v * 12)
                    for i, c in enumerate((x, y, z)):
                        lo[i] = min(lo[i], c); hi[i] = max(hi[i], c)
                off += 50
            return lo, hi, n
    # sonst: ASCII
    for line in data.decode("utf-8", "ignore").splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[0] == "vertex":
            x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
            for i, c in enumerate((x, y, z)):
                lo[i] = min(lo[i], c); hi[i] = max(hi[i], c)
        elif parts[:2] == ["facet", "normal"]:
            n += 1
    return lo, hi, n


def test_validate_code():
    assert validate_code("42") == "00042"
    assert validate_code("73412") == "73412"
    for bad in ("abc", "12a45", "123456", "-1"):
        with pytest.raises(ValueError):
            validate_code(bad)


def test_render_matches_sample(tmp_path):
    out = tmp_path / "gen.stl"
    res = Generator().render("73412", out_path=out)
    assert res.path.is_file()
    assert res.sha256 and res.bytes > 0

    glo, ghi, _ = _stl_bounds(out)
    # Aussenmasse muessen mit der Vorlage uebereinstimmen (Ausrichtung korrekt);
    # die Nummer ist buendig -> ueberschreitet die Oberflaeche 4.0 nicht.
    for i in range(3):
        assert abs(ghi[i] - SAMPLE_BOUNDS_MAX[i]) < 0.05, f"max[{i}] {ghi[i]}"
        assert abs(glo[i] - SAMPLE_BOUNDS_MIN[i]) < 0.05, f"min[{i}] {glo[i]}"

    # Code-Volumen (Nummer + weisser Tag-Rahmen) pruefen.
    codeout = tmp_path / "code.stl"
    Generator().render("73412", out_path=codeout, part="code")
    clo, chi, _ = _stl_bounds(codeout)
    # Ziffern enden buendig mit der Oberflaeche (z ~ 4.0); der Rahmen sitzt tiefer
    # am Taschenrand (bei ~2.6 unter der Pausenebene) -> zmin deutlich unter 3.4.
    assert 3.9 < chi[2] <= 4.02, f"Ziffern nicht buendig (zmax={chi[2]})"
    assert clo[2] < 3.4, f"Code sinkt nicht in den Feldboden/Rahmen fehlt (zmin={clo[2]})"
    # Rahmen vorhanden: Code-Geometrie an der Taschenrand-Ebene (~2.6-3.0).
    assert clo[2] < 2.7, f"Tag-Rahmen fehlt (erwartet Geometrie bei ~2.6, zmin={clo[2]})"
    # Code zentriert (Zentrum ~ 11.30 / 14.17); Ausdehnung <= Rahmen-Aussenmass (~21.4 x 14.4).
    assert 3.0 < (chi[0] - clo[0]) < 23.0 and 3.0 < (chi[1] - clo[1]) < 16.0
    assert abs((chi[0] + clo[0]) / 2 - 11.30) < 1.5, "Code nicht in Feldmitte (X)"
    assert abs((chi[1] + clo[1]) / 2 - 14.17) < 1.5, "Code nicht in Feldmitte (Y)"


def test_deterministic(tmp_path):
    g = Generator()
    a = g.render("10098", out_path=tmp_path / "a.stl")
    b = g.render("10098", out_path=tmp_path / "b.stl")
    assert a.sha256 == b.sha256


def test_p1s_project_3mf(tmp_path):
    """P1S-Projekt-3MF: Bambu-Projektstruktur, zweifarbig, Pause bei 3 mm."""
    import zipfile
    from app import threemf, p1s_project

    g = Generator()
    items = []
    for c in ["73412", "10098", "24680"]:
        b = g.render(c, out_path=tmp_path / f"{c}_b.stl", part="body")
        cc = g.render(c, out_path=tmp_path / f"{c}_c.stl", part="code")
        items.append(threemf.Airlock3MFItem(c, b.path, cc.path))
    res = p1s_project.build_p1s_project_3mf(items, tmp_path / "p1s.3mf")
    assert res.count == 3 and res.fits

    z = zipfile.ZipFile(res.path)
    names = set(z.namelist())
    for req in ("3D/3dmodel.model", "3D/_rels/3dmodel.model.rels",
                "Metadata/project_settings.config", "Metadata/model_settings.config",
                "Metadata/custom_gcode_per_layer.xml", "3D/Objects/object_1.model",
                "3D/Objects/object_3.model"):
        assert req in names, f"fehlt: {req}"

    # Pause bei 3 mm (M400 U1, type=1 = Pause)
    cg = z.read("Metadata/custom_gcode_per_layer.xml").decode()
    assert 'top_z="3"' in cg and "M400 U1" in cg and 'type="1"' in cg
    # P1S-Profil eingebettet
    assert "Bambu Lab P1S" in z.read("Metadata/project_settings.config").decode()
    # Zweifarbig via paint_color (Body 1C, Nummer 0C)
    o1 = z.read("3D/Objects/object_1.model").decode()
    assert 'paint_color="1C"' in o1 and 'paint_color="0C"' in o1
