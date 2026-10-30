"""Build the predicted-pass library from a Celestrak TLE snapshot.

What gets built comes from config/workflow.json (libraries.predicted and the
shared localities). For each locality and for the snapshot's day plus the
following days:

- the "passes_from" matrix (Abstracted): one event per satellite pass that can
  image the locality (python/predict_passes.py, thresholds in its "satellites");
- each "roll_ups" matrix (Simplified): the same passes rolled up into its
  groups (EO / IR / SAR).

The ICOD of every payload is the snapshot's "fetched" time (when the orbits
were downloaded), with icod_source "celestrak". Predictions are only good for
a few days from the orbit epochs, which is why the days follow the snapshot.

    python scripts/fetch_tles.py         # new snapshot in data/tle/
    python scripts/build_live_data.py    # rebuild web/live from the newest snapshot
    python scripts/build_live_data.py --tle data/tle/<file>.json --out DIR
"""

import argparse
import json
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python"))
sys.path.insert(0, str(REPO / "scripts"))

import export_payload as ep  # noqa: E402
import predict_passes as pp  # noqa: E402
import workflow as wf  # noqa: E402

SOURCE = "Predicted passes from Celestrak orbits (%s), computed with Skyfield"


def latest_snapshot() -> Path:
    snapshots = sorted((REPO / "data" / "tle").glob("celestrak-*.json"))
    if not snapshots:
        sys.exit("No TLE snapshot in data/tle; run scripts/fetch_tles.py first")
    return snapshots[-1]


def group_provenance(config: dict, events: list, row_group: dict, abstracted: dict) -> dict:
    """Per-phenomenology notes: how many passes, from how many of the configured satellites.

    A group with no satellites in the Abstracted config (e.g. Simplified's COM)
    has no feed, so it gets no source or ICOD.
    """
    out = {}
    for group in config["groups"]:
        name = group["name"]
        rows = [r for r, g in row_group.items() if g == name and r in abstracted.get("satellites", {})]
        if not rows:
            out[name] = {"source": "No data source for %s" % name, "icod": None, "icod_source": None}
            continue
        configured = sum(len(abstracted["satellites"][r]["norad"]) for r in rows)
        group_events = [e for e in events if row_group[e["row"]] == name]
        passing = len({e["label"] for e in group_events})  # one label per spacecraft ("LEGION 3 pass")
        if group_events:
            notes = "%d predicted pass%s from %d of %d configured satellites" % (
                len(group_events), "" if len(group_events) == 1 else "es", passing, configured)
        else:
            notes = "No predicted passes from the %d configured satellites" % configured
        out[name] = {"notes": notes}
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tle", help="TLE snapshot (default: newest in data/tle)")
    parser.add_argument("--out", help="Library folder to write (default: the folder in workflow.json)")
    args = parser.parse_args()

    workflow = wf.load_workflow()
    predicted = workflow["libraries"]["predicted"]
    tle_path = Path(args.tle) if args.tle else latest_snapshot()
    snapshot = pp.load_snapshot(tle_path)
    out_dir = Path(args.out or REPO / predicted["folder"])
    source_id = predicted["passes_from"]
    source_matrix = wf.load_matrix(source_id)
    roll_ups = {m: wf.load_matrix(m) for m in predicted.get("roll_ups", [])}

    row_group = {ep.row_id(r): g["name"] for g in source_matrix["groups"] for r in g["rows"]}
    # A roll-up matrix shows each group as one row: map group name -> that row's id.
    group_row = {m: {g["name"]: ep.row_id(g["rows"][0]) for g in c["groups"]} for m, c in roll_ups.items()}
    source = SOURCE % tle_path.name
    first_day = date.fromisoformat(snapshot["fetched"][:10])

    # The library is rebuilt whole from one snapshot: drop the previous days
    # (they were predicted from older orbits) instead of keeping them around.
    for matrix in [source_id, *roll_ups]:
        shutil.rmtree(out_dir / matrix, ignore_errors=True)

    for name, point in wf.sites(workflow):
        locality = {"name": name, "point": point}
        lon, lat = ep.parse_wkt_point(point)
        for offset in range(int(predicted["days"])):
            day = first_day + timedelta(days=offset)
            window = ep.build_window(source_matrix, day)
            start, end = ep.parse_iso(window["start"]), ep.parse_iso(window["end"])
            events = pp.predict_events(source_matrix, snapshot, lat, lon, start, end)
            builds = [(source_id, source_matrix, events)]
            for matrix, config in roll_ups.items():
                rolled = [dict(e, row=group_row[matrix][e["row"]]) for e in pp.roll_up(events, row_group)]
                builds.append((matrix, config, rolled))

            for matrix, config, matrix_events in builds:
                payload = ep.build_payload(config, matrix_events, day, icod=snapshot["fetched"],
                                           icod_source="celestrak", locality=locality, source=source,
                                           provenance=group_provenance(config, events, row_group, source_matrix))
                path = out_dir / matrix / payload["locality"]["id"] / ("%s.json" % day.isoformat())
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, indent=2))
    ep.rebuild_manifest(out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
