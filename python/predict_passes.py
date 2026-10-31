"""Predict when each satellite row can image a locality, from public orbit data.

Orbits come from a Celestrak snapshot (scripts/fetch_tles.py); passes are
computed with Skyfield. The prediction catalogue (config/catalogue.json) says,
per matrix row, which spacecraft it covers and when a pass counts:

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

Each window also records its pass geometry at the peak (when the satellite is
highest), for a collection request:

    "pass": {"peak": "2026-10-31T00:03:12Z",
             "elevation": 24.1, "azimuth": 187.4,           (satellite seen from the locality)
             "sun_elevation": 26.0, "sun_azimuth": 301.2,
             "clipped": ["start"]}                           (only when the window cuts the pass)

"clipped" names the end(s) of the window that are the day's edge (UTC
midnight) rather than the satellite rising or setting through the threshold.

These thresholds are approximations of each sensor's geometry, not tasking
rules; they live in the catalogue so they can be tuned. The catalogue writes
the data files (access windows); it is not part of the drawing.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from astral import Observer
from astral.sun import azimuth as sun_azimuth
from astral.sun import elevation as sun_elevation
from skyfield.api import EarthSatellite, load, wgs84

TS = load.timescale(builtin=True)  # bundled leap-second data; no download


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hhmm(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%H%MZ")


def bearing(degrees: float) -> float:
    """An azimuth to 0.1°, in [0, 360): 359.96 is 0.0, not 360.0."""
    return round(degrees, 1) % 360


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
    """(rise, culmination, set, max elevation, azimuth at culmination, clipped) for
    passes above min_elevation.

    Passes already in progress at `start`, or still going at `end`, are
    clipped to the window; clipped lists which ends were cut ("start", "end").
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
                out.append((rise, peak, moment, []))
            rise, peak = None, None
    if peak is not None:  # still above the threshold at the window end
        out.append((rise, peak, end, ["end"]))

    result = []
    for rise, peak, set_, clipped in out:
        if rise is start:
            clipped = ["start"] + clipped
        alt, az, _ = (sat - place).at(TS.from_datetime(peak)).altaz()
        result.append((rise, peak, set_, float(alt.degrees), float(az.degrees), clipped))
    return result


def load_catalogue(path) -> dict:
    """The prediction catalogue: {"seclab": ..., "satellites": {row: {"norad": [...], "min_elevation": ...}}}.

    "seclab" is the security label written on every predicted window; a row
    may set its own.
    """
    catalogue = json.loads(Path(path).read_text())
    for row, spec in catalogue.get("satellites", {}).items():
        if not spec.get("norad") or "min_elevation" not in spec:
            raise ValueError("%s: satellites[%r] needs \"norad\" and \"min_elevation\"" % (Path(path).name, row))
        if not spec.get("seclab", catalogue.get("seclab")):
            raise ValueError("%s: satellites[%r] has no \"seclab\" (nor has the catalogue)" % (Path(path).name, row))
    return catalogue


def predict_windows(catalogue: dict, snapshot: dict, lat: float, lon: float,
                    start: datetime, end: datetime) -> list:
    """Access windows (one per pass) for every row in the catalogue."""
    observer = Observer(latitude=lat, longitude=lon)
    fetched = snapshot["fetched"]
    events = []
    for row, spec in catalogue.get("satellites", {}).items():
        for norad in spec["norad"]:
            sat = satellite(snapshot, norad)
            record = snapshot["by_norad"][int(norad)]
            for rise, peak, set_, max_el, az, clipped in passes(sat, lat, lon, start, end, spec["min_elevation"]):
                if "max_elevation" in spec and max_el > spec["max_elevation"]:
                    continue  # side-looking SAR: the locality is under the satellite, not in the swath
                sun = sun_elevation(observer, peak)
                if spec.get("needs_daylight") and sun <= 0:
                    continue  # optical sensor in the dark
                name = record["OBJECT_NAME"]
                geometry = {"peak": iso(peak), "elevation": round(max_el, 1), "azimuth": bearing(az),
                            "sun_elevation": round(sun, 1), "sun_azimuth": bearing(sun_azimuth(observer, peak))}
                if clipped:
                    geometry["clipped"] = clipped
                events.append({
                    "id": "%s-%s-%s" % (row, norad, hhmm(peak)),
                    "satellite": row,
                    "norad": int(norad),
                    "start": iso(rise),
                    "end": iso(set_),
                    "status": "Predicted",
                    "seclab": spec.get("seclab", catalogue.get("seclab")),
                    "label": "%s pass" % name,
                    "pass": geometry,
                    "notes": "Highest %.0f° at %s (sun %.0f°). Threshold %s°. Orbit: Celestrak "
                             "NORAD %s, epoch %s, fetched %s."
                             % (max_el, hhmm(peak), sun,
                                spec["min_elevation"] if "max_elevation" not in spec
                                else "%s–%s" % (spec["min_elevation"], spec["max_elevation"]),
                                norad, record["EPOCH"][:16].replace("T", " ") + "Z", fetched),
                })
    events.sort(key=lambda e: (e["start"], e["satellite"]))
    return events

