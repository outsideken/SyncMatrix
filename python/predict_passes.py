"""Predict when each satellite row can image a locality, from public orbit data.

Orbits come from a Celestrak snapshot (scripts/fetch_tles.py); passes are
computed with Skyfield. A row's "satellites" entry in the config says which
spacecraft it covers and when a pass counts:

    "Sentinel-2": {"norad": [40697, 42063, 60989], "min_elevation": 78, "needs_daylight": true}
    "Sentinel-1": {"norad": [39634, 62261, 66315], "min_elevation": 44, "max_elevation": 61}

- min_elevation: the satellite must be at least this high above the
  locality's horizon (degrees). Elevation = 90 - incidence angle, so this
  stands in for each sensor's field of regard (off-nadir pointing or swath).
- max_elevation (side-looking SAR): the pass only counts if the satellite's
  highest point stays at or below this, i.e. the locality falls in the swath
  rather than under the satellite.
- needs_daylight: optical (EO) rows; the sun must be up at the locality when
  the satellite is highest.

These thresholds are approximations of each sensor's geometry, not tasking
rules; they live in the config so they can be tuned.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from astral import Observer
from astral.sun import elevation as sun_elevation
from skyfield.api import EarthSatellite, load, wgs84

TS = load.timescale(builtin=True)  # bundled leap-second data; no download


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hhmm(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%H%MZ")


def load_snapshot(path) -> dict:
    """A Celestrak snapshot: {"source", "fetched", "satellites": [OMM records]}."""
    snapshot = json.loads(Path(path).read_text())
    snapshot["by_norad"] = {int(r["NORAD_CAT_ID"]): r for r in snapshot["satellites"]}
    return snapshot


def satellite(snapshot: dict, norad: int) -> EarthSatellite:
    record = snapshot["by_norad"].get(int(norad))
    if record is None:
        raise ValueError("NORAD %s is not in the TLE snapshot" % norad)
    return EarthSatellite.from_omm(TS, record)


def passes(sat: EarthSatellite, lat: float, lon: float, start: datetime, end: datetime,
           min_elevation: float):
    """(rise, culmination, set, max elevation) for passes above min_elevation.

    Passes already in progress at `start`, or still going at `end`, are
    clipped to the window.
    """
    place = wgs84.latlon(lat, lon)
    times, kinds = sat.find_events(place, TS.from_datetime(start), TS.from_datetime(end),
                                   altitude_degrees=min_elevation)
    out, rise, peak = [], None, None
    for t, kind in zip(times, kinds):
        moment = t.utc_datetime()
        if kind == 0:
            rise, peak = moment, None
        elif kind == 1:
            peak = moment
            if rise is None:  # pass already in progress at the window start
                rise = start
        else:
            if peak is not None:
                out.append((rise or start, peak, moment))
            rise, peak = None, None
    if peak is not None:  # still above the threshold at the window end
        out.append((rise or start, peak, end))

    result = []
    for rise, peak, set_ in out:
        alt, _, _ = (sat - place).at(TS.from_datetime(peak)).altaz()
        result.append((rise, peak, set_, float(alt.degrees)))
    return result


def predict_events(config: dict, snapshot: dict, lat: float, lon: float,
                   start: datetime, end: datetime) -> list:
    """Predicted-pass events for every row in the config's "satellites"."""
    observer = Observer(latitude=lat, longitude=lon)
    fetched = snapshot["fetched"]
    events = []
    for row, spec in config.get("satellites", {}).items():
        for norad in spec["norad"]:
            sat = satellite(snapshot, norad)
            record = snapshot["by_norad"][int(norad)]
            for rise, peak, set_, max_el in passes(sat, lat, lon, start, end, spec["min_elevation"]):
                if "max_elevation" in spec and max_el > spec["max_elevation"]:
                    continue  # side-looking SAR: the locality is under the satellite, not in the swath
                sun = sun_elevation(observer, peak)
                if spec.get("needs_daylight") and sun <= 0:
                    continue  # optical sensor in the dark
                name = record["OBJECT_NAME"]
                events.append({
                    "id": "%s-%s-%s" % (row, norad, hhmm(peak)),
                    "row": row,
                    "start": iso(rise),
                    "end": iso(set_),
                    "status": "Predicted",
                    "label": "%s pass" % name,
                    "notes": "Highest %.0f° at %s (sun %.0f°). Threshold %s°. Orbit: Celestrak "
                             "NORAD %s, epoch %s, fetched %s."
                             % (max_el, hhmm(peak), sun,
                                spec["min_elevation"] if "max_elevation" not in spec
                                else "%s–%s" % (spec["min_elevation"], spec["max_elevation"]),
                                norad, record["EPOCH"][:16].replace("T", " ") + "Z", fetched),
                })
    events.sort(key=lambda e: (e["start"], e["row"]))
    return events


def roll_up(events: list, row_group: dict) -> list:
    """Summarise per-satellite events by group (e.g. EO, IR, SAR) for Simplified.

    Overlapping passes in the same group become one event listing them.
    """
    by_group = {}
    for event in events:
        by_group.setdefault(row_group[event["row"]], []).append(event)

    out = []
    for group, items in by_group.items():
        items.sort(key=lambda e: e["start"])
        merged = []
        for e in items:
            if merged and e["start"] <= merged[-1]["end"]:
                merged[-1]["end"] = max(merged[-1]["end"], e["end"])
                merged[-1]["members"].append(e)
            else:
                merged.append({"start": e["start"], "end": e["end"], "members": [e]})
        for m in merged:
            names = [e["label"].replace(" pass", "") for e in m["members"]]
            out.append({"id": "%s-%s" % (group, m["start"][11:16].replace(":", "")),
                        "row": group,
                        "start": m["start"],
                        "end": m["end"],
                        "status": "Predicted",
                        "label": "%d %s pass%s" % (len(names), group, "" if len(names) == 1 else "es"),
                        "notes": "; ".join(names)})
    out.sort(key=lambda e: (e["start"], e["row"]))
    return out
