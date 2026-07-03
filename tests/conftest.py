"""Test config: point SNVR_DB_PATH at a per-session temp DB so tests are isolated."""
import os
import tempfile

os.environ.setdefault("SNVR_DEVICE", "cpu")
_TMPDB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMPDB.close()
os.environ["SNVR_DB_PATH"] = _TMPDB.name
