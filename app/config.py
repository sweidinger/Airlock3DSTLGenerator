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

    Defaults = NTAG213-Schloss (Vorhaenge-/Siegel-Form mit Print-Pause-Tasche
    fuer einen 12x19x0,19-mm-Tag und abgesenktem Zahlenfeld auf der Oberseite).
    Die Nummer wird zentriert und buendig in dieses Feld generiert. Weitere
    Modelle lassen sich spaeter als zusaetzliche Profile ergaenzen.
    """

    name: str = "DisposableLock_NTAG213"
    base_stl: Path = BASE_DIR / "templates" / "DisposableLock_NTAG213.stl"

    # Schrift / Groesse
    font: str = "Liberation Sans:style=Bold"
    size: float = 4.8
    xscale: float = 0.9573      # Horizontale Skalierung (Breite ~16,9 mm im 19-mm-Feld)
    depth: float = 0.5          # Recess-Fuellhoehe -> Ziffern enden buendig mit der Oberflaeche
    sink: float = 0.20          # Einsinktiefe in den Feldboden -> sauberes Manifold

    # Textposition: zentriert im abgesenkten Zahlenfeld (normalisierte Koordinaten).
    # halign/valign = center -> tx/ty ist das Feldzentrum, nicht die Grundlinie.
    tx: float = 11.2954         # Zahlenfeld-Zentrum X
    ty: float = 14.1662         # Zahlenfeld-Zentrum Y
    topz: float = 3.5           # Zahlenfeld-Boden (Oberflaeche liegt bei 4.0)
    halign: str = "center"
    valign: str = "center"

    # Vorlagen-Ausrichtung: Zahlenfeld liegt bereits oben -> keine Drehung,
    # nur die min-Ecke der STL in den Ursprung normalisieren.
    rot: tuple[float, float, float] = (0.0, 0.0, 0.0)
    translate: tuple[float, float, float] = (-45.12457, -20.01378, -1.0)

    # erwartete Ausgabemasse (fuer Plausibilitaetscheck)
    expected_bounds_max: tuple[float, float, float] = (39.9, 55.854, 4.0)


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
    threemf_color_body: str = os.environ.get("AIRLOCK_3MF_COLOR_BODY", "#000000")
    threemf_color_code: str = os.environ.get("AIRLOCK_3MF_COLOR_CODE", "#FFFFFF")

    # NFC-Signierung: Geheimnis für HMAC(Code|UID). MUSS im Betrieb gesetzt sein
    # (dasselbe Secret braucht später der KG-Tracker zum Offline-Verifizieren).
    nfc_secret: str = os.environ.get("AIRLOCK_NFC_SECRET", "change-me-nfc-secret")

    # Optionaler statischer KG-Tracker-Key (Alternative zu den im Dashboard
    # erzeugten Keys). Leer = nur die dynamisch erzeugten Keys gelten.
    kg_api_key: str = os.environ.get("AIRLOCK_KG_API_KEY", "")

    # BETA: erlaubt beim bewussten Neu-Verheiraten (rebind=true) auch, einen Tag
    # von einem ANDEREN Schloss "wegzunehmen" (dort loesen, hierher umbinden).
    # Nur fuer die Beta-Phase gedacht — in Produktion AUS lassen, dann bleibt ein
    # Tag dauerhaft an hoechstens einem Schloss. Der normale rebind (Ersetzen der
    # Bindung eines Schlosses durch einen FREIEN Tag) haengt NICHT an diesem Flag.
    beta_tag_move: bool = os.environ.get("AIRLOCK_BETA_TAG_MOVE", "").strip().lower() in (
        "1", "true", "yes", "on",
    )

    # Basis-URL fuer den optionalen Tag-URL-Record (Universal Link -> KG-Tracker).
    # Leer = kein URL-Record (nur Text-Record, Alt-Verhalten).
    tag_url_base: str = os.environ.get("AIRLOCK_TAG_URL_BASE", "")

    profile: TemplateProfile = field(default_factory=TemplateProfile)

    @property
    def code_space(self) -> int:
        return 10 ** self.code_length


settings = Settings()
