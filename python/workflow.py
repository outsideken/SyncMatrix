"""The build workflow: shared localities, the data store, and each library.

Three configuration files, each with one job:

- config/matrix.json draws the chart (groups, rows, colours, groupings) and
  names its views (Abstracted, Simplified);
- config/catalogue.json is the prediction catalogue (NORAD ids, elevation
  thresholds, daylight, swath) that writes predicted data files;
- config/workflow.json (this module) lists the shared localities and how each
  library is built.

A library is built in two steps. Data files (one place on one UTC evaluation
date: locality, ICOD, access windows) are written to its "store" under data/;
then every view of the matrix is drawn from those files into its "folder"
under web/. A colour or group change only redraws (scripts/build_views.py);
it never re-runs Skyfield.

workflow.json, checked by load_workflow():

- localities: a name and a POINT(lon lat) each (optional "kind", e.g.
  "reference" or "city"); names and their ids are unique, points are on the
  globe, and a timezone is found for each. Every library and view shares
  them. The demo library seeds its sample windows from a locality's position
  in the list, so add new localities at the end to leave existing demo data
  as it is.
- libraries.predicted: store, folder, days (from the orbit snapshot's date),
  keep_snapshots.
- libraries.demo: store, folder, days ({date, icod}), events_per_day.
"""

import json
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

from timezonefinder import TimezoneFinder

import export_payload as ep

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "config"
PREDICTED_SOURCE = "Predicted passes from Celestrak orbits (%s), computed with Skyfield"
DEMO_SOURCE = "Demo data: generated sample events"


def load_matrix() -> dict:
    return ep.load_config(CONFIG / "matrix.json")


def sites(workflow: dict) -> list:
    """[(name, "POINT(lon lat)")] in workflow order."""
    return [(l["name"], l["point"]) for l in workflow["localities"]]


def load_workflow(path=CONFIG / "workflow.json") -> dict:
    path = Path(path)
    workflow = json.loads(path.read_text())

    def fail(message):
        raise ValueError("%s: %s" % (path.name, message))

    localities = workflow.get("localities") or fail("no localities")
    names, ids = set(), set()
    finder = TimezoneFinder()
    for i, loc in enumerate(localities):
        name, point = loc.get("name"), loc.get("point")
        if not name or not point:
            fail("locality %d needs a name and a point" % (i + 1))
        if name in names or ep.slugify(name) in ids:
            fail("locality %r is listed twice" % name)
        names.add(name)
        ids.add(ep.slugify(name))
        try:
            lon, lat = ep.parse_wkt_point(point)
        except ValueError as err:
            fail("%s: %s" % (name, err))
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            fail("%s: %s is off the globe (POINT takes longitude first)" % (name, point))
        if finder.timezone_at(lat=lat, lng=lon) is None:
            fail("%s: no timezone found for %s" % (name, point))

    libraries = workflow.get("libraries", {})
    for library_id, library in libraries.items():
        if not library.get("store") or not library.get("folder"):
            fail("libraries.%s needs a store (data files) and a folder (payloads)" % library_id)

    predicted = libraries.get("predicted")
    if predicted:
        if int(predicted.get("days", 0)) < 1 or int(predicted.get("keep_snapshots", 0)) < 1:
            fail("libraries.predicted needs days >= 1 and keep_snapshots >= 1")
        rows = set(ep.row_groups(load_matrix()))
        catalogue = json.loads((CONFIG / "catalogue.json").read_text()).get("satellites") or fail("catalogue.json has no satellites")
        unknown = sorted(set(catalogue) - rows)
        if unknown:
            fail("catalogue.json rows not in matrix.json: %s" % ", ".join(unknown))

    demo = libraries.get("demo")
    if demo:
        for day in demo.get("days") or fail("libraries.demo needs days"):
            datetime.strptime(day["date"], "%Y-%m-%d")
            ep.parse_iso(day["icod"])
        if int(demo.get("events_per_day", -1)) < 0:
            fail("libraries.demo needs events_per_day >= 0")
    return workflow

################################################################################
## DATA STORE
################################################################################

def data_path(store, data: dict) -> Path:
    """<store>/<locality>/<YYYY-MM-DD>.json"""
    return Path(store) / ep.slugify(data["locality"]["name"]) / ("%s.json" % data["evaluation_date"])


def write_store(store, data_files: list) -> None:
    """Replace a store with these data files (older days are history in Git)."""
    store = Path(store)
    shutil.rmtree(store, ignore_errors=True)
    for data in data_files:
        path = data_path(store, data)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def store_files(store) -> list:
    return sorted(p for p in Path(store).glob("*/*.json"))


def predicted_data(workflow: dict, snapshot: dict, snapshot_name: str) -> list:
    """One data file per locality per day from a Celestrak snapshot.

    The ICOD is the snapshot's "fetched" time (when the orbits were
    downloaded); the days start on its date, because predictions are only
    good for a few days from the orbit epochs.
    """
    import predict_passes as pp  # Skyfield is only needed to predict

    catalogue = pp.load_catalogue(CONFIG / "catalogue.json")
    predicted = workflow["libraries"]["predicted"]
    first_day = date.fromisoformat(snapshot["fetched"][:10])
    evaluated = {row: spec["norad"] for row, spec in catalogue["satellites"].items()}
    out = []
    for name, point in sites(workflow):
        lon, lat = ep.parse_wkt_point(point)
        for offset in range(int(predicted["days"])):
            day = first_day + timedelta(days=offset)
            start = ep.parse_iso("%sT00:00:00Z" % day.isoformat())
            out.append({"locality": {"name": name, "point": point},
                        "evaluation_date": day.isoformat(),
                        "icod": snapshot["fetched"],
                        "icod_source": "celestrak",
                        "source": PREDICTED_SOURCE % snapshot_name,
                        "evaluated": evaluated,
                        "windows": pp.predict_windows(catalogue, snapshot, lat, lon, start,
                                                      start + timedelta(days=1))})
    return out


def seed_for(site_index: int, day: str) -> int:
    return site_index * 100 + int(day[5:7]) * 10 + int(day[-1])


def demo_data(workflow: dict, matrix: dict) -> list:
    """Deterministic sample windows on the matrix's rows, one file per locality per demo day.

    Seeds use the locality's position in workflow.json, so re-running
    reproduces the committed files.
    """
    demo = workflow["libraries"]["demo"]
    groups = ep.build_groups(matrix["groups"])
    tick = int(matrix.get("tick_minutes", 30))
    out = []
    for i, (name, point) in enumerate(sites(workflow), start=1):
        for day in demo["days"]:
            start = ep.parse_iso("%sT00:00:00Z" % day["date"])
            events = ep.demo_events(groups, start, tick, int(demo["events_per_day"]), seed_for(i, day["date"]))
            out.append({"locality": {"name": name, "point": point},
                        "evaluation_date": day["date"],
                        "icod": day["icod"],
                        "icod_source": "demo",
                        "source": DEMO_SOURCE,
                        "windows": [{"id": e["id"], "satellite": e["row"], "start": e["start"], "end": e["end"],
                                     "status": e["status"], "label": e["label"], "notes": e["notes"]}
                                    for e in events]})
    return out


def draw_library(matrix: dict, store, folder) -> int:
    """Redraw every view of every data file in a store into a library folder.

    The folder's view folders are replaced whole, so a day dropped from the
    store (or a view dropped from the matrix) leaves the page too.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for old in (p for p in folder.iterdir() if p.is_dir() and not p.name.startswith(".")):
        shutil.rmtree(old)
    return ep.write_views(matrix, store_files(store), folder)
