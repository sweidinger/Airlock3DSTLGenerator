"""Test-Setup: isolierte DB/Output-Pfade, bevor die App importiert wird."""
import os
import pathlib
import tempfile

_tmp = tempfile.mkdtemp(prefix="airlock-test-")
os.environ["AIRLOCK_API_KEY"] = "test-key"
os.environ["AIRLOCK_DB_PATH"] = str(pathlib.Path(_tmp) / "registry.db")
os.environ["AIRLOCK_OUTPUT_DIR"] = str(pathlib.Path(_tmp) / "output")
os.environ["AIRLOCK_CONTROL_DIR"] = str(pathlib.Path(_tmp) / "control")
os.environ["AIRLOCK_MAX_BATCH"] = "50"

TESTS_DIR = pathlib.Path(__file__).resolve().parent

# Soll-Aussenmasse der NTAG213-Vorlage (normalisiert, min-Ecke im Ursprung).
# Die Nummer wird buendig ins Zahlenfeld generiert -> zmax bleibt bei der
# Oberflaeche 4.0 (keine erhabene Praegung mehr).
SAMPLE_BOUNDS_MIN = (0.0, 0.0, 0.0)
SAMPLE_BOUNDS_MAX = (39.9, 55.854, 4.0)
