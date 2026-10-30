"""Check the page's library (web/live) before it ships.

- every JSON file parses;
- every file listed in index.json exists, and every payload is listed;
- each payload has the fields the page needs, an ICOD, and events that
  point at rows that exist.

Exit code 1 with a list of problems if anything is wrong.
"""

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REQUIRED = ("version", "title", "icod", "icod_source", "source", "provenance", "locality", "window",
            "groups", "events")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.parse_args()
    # The page's library (web/live); read without importing anything, so Pages can run this bare.
    DATA = REPO / json.loads((REPO / "config" / "workflow.json").read_text())["folder"]
    problems = []

    payloads = {}
    for path in sorted(DATA.rglob("*.json")):
        # Skip hidden folders such as Jupyter's .ipynb_checkpoints.
        if any(part.startswith(".") for part in path.relative_to(DATA).parts):
            continue
        try:
            content = json.loads(path.read_text())
        except json.JSONDecodeError as err:
            problems.append("%s: not valid JSON (%s)" % (path.relative_to(DATA), err))
            continue
        if path.name != "index.json":
            payloads[path.relative_to(DATA).as_posix()] = content

    manifest = json.loads((DATA / "index.json").read_text())
    listed = set()
    for matrix in manifest["matrices"]:
        for locality in matrix["localities"]:
            for day in locality["dates"]:
                listed.add(day["file"])
                if day["file"] not in payloads:
                    problems.append("index.json lists %s, which does not exist" % day["file"])
    for name in sorted(set(payloads) - listed):
        problems.append("%s is not listed in index.json (run --rebuild-manifest)" % name)

    for name, payload in sorted(payloads.items()):
        missing = [key for key in REQUIRED if key not in payload]
        if missing:
            problems.append("%s: missing %s" % (name, ", ".join(missing)))
            continue
        if not payload["icod"]:
            problems.append("%s: no ICOD" % name)
        provenance = payload.get("provenance", {})
        missing = [g["id"] for g in payload["groups"] if g["id"] not in provenance] + \
                  (["all"] if "all" not in provenance else [])
        if missing:
            problems.append("%s: no provenance for %s" % (name, ", ".join(missing)))
        rows = {row["id"] for group in payload["groups"] for row in group["rows"]}
        for alt in payload.get("alt_groupings", []):
            alt_rows = {row["id"] for group in alt["groups"] for row in group["rows"]}
            if alt_rows != rows:
                problems.append("%s: grouping %r has different rows from the main grouping" % (name, alt["label"]))
        for event in payload["events"]:
            if event["row"] not in rows:
                problems.append("%s: event %r on unknown row %r" % (name, event.get("label"), event["row"]))

    for problem in problems:
        print("FAIL", problem)
    print("%s: %s: %d payloads, %d listed in index.json, %d problem(s)"
          % ("OK" if not problems else "FAILED", DATA.name, len(payloads), len(listed), len(problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
