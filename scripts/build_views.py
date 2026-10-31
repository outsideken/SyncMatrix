"""Redraw the page's library from the stored data files, without re-predicting.

Run this after a matrix change (config/matrix.json: colours, groups, rows,
views). It reads every store's data files (data/predicted, data/demo) and
writes every view into the page's library (web/live). Skyfield is not run
and no data file changes.

    python scripts/build_views.py            # redraw web/live
    python scripts/build_views.py --out DIR  # draw elsewhere
"""

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python"))

import workflow as wf  # noqa: E402


def main() -> int:
    workflow = wf.load_workflow()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(REPO / workflow["folder"]), help="Library folder to write")
    args = parser.parse_args()
    wf.draw_library(wf.load_matrix(), wf.stores(workflow), args.out, workflow["max_seclab"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
