"""Build the predicted-pass library in web/live from a Celestrak TLE snapshot.

For each demo site and for the snapshot's day plus the next two days:

- Abstracted: one event per satellite pass that can image the site
  (python/predict_passes.py, thresholds in config/abstracted.json "satellites").
- Partner: the same passes rolled up into its EO / IR / SAR rows.

The ICOD of every payload is the snapshot's "fetched" time (when the orbits
were downloaded), with icod_source "celestrak". Predictions are only good for
a few days from the orbit epochs, which is why the days follow the snapshot.

    python scripts/fetch_tles.py         # new snapshot in data/tle/
    python scripts/build_live_data.py    # rebuild web/live from the newest snapshot
    python scripts/build_live_data.py --tle data/tle/<file>.json --out DIR
"""

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python"))
sys.path.insert(0, str(REPO / "scripts"))

import export_payload as ep  # noqa: E402
import predict_passes as pp  # noqa: E402
from build_demo_data import SITES  # noqa: E402

DAYS = 3
SOURCE = "Predicted passes from Celestrak orbits (%s), computed with Skyfield"


def latest_snapshot() -> Path:
    snapshots = sorted((REPO / "data" / "tle").glob("celestrak-*.json"))
    if not snapshots:
        sys.exit("No TLE snapshot in data/tle; run scripts/fetch_tles.py first")
    return snapshots[-1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tle", help="TLE snapshot (default: newest in data/tle)")
    parser.add_argument("--out", default=str(REPO / "web" / "live"), help="Library folder to write")
    args = parser.parse_args()

    tle_path = Path(args.tle) if args.tle else latest_snapshot()
    snapshot = pp.load_snapshot(tle_path)
    out_dir = Path(args.out)
    abstracted = ep.load_config(REPO / "config" / "abstracted.json")
    partner = ep.load_config(REPO / "config" / "partner.json")

    row_group = {ep.row_id(r): g["name"] for g in abstracted["groups"] for r in g["rows"]}
    partner_row = {g["name"]: ep.row_id(g["rows"][0]) for g in partner["groups"]}
    source = SOURCE % tle_path.name
    first_day = date.fromisoformat(snapshot["fetched"][:10])

    for name, point in SITES:
        locality = {"name": name, "point": point}
        lon, lat = ep.parse_wkt_point(point)
        for offset in range(DAYS):
            day = first_day + timedelta(days=offset)
            window = ep.build_window(abstracted, day)
            start, end = ep.parse_iso(window["start"]), ep.parse_iso(window["end"])
            events = pp.predict_events(abstracted, snapshot, lat, lon, start, end)
            rolled = [dict(e, row=partner_row[e["row"]]) for e in pp.roll_up(events, row_group)]

            for matrix, config, matrix_events in (("abstracted", abstracted, events), ("partner", partner, rolled)):
                payload = ep.build_payload(config, matrix_events, day, icod=snapshot["fetched"],
                                           icod_source="celestrak", locality=locality)
                payload["source"] = source
                path = out_dir / matrix / payload["locality"]["id"] / ("%s.json" % day.isoformat())
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, indent=2))
    ep.rebuild_manifest(out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
