"""Check web/data is up to date with config/ and the exporter.

Rebuilds the demo library into a temporary folder (scripts/build_demo_data.py)
and compares it with the committed web/data, ignoring each file's "generated"
timestamp. Fails if a config or the exporter changed without the demo data
being rebuilt, or the other way round.

Exit code 1 with the differing files if anything is out of date.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "web" / "data"


def load(path: Path) -> dict:
    content = json.loads(path.read_text())
    content.pop("generated", None)
    return content


def files(root: Path) -> set:
    return {p.relative_to(root).as_posix() for p in root.rglob("*.json")
            if not any(part.startswith(".") for part in p.relative_to(root).parts)}


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        fresh = Path(tmp)
        subprocess.run([sys.executable, str(REPO / "scripts" / "build_demo_data.py"), "--out", str(fresh)],
                       check=True, capture_output=True)
        committed, rebuilt = files(DATA), files(fresh)
        problems = ["%s: committed but not produced by the configs" % f for f in sorted(committed - rebuilt)]
        problems += ["%s: produced by the configs but not committed" % f for f in sorted(rebuilt - committed)]
        problems += ["%s: differs from a fresh build" % f for f in sorted(committed & rebuilt)
                     if load(DATA / f) != load(fresh / f)]

    for problem in problems:
        print("FAIL", problem)
    if problems:
        print("FAILED: run `python scripts/build_demo_data.py` and commit web/data")
        return 1
    print("OK: %d files match a fresh build from config/" % len(committed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
