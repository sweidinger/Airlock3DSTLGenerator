"""Generator-Core: erzeugt aus einem Code eine Airlock-STL via OpenSCAD.

Deterministisch: gleicher Code + gleiches Profil -> bytegleiche STL.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import Settings, TemplateProfile, settings

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_jinja = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(enabled_extensions=()),
    keep_trailing_newline=True,
)


class GeneratorError(RuntimeError):
    """Fehler beim Rendern einer STL."""


@dataclass(frozen=True)
class RenderResult:
    code: str
    path: Path
    sha256: str
    bytes: int


def validate_code(code: str, length: int = 5) -> str:
    """Prueft/normalisiert einen Code auf `length` Ziffern (mit Nullen aufgefuellt)."""
    if not isinstance(code, str):
        code = str(code)
    code = code.strip()
    if not re.fullmatch(r"\d+", code):
        raise ValueError(f"Code muss rein numerisch sein: {code!r}")
    if len(code) > length:
        raise ValueError(f"Code laenger als {length} Ziffern: {code!r}")
    return code.zfill(length)


class Generator:
    """Rendert Airlock-STLs mit einem Vorlagen-Profil."""

    def __init__(self, cfg: Settings | None = None, profile: TemplateProfile | None = None):
        self.cfg = cfg or settings
        self.profile = profile or self.cfg.profile
        if not Path(self.profile.base_stl).is_file():
            raise GeneratorError(f"Vorlage nicht gefunden: {self.profile.base_stl}")

    def _render_scad(self, code: str) -> str:
        p = self.profile
        tpl = _jinja.get_template("lock.scad.j2")
        return tpl.render(
            code=code,
            size=p.size,
            xscale=p.xscale,
            depth=p.depth,
            sink=p.sink,
            tx=p.tx,
            ty=p.ty,
            font=p.font,
            topz=p.topz,
            base_stl=str(Path(p.base_stl).resolve()),
            rot_x=p.rot[0], rot_y=p.rot[1], rot_z=p.rot[2],
            tr_x=p.translate[0], tr_y=p.translate[1], tr_z=p.translate[2],
        )

    def render(self, code: str, out_path: Path | None = None) -> RenderResult:
        """Erzeugt die STL fuer `code`. Schreibt nach `out_path` oder ins Output-Verzeichnis."""
        code = validate_code(code, self.cfg.code_length)
        if out_path is None:
            out_dir = Path(self.cfg.output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"{self.profile.name}_{code}.stl"
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        scad_text = self._render_scad(code)
        with tempfile.NamedTemporaryFile("w", suffix=".scad", delete=False) as fh:
            fh.write(scad_text)
            scad_file = fh.name
        try:
            proc = subprocess.run(
                [self.cfg.openscad_bin, "--export-format", "binstl",
                 "-o", str(out_path), scad_file],
                capture_output=True, text=True, timeout=self.cfg.render_timeout,
            )
            if proc.returncode != 0 or not out_path.is_file():
                raise GeneratorError(
                    f"OpenSCAD fehlgeschlagen (code {proc.returncode}): {proc.stderr.strip()}"
                )
        finally:
            Path(scad_file).unlink(missing_ok=True)

        data = out_path.read_bytes()
        return RenderResult(
            code=code,
            path=out_path,
            sha256=hashlib.sha256(data).hexdigest(),
            bytes=len(data),
        )
