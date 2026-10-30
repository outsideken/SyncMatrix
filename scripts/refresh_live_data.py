"""Refresh the predicted-pass library: new orbits, rebuilt web/live, checked.

The daily GitHub Action (.github/workflows/refresh-live.yml) runs this; it
works the same locally:

    python scripts/refresh_live_data.py            # fetch, prune, build, check
    python scripts/refresh_live_data.py --keep 14  # override keep_snapshots from workflow.json

Steps, stopping at the first failure:
1. scripts/fetch_tles.py: a new Celestrak snapshot in data/tle/ (its download
   time becomes the ICOD of the rebuilt library).
2. Prune data/tle/ to the newest --keep snapshots (older ones are history in Git).
3. scripts/build_live_data.py: rebuild data/predicted and web/live from the
   new snapshot (three days from its date, replacing the previous days).
4. Checks: check_data.py and check_build.py.

Nothing is committed here; the workflow commits if the checks pass.
"""

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(REPO / "python"))

import workflow as wf  # noqa: E402


def run(*args) -> None:
    print("$", " ".join(str(a) for a in args), flush=True)
    subprocess.run([sys.executable, *map(str, args)], check=True, cwd=REPO)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--keep", type=int, help="Snapshots to keep in data/tle (default: keep_snapshots in workflow.json)")
    args = parser.parse_args()
    if args.keep is None:
        args.keep = int(wf.load_workflow()["libraries"]["predicted"]["keep_snapshots"])

    try:
        run(SCRIPTS / "fetch_tles.py")

        snapshots = sorted((REPO / "data" / "tle").glob("celestrak-*.json"))
        for old in snapshots[:-args.keep] if args.keep > 0 else []:
            print("pruning", old.relative_to(REPO))
            old.unlink()

        run(SCRIPTS / "build_live_data.py")
        run(SCRIPTS / "check_data.py")
        run(SCRIPTS / "check_build.py")
    except subprocess.CalledProcessError as err:
        print("FAILED:", err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
