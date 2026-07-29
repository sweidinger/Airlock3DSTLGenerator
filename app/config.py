"""Zentrale Konfiguration des Airlock-Generators (aus Umgebungsvariablen)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Projektwurzel (…/airlock-stl-generator)
BASE_DIR = Path(__file__).resolve().parent.parent


def _env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default)).expanduser()


@dataclass(frozen=True)
class TemplateProfile:
    """Beschreibt eine Lock-Vorlage samt Praege-Parametern.

    Die Defaults entsprechen den gegen `DisposableLock_v2_withCode_sample.stl`
    validierten Werten (siehe ARCHITECTURE.md, Abschnitt 2). Weitere Modelle
    lassen sich spaeter als zusaetzliche Profile ergaenzen.
    """

    name: str = "DisposableLock_v2"
    base_stl: Path = BASE_DIR / "templates" / "DisposableLock_v2.stl"

    # Schrift / Groesse
    font: str = "Liberation Sans:style=Bold"
    size: float = 4.31
    xscale: float = 0.9573      # Horizontale Skalierung -> Breite wie Sample
    depth: float = 0.585        # Praegehoehe (erhaben)
    sink: float = 0.20          # Einsinktiefe -> sauberes Manifold

    # Textposition (in Sample-Ausrichtung, Ursprung 0/0/0)
    tx: float = 2.214           # Tinte startet dann bei X = 2.46 mm
    ty: float = 11.76           # Grundlinie
    topz: float = 4.0           # Deckflaeche

    # Vorlagen-Ausrichtung: 180 Grad um Y, danach in den Ursprung schieben.
    rot: tuple[float, float, float] = (0.0, 180.0, 0.0)
    translate: tuple[float, float, float] = (50.12456894, -20.01378441, 1.0)

    # erwartete Ausgabemasse (fuer Plausibilitaetscheck)
    expected_bounds_max: tuple[float, float, float] = (34.9, 55.859, 4.585)


@dataclass(frozen=True)
class Settings:
    api_key: str = os.environ.get("AIRLOCK_API_KEY", "change-me-in-production")
    db_path: Path = _env_path("AIRLOCK_DB_PATH", str(BASE_DIR / "data" / "registry.db"))
    output_dir: Path = _env_path("AIRLOCK_OUTPUT_DIR", str(BASE_DIR / "output"))
    # Geteiltes Verzeichnis mit dem Host-Update-Watcher (status.json / update.request).
    control_dir: Path = _env_path("AIRLOCK_CONTROL_DIR", str(BASE_DIR / "control"))
    max_batch: int = int(os.environ.get("AIRLOCK_MAX_BATCH", "200"))
    code_length: int = int(os.environ.get("AIRLOCK_CODE_LENGTH", "5"))
    openscad_bin: str = os.environ.get("OPENSCAD_BIN", "openscad")
    render_timeout: int = int(os.environ.get("AIRLOCK_RENDER_TIMEOUT", "120"))
    # Wenn aktiv, spritzt der Server den API-Key ins Dashboard (Null-Tippen).
    # ACHTUNG: Key ist dann im Seitenquelltext sichtbar -> nur im vertrauten LAN.
    ui_autokey: bool = os.environ.get("AIRLOCK_UI_AUTOKEY", "").strip().lower() in (
        "1", "true", "yes", "on",
    )

    # Mehrfarb-3MF-Export (Bambu X1/P1/A1): Bauplatte + Raster + Farben.
    threemf_plate: float = float(os.environ.get("AIRLOCK_3MF_PLATE", "256"))
    threemf_margin: float = float(os.environ.get("AIRLOCK_3MF_MARGIN", "8"))
    threemf_gap: float = float(os.environ.get("AIRLOCK_3MF_GAP", "6"))
    threemf_color_body: str = os.environ.get("AIRLOCK_3MF_COLOR_BODY", "#111111")
    threemf_color_code: str = os.environ.get("AIRLOCK_3MF_COLOR_CODE", "#FFFFFF")

    profile: TemplateProfile = field(default_factory=TemplateProfile)

    @property
    def code_space(self) -> int:
        return 10 ** self.code_length


settings = Settings()
