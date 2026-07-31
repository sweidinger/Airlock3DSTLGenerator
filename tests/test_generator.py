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

    # Buendige Praegung im Zahlenfeld: das Code-Volumen allein pruefen.
    codeout = tmp_path / "code.stl"
    Generator().render("73412", out_path=codeout, part="code")
    clo, chi, _ = _stl_bounds(codeout)
    # Ziffern enden buendig mit der Oberflaeche (z ~ 4.0) und sinken in den Feldboden.
    assert 3.9 < chi[2] <= 4.02, f"Ziffern nicht buendig (zmax={chi[2]})"
    assert clo[2] < 3.4, f"Ziffern sinken nicht in den Feldboden (zmin={clo[2]})"
    # Text sitzt zentriert im Zahlenfeld (Zentrum ~ 11.30 / 14.17), Breite < 19 mm.
    assert 3.0 < (chi[0] - clo[0]) < 19.0 and 3.0 < (chi[1] - clo[1]) < 12.0
    assert abs((chi[0] + clo[0]) / 2 - 11.30) < 1.5, "Text nicht in Feldmitte (X)"
    assert abs((chi[1] + clo[1]) / 2 - 14.17) < 1.5, "Text nicht in Feldmitte (Y)"


def test_deterministic(tmp_path):
    g = Generator()
    a = g.render("10098", out_path=tmp_path / "a.stl")
    b = g.render("10098", out_path=tmp_path / "b.stl")
    assert a.sha256 == b.sha256
