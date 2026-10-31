"""The build workflow: shared localities, the data store, and each library.

Three configuration files, each with one job:

- config/matrix.json draws the chart (groups, rows, colours, groupings) and
  names its views (Abstracted, Simplified);
- config/catalogue.json is the prediction catalogue (NORAD ids, elevation
  thresholds, daylight, swath) that writes predicted data files;
- config/workflow.json (this module) lists the shared localities and how each
  library is built.

The page reads one library. It is built in two steps. Each data source
writes data files (one place on one UTC evaluation date: locality, ICOD,
access windows) to its "store" under data/; then every view of the matrix is
drawn from all the stores into one "folder" under web/. A colour or group
change only redraws (scripts/build_views.py); it never re-runs Skyfield.

workflow.json, checked by load_workflow():

- localities: a name and a POINT(lon lat) each (optional "kind", e.g.
  "reference", "city" or "sea"); names and their ids are unique, points are
  on the globe, and a timezone is found for each. Every view shares them.
  Optional "evaluate" lists the matrix groups predicted there: phenomenology
  groups (e.g. ["EO", "SAR"]) or groups of another grouping such as a
  provider (["HawkEye 360"]); without it, every row in the catalogue. A
  chart draws only what its data file evaluated.
- folder: the library the page reads (web/live).
- max_seclab: the highest security label the folder may publish (a label in
  matrix.json "seclabs"). web/live is a public site, so UNCLASSIFIED; a
  window above it fails the build.
- libraries.predicted: store, days (from the orbit snapshot's date),
  keep_snapshots.
- libraries.demo: store, locality (the one "Demo" entry in the page's
  Locality list, and the point its daylight is drawn for), days
  ({date, icod}), events_per_day, seclab (the label on every demo window).
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


def named_groups(matrix: dict) -> dict:
    """Group name -> its row ids, across every grouping (phenomenology and e.g. Provider)."""
    out = {}
    for groups in [matrix["groups"], *matrix.get("alt_groupings", {}).values()]:
        for g in groups:
            out.setdefault(g["name"], set()).update(ep.row_id(r) for r in g["rows"])
    return out


def evaluated_rows(matrix: dict, loc: dict) -> set:
    """The rows a place evaluates: the union of the groups in its "evaluate" (all rows by default)."""
    named = named_groups(matrix)
    if "evaluate" not in loc:
        return set(ep.row_groups(matrix))
    return set().union(*(named[name] for name in loc["evaluate"]))


def sites(workflow: dict) -> list:
    """[(name, "POINT(lon lat)")] in workflow order."""
    return [(l["name"], l["point"]) for l in workflow["localities"]]


def load_workflow(path=CONFIG / "workflow.json") -> dict:
    path = Path(path)
    workflow = json.loads(path.read_text())

    def fail(message):
        raise ValueError("%s: %s" % (path.name, message))

    libraries = workflow.get("libraries", {})
    localities = workflow.get("localities") or fail("no localities")
    demo = libraries.get("demo")
    names, ids = set(), set()
    finder = TimezoneFinder()
    for i, loc in enumerate(localities + ([demo.get("locality") or {}] if demo else [])):
        name, point = loc.get("name"), loc.get("point")
        if not name or not point:
            fail("locality %d needs a name and a point" % (i + 1) if i < len(localities)
                 else "libraries.demo needs a locality with a name and a point")
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

    matrix = load_matrix()
    rank = ep.seclab_rank(matrix)

    def check_label(label, what):
        if label not in rank:
            fail("%s must be a security label from matrix.json seclabs (%s); got %r" % (what, ", ".join(rank), label))
        if "max_seclab" in workflow and rank[label] > rank.get(workflow["max_seclab"], -1):
            fail("%s is %s, above max_seclab %s" % (what, label, workflow["max_seclab"]))

    check_label(workflow.get("max_seclab"), "max_seclab")
    groups = named_groups(matrix)
    for loc in localities:
        unknown = sorted(set(loc.get("evaluate", groups)) - set(groups))
        if unknown or loc.get("evaluate") == []:
            fail("%s: evaluate must list matrix groups (%s); got %s"
                 % (loc["name"], ", ".join(sorted(groups)), ", ".join(unknown) or "none"))

    if not workflow.get("folder"):
        fail("needs a folder (the library the page reads)")
    for library_id, library in libraries.items():
        if not library.get("store"):
            fail("libraries.%s needs a store (its data files)" % library_id)

    predicted = libraries.get("predicted")
    if predicted:
        if int(predicted.get("days", 0)) < 1 or int(predicted.get("keep_snapshots", 0)) < 1:
            fail("libraries.predicted needs days >= 1 and keep_snapshots >= 1")
        rows = set(ep.row_groups(matrix))
        catalogue = json.loads((CONFIG / "catalogue.json").read_text())
        satellites = catalogue.get("satellites") or fail("catalogue.json has no satellites")
        unknown = sorted(set(satellites) - rows)
        if unknown:
            fail("catalogue.json rows not in matrix.json: %s" % ", ".join(unknown))
        for row, spec in satellites.items():
            check_label(spec.get("seclab", catalogue.get("seclab")), "catalogue.json %s seclab" % row)

    if demo:
        for day in demo.get("days") or fail("libraries.demo needs days"):
            datetime.strptime(day["date"], "%Y-%m-%d")
            ep.parse_iso(day["icod"])
        if int(demo.get("events_per_day", -1)) < 0:
            fail("libraries.demo needs events_per_day >= 0")
        check_label(demo.get("seclab"), "libraries.demo seclab")
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


def store_files(*stores) -> list:
    return sorted(p for store in stores for p in Path(store).glob("*/*.json"))


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
    matrix = load_matrix()
    out = []
    for loc in workflow["localities"]:
        name, point = loc["name"], loc["point"]
        lon, lat = ep.parse_wkt_point(point)
        # Only the rows this place evaluates (all by default): its data file covers those, and the chart shows them.
        wanted = evaluated_rows(matrix, loc)
        here = dict(catalogue, satellites={row: spec for row, spec in catalogue["satellites"].items() if row in wanted})
        evaluated = {row: spec["norad"] for row, spec in here["satellites"].items()}
        for offset in range(int(predicted["days"])):
            day = first_day + timedelta(days=offset)
            start = ep.parse_iso("%sT00:00:00Z" % day.isoformat())
            out.append({"locality": {"name": name, "point": point},
                        "evaluation_date": day.isoformat(),
                        "icod": snapshot["fetched"],
                        "icod_source": "celestrak",
                        "source": PREDICTED_SOURCE % snapshot_name,
                        "evaluated": evaluated,
                        "windows": pp.predict_windows(here, snapshot, lat, lon, start,
                                                      start + timedelta(days=1))})
    return out


def seed_for(day: str) -> int:
    return 100 + int(day[5:7]) * 10 + int(day[-1])


def demo_data(workflow: dict, matrix: dict) -> list:
    """Deterministic sample windows on the matrix's rows at the demo locality, one file per demo day.

    Fixed seeds, so re-running reproduces the committed files.
    """
    demo = workflow["libraries"]["demo"]
    groups = ep.build_groups(matrix["groups"])
    tick = int(matrix.get("tick_minutes", 30))
    out = []
    for day in demo["days"]:
        start = ep.parse_iso("%sT00:00:00Z" % day["date"])
        events = ep.demo_events(groups, start, tick, int(demo["events_per_day"]), seed_for(day["date"]), demo["seclab"])
        out.append({"locality": dict(demo["locality"]),
                    "evaluation_date": day["date"],
                    "icod": day["icod"],
                    "icod_source": "demo",
                    "source": DEMO_SOURCE,
                    # Demo covers every row, so its charts show every group.
                    "evaluated": {ep.row_id(r): [] for g in matrix["groups"] for r in g["rows"]},
                    "windows": [{"id": e["id"], "satellite": e["row"], "start": e["start"], "end": e["end"],
                                 "status": e["status"], "seclab": e["seclab"], "label": e["label"],
                                 "notes": e["notes"]}
                                for e in events]})
    return out


def stores(workflow: dict) -> list:
    return [REPO / library["store"] for library in workflow["libraries"].values()]


def draw_library(matrix: dict, store_dirs: list, folder, ceiling: str) -> int:
    """Redraw every view of every data file in the stores into the library folder.

    The folder's view folders are replaced whole, so a day dropped from a
    store (or a view dropped from the matrix) leaves the page too. ceiling
    is the folder's max_seclab: the check is on what is published, whichever
    store a window came from.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for old in (p for p in folder.iterdir() if p.is_dir() and not p.name.startswith(".")):
        shutil.rmtree(old)
    return ep.write_views(matrix, store_files(*store_dirs), folder, ceiling)
