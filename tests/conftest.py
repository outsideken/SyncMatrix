"""Make python/export_payload.py importable as `export_payload` in tests."""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python"))
