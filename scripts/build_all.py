"""Rebuild both libraries from config/ and check them: the one command after an edit.

    python scripts/build_all.py           # demo + predicted (from the newest TLE snapshot)
    python scripts/build_all.py --demo    # only the demo library
    python scripts/build_all.py --live    # only the predicted library

Edit config/workflow.json (localities, days) or config/matrices/*.json, run
this, then commit config/ and the rebuilt web/data and web/live. It does not
fetch new orbits; scripts/refresh_live_data.py (or the daily job) does that.
"""

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"


def run(*args) -> None:
    print("$", " ".join(str(a) for a in args), flush=True)
    subprocess.run([sys.executable, *map(str, args)], check=True, cwd=REPO)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--demo", action="store_true", help="Only the demo library")
    parser.add_argument("--live", action="store_true", help="Only the predicted library")
    args = parser.parse_args()
    both = not (args.demo or args.live)
    try:
        if both or args.demo:
            run(SCRIPTS / "build_demo_data.py")
            run(SCRIPTS / "check_data.py")
            run(SCRIPTS / "check_demo_data.py")
        if both or args.live:
            run(SCRIPTS / "build_live_data.py")
            run(SCRIPTS / "check_data.py", "--live")
            run(SCRIPTS / "check_demo_data.py", "--live")
    except subprocess.CalledProcessError as err:
        print("FAILED:", err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
