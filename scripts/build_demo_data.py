"""Rebuild the demo library (generated sample events) from config/.

Localities and days come from config/workflow.json (libraries.demo and the
shared localities), matrices from config/matrices/. Events are deterministic
samples (fixed seeds), so re-running this reproduces the committed files apart
from their "generated" timestamp. ICODs are fixed demo values.

    python scripts/build_demo_data.py            # rebuild the folder in workflow.json (web/data)
    python scripts/build_demo_data.py --out DIR  # build elsewhere (e.g. to compare)
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python"))

import export_payload as ep  # noqa: E402
import workflow as wf  # noqa: E402


def seed_for(site_index: int, day: str) -> int:
    return site_index * 100 + int(day[5:7]) * 10 + int(day[-1])


def main() -> int:
    workflow = wf.load_workflow()
    demo = workflow["libraries"]["demo"]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(REPO / demo["folder"]), help="Data folder to write")
    args = parser.parse_args()
    out_dir = Path(args.out)

    for matrix, spec in demo["matrices"].items():
        config = wf.load_matrix(matrix)
        # Seeds use the locality's position in workflow.json (append new ones to keep existing data).
        for i, (name, point) in enumerate(wf.sites(workflow), start=1):
            for day in demo["days"]:
                payload = ep.build_payload(config, day=date.fromisoformat(day["date"]),
                                           demo_count=spec["events_per_day"],
                                           seed=seed_for(i, day["date"]) + spec.get("seed_offset", 0),
                                           icod=day["icod"], locality={"name": name, "point": point})
                path = out_dir / matrix / payload["locality"]["id"] / ("%s.json" % day["date"])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, indent=2))
    ep.rebuild_manifest(out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
