"""Check a committed data library is up to date with config/ and the code.

Rebuilds the library into a temporary folder and compares it with the
committed one, ignoring each file's "generated" timestamp. Fails if a config,
the exporter or the pass prediction changed without the library being
rebuilt, or the other way round.

    python scripts/check_demo_data.py          # web/data  (scripts/build_demo_data.py)
    python scripts/check_demo_data.py --live   # web/live  (scripts/build_live_data.py,
                                               #            from the newest committed TLE snapshot)

Exit code 1 with the differing files if anything is out of date.
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python"))

import workflow as wf  # noqa: E402

LIBRARY_FOLDERS = wf.load_workflow()["libraries"]
LIBRARIES = {"demo": ("build_demo_data.py", REPO / LIBRARY_FOLDERS["demo"]["folder"]),
             "live": ("build_live_data.py", REPO / LIBRARY_FOLDERS["predicted"]["folder"])}


def load(path: Path) -> dict:
    content = json.loads(path.read_text())
    content.pop("generated", None)
    return content


def files(root: Path) -> set:
    return {p.relative_to(root).as_posix() for p in root.rglob("*.json")
            if not any(part.startswith(".") for part in p.relative_to(root).parts)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true", help="Check web/live instead of web/data")
    args = parser.parse_args()
    builder, DATA = LIBRARIES["live" if args.live else "demo"]

    with tempfile.TemporaryDirectory() as tmp:
        fresh = Path(tmp)
        subprocess.run([sys.executable, str(REPO / "scripts" / builder), "--out", str(fresh)],
                       check=True, capture_output=True)
        committed, rebuilt = files(DATA), files(fresh)
        problems = ["%s: committed but not produced by the configs" % f for f in sorted(committed - rebuilt)]
        problems += ["%s: produced by the configs but not committed" % f for f in sorted(rebuilt - committed)]
        problems += ["%s: differs from a fresh build" % f for f in sorted(committed & rebuilt)
                     if load(DATA / f) != load(fresh / f)]

    for problem in problems:
        print("FAIL", problem)
    if problems:
        print("FAILED: run `python scripts/%s` and commit %s" % (builder, DATA.relative_to(REPO)))
        return 1
    print("OK: %s: %d files match a fresh build" % (DATA.relative_to(REPO), len(committed)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
