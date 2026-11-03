"""Make python/export_payload.py importable as `export_payload` in tests."""

import sys

from test_helpers import REPO

sys.path.insert(0, str(REPO / "python"))
