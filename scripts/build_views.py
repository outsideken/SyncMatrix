"""Redraw the page's payloads from the stored data files, without re-predicting.

Run this after a matrix change (config/matrix.json: colours, groups, rows,
views). It reads each library's data files (data/predicted, data/demo) and
writes every view into its folder (web/live, web/data). Skyfield is not run
and no data file changes.

    python scripts/build_views.py                     # both libraries
    python scripts/build_views.py --library demo      # one library
    python scripts/build_views.py --library demo --store DIR --out DIR
"""

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python"))

import workflow as wf  # noqa: E402


def main() -> int:
    workflow = wf.load_workflow()
    libraries = workflow["libraries"]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--library", choices=sorted(libraries), help="One library (default: all)")
    parser.add_argument("--store", help="Data files to draw (default: the library's store; needs --library)")
    parser.add_argument("--out", help="Library folder to write (default: the library's folder; needs --library)")
    args = parser.parse_args()
    if (args.store or args.out) and not args.library:
        parser.error("--store and --out need --library")

    matrix = wf.load_matrix()
    for library_id in [args.library] if args.library else sorted(libraries):
        library = libraries[library_id]
        wf.draw_library(matrix, args.store or REPO / library["store"], args.out or REPO / library["folder"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
