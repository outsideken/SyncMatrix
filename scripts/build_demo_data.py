"""Rebuild the demo library (generated sample windows) from config/.

Two steps, from config/workflow.json (libraries.demo and the shared
localities):

1. Generate: for each locality and demo day, one data file of sample windows
   on the matrix's satellite rows in data/demo/<locality>/<date>.json. They
   are deterministic (fixed seeds), so re-running reproduces the committed
   files. ICODs are fixed demo values.
2. Draw: every view of config/matrix.json from those files into web/data
   (Simplified rolls the same windows up by group).

    python scripts/build_demo_data.py                        # rebuild data/demo and web/data
    python scripts/build_demo_data.py --store DIR --out DIR  # build elsewhere (e.g. to compare)
"""

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python"))

import workflow as wf  # noqa: E402


def main() -> int:
    workflow = wf.load_workflow()
    demo = workflow["libraries"]["demo"]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store", default=str(REPO / demo["store"]), help="Data files to write")
    parser.add_argument("--out", default=str(REPO / demo["folder"]), help="Library folder to write")
    args = parser.parse_args()

    matrix = wf.load_matrix()
    wf.write_store(args.store, wf.demo_data(workflow, matrix))
    wf.draw_library(matrix, args.store, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
