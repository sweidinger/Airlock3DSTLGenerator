"""Test-Setup: isolierte DB/Output-Pfade, bevor die App importiert wird."""
import os
import pathlib
import tempfile

_tmp = tempfile.mkdtemp(prefix="airlock-test-")
os.environ["AIRLOCK_API_KEY"] = "test-key"
os.environ["AIRLOCK_DB_PATH"] = str(pathlib.Path(_tmp) / "registry.db")
os.environ["AIRLOCK_OUTPUT_DIR"] = str(pathlib.Path(_tmp) / "output")
os.environ["AIRLOCK_MAX_BATCH"] = "50"

TESTS_DIR = pathlib.Path(__file__).resolve().parent

# Soll-Aussenmasse aus dem Original-Sample DisposableLock_v2_withCode_sample.stl
# (siehe ARCHITECTURE.md §2). Dienen als Referenz, ohne die grosse Binaerdatei
# im Repo vorhalten zu muessen.
SAMPLE_BOUNDS_MIN = (0.0, 0.0, 0.0)
SAMPLE_BOUNDS_MAX = (34.9, 55.859, 4.585)
