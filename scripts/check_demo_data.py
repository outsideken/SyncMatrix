"""Check a committed library is up to date with config/ and the code.

Rebuilds the library's data files and payloads into a temporary folder and
compares both with the committed ones, ignoring each payload's "generated"
timestamp. Fails if a config, the exporter or the pass prediction changed
without the library being rebuilt, or the other way round.

    python scripts/check_demo_data.py          # data/demo + web/data       (scripts/build_demo_data.py)
    python scripts/check_demo_data.py --live   # data/predicted + web/live  (scripts/build_live_data.py,
                                               #   from the newest committed TLE snapshot)

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

LIBRARY = wf.load_workflow()["libraries"]
LIBRARIES = {"demo": ("build_demo_data.py", LIBRARY["demo"]),
             "live": ("build_live_data.py", LIBRARY["predicted"])}


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
    builder, library = LIBRARIES["live" if args.live else "demo"]
    pairs = [(REPO / library["store"], "store"), (REPO / library["folder"], "out")]

    problems, counts = [], []
    with tempfile.TemporaryDirectory() as tmp:
        fresh = {name: Path(tmp) / name for _, name in pairs}
        subprocess.run([sys.executable, str(REPO / "scripts" / builder),
                        "--store", str(fresh["store"]), "--out", str(fresh["out"])],
                       check=True, capture_output=True)
        for committed_dir, name in pairs:
            where = committed_dir.relative_to(REPO).as_posix()
            committed, rebuilt = files(committed_dir), files(fresh[name])
            problems += ["%s/%s: committed but not produced by the configs" % (where, f) for f in sorted(committed - rebuilt)]
            problems += ["%s/%s: produced by the configs but not committed" % (where, f) for f in sorted(rebuilt - committed)]
            problems += ["%s/%s: differs from a fresh build" % (where, f) for f in sorted(committed & rebuilt)
                         if load(committed_dir / f) != load(fresh[name] / f)]
            counts.append("%s: %d files" % (where, len(committed)))

    for problem in problems:
        print("FAIL", problem)
    if problems:
        print("FAILED: run `python scripts/%s` and commit %s and %s" % (builder, library["store"], library["folder"]))
        return 1
    print("OK: %s match a fresh build" % ", ".join(counts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
