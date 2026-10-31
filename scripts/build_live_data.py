"""Build the predicted-pass library from a Celestrak TLE snapshot.

Two steps, from config/workflow.json (libraries.predicted and the shared
localities):

1. Predict: for each locality, the snapshot's day and the following days,
   one data file of access windows (one per satellite pass that can image the
   locality; thresholds in config/catalogue.json, python/predict_passes.py)
   in data/predicted/<locality>/<date>.json. The store is replaced whole.
2. Draw: every view of config/matrix.json from all the stores (predicted
   and demo) into the page's library, web/live (scripts/build_views.py does
   only this step).

The ICOD of every file is the snapshot's "fetched" time (when the orbits were
downloaded), with icod_source "celestrak".

    python scripts/fetch_tles.py         # new snapshot in data/tle/
    python scripts/build_live_data.py    # rebuild data/predicted and web/live from the newest snapshot
    python scripts/build_live_data.py --tle data/tle/<file>.json --store DIR --out DIR
"""

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python"))

import predict_passes as pp  # noqa: E402
import workflow as wf  # noqa: E402


def latest_snapshot() -> Path:
    snapshots = sorted((REPO / "data" / "tle").glob("celestrak-*.json"))
    if not snapshots:
        sys.exit("No TLE snapshot in data/tle; run scripts/fetch_tles.py first")
    return snapshots[-1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tle", help="TLE snapshot (default: newest in data/tle)")
    parser.add_argument("--store", help="Predicted data files to write (default: the store in workflow.json)")
    parser.add_argument("--out", help="Library folder to write (default: the folder in workflow.json)")
    args = parser.parse_args()

    workflow = wf.load_workflow()
    predicted = workflow["libraries"]["predicted"]
    tle_path = Path(args.tle) if args.tle else latest_snapshot()
    store = Path(args.store or REPO / predicted["store"])

    wf.write_store(store, wf.predicted_data(workflow, pp.load_snapshot(tle_path), tle_path.name))
    others = [REPO / lib["store"] for lib_id, lib in workflow["libraries"].items() if lib_id != "predicted"]
    wf.draw_library(wf.load_matrix(), [store, *others], args.out or REPO / workflow["folder"],
                    workflow["max_seclab"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
