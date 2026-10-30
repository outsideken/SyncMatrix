"""Check the committed data files and library are up to date with config/ and the code.

Rebuilds everything into a temporary folder (demo data files, predicted data
files from the newest committed TLE snapshot, and the page's library drawn
from both) and compares it with the committed data/demo, data/predicted and
web/live, ignoring each payload's "generated" timestamp. Fails if a config,
the exporter or the pass prediction changed without a rebuild, or the other
way round.

    python scripts/check_build.py

Exit code 1 with the differing files if anything is out of date.
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python"))
sys.path.insert(0, str(REPO / "scripts"))

import predict_passes as pp  # noqa: E402
import workflow as wf  # noqa: E402
from build_live_data import latest_snapshot  # noqa: E402


def load(path: Path) -> dict:
    content = json.loads(path.read_text())
    content.pop("generated", None)
    return content


def files(root: Path) -> set:
    return {p.relative_to(root).as_posix() for p in root.rglob("*.json")
            if not any(part.startswith(".") for part in p.relative_to(root).parts)}


def main() -> int:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    workflow = wf.load_workflow()
    libraries = workflow["libraries"]
    matrix = wf.load_matrix()
    snapshot = latest_snapshot()

    problems, counts = [], []
    with tempfile.TemporaryDirectory() as tmp:
        fresh = Path(tmp)
        built = {"demo": wf.demo_data(workflow, matrix),
                 "predicted": wf.predicted_data(workflow, pp.load_snapshot(snapshot), snapshot.name)}
        pairs = []
        for library_id, data_files in built.items():
            wf.write_store(fresh / library_id, data_files)
            pairs.append((REPO / libraries[library_id]["store"], fresh / library_id))
        wf.draw_library(matrix, [fresh / library_id for library_id in built], fresh / "web")
        pairs.append((REPO / workflow["folder"], fresh / "web"))

        for committed_dir, rebuilt_dir in pairs:
            where = committed_dir.relative_to(REPO).as_posix()
            committed, rebuilt = files(committed_dir), files(rebuilt_dir)
            problems += ["%s/%s: committed but not produced by the configs" % (where, f) for f in sorted(committed - rebuilt)]
            problems += ["%s/%s: produced by the configs but not committed" % (where, f) for f in sorted(rebuilt - committed)]
            problems += ["%s/%s: differs from a fresh build" % (where, f) for f in sorted(committed & rebuilt)
                         if load(committed_dir / f) != load(rebuilt_dir / f)]
            counts.append("%s: %d files" % (where, len(committed)))

    for problem in problems:
        print("FAIL", problem)
    if problems:
        print("FAILED: run `python scripts/build_all.py` and commit data/ and %s" % workflow["folder"])
        return 1
    print("OK: %s match a fresh build (orbits: %s)" % (", ".join(counts), snapshot.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
