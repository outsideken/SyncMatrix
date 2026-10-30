"""Rebuild the data files and the page's library from config/ and check them: the one command after an edit.

    python scripts/build_all.py    # demo + predicted (from the newest TLE snapshot), then web/live

Edit config/workflow.json (localities, days), config/catalogue.json
(satellites, thresholds) or config/matrix.json (groups, colours, views), run
this, then commit config/ and the rebuilt data/ and web/live. A matrix-only change
can use scripts/build_views.py instead (redraws without re-predicting). This
does not fetch new orbits; scripts/refresh_live_data.py (or the daily job)
does that.
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
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    try:
        run(SCRIPTS / "build_demo_data.py")
        run(SCRIPTS / "build_live_data.py")
        run(SCRIPTS / "check_data.py")
        run(SCRIPTS / "check_build.py")
    except subprocess.CalledProcessError as err:
        print("FAILED:", err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
