"""The build workflow: shared localities and how each library is built.

config/workflow.json is the one place to add a locality or change what gets
built. Every builder, check and test reads it through load_workflow(), which
validates it first:

- localities: a name and a POINT(lon lat) each (optional "kind", e.g.
  "reference" or "city"); names and their ids are unique, points are on the
  globe, and a timezone is found for each. All matrices share them.
  The demo library seeds its sample events from a locality's position in the
  list, so add new localities at the end to leave existing demo data as it is.
- libraries.predicted: days (from the orbit snapshot's date), keep_snapshots,
  passes_from (the matrix whose "satellites" are predicted) and roll_ups
  (matrices built by rolling those passes up into their groups).
- libraries.demo: days ({date, icod}) and, per matrix, events_per_day and
  seed_offset.
"""

import json
from datetime import datetime
from pathlib import Path

from timezonefinder import TimezoneFinder

import export_payload as ep

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "config"


def matrix_path(matrix_id: str) -> Path:
    return CONFIG / "matrices" / ("%s.json" % matrix_id)


def load_matrix(matrix_id: str) -> dict:
    return ep.load_config(matrix_path(matrix_id))


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
    known = {p.stem for p in (CONFIG / "matrices").glob("*.json")}

    def need_matrix(matrix_id, where):
        if matrix_id not in known:
            fail("%s names matrix %r, but config/matrices/%s.json doesn't exist" % (where, matrix_id, matrix_id))

    predicted = libraries.get("predicted")
    if predicted:
        if int(predicted.get("days", 0)) < 1 or int(predicted.get("keep_snapshots", 0)) < 1:
            fail("libraries.predicted needs days >= 1 and keep_snapshots >= 1")
        need_matrix(predicted.get("passes_from"), "libraries.predicted.passes_from")
        if not load_matrix(predicted["passes_from"]).get("satellites"):
            fail("libraries.predicted.passes_from %r has no \"satellites\"" % predicted["passes_from"])
        for matrix_id in predicted.get("roll_ups", []):
            need_matrix(matrix_id, "libraries.predicted.roll_ups")

    demo = libraries.get("demo")
    if demo:
        for day in demo.get("days") or fail("libraries.demo needs days"):
            datetime.strptime(day["date"], "%Y-%m-%d")
            ep.parse_iso(day["icod"])
        for matrix_id, spec in (demo.get("matrices") or fail("libraries.demo needs matrices")).items():
            need_matrix(matrix_id, "libraries.demo.matrices")
            if int(spec.get("events_per_day", -1)) < 0:
                fail("libraries.demo.matrices[%r] needs events_per_day >= 0" % matrix_id)
    return workflow
