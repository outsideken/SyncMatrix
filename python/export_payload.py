r"""Build a Sync Matrix JSON payload for the d3 renderer (web/index.html).

Python owns the data and the computation (sunrise/sunset, end of local day,
ICOD, validation); the browser only draws. The payload is plain JSON so it can
be committed to Git, served from any static host, or pushed into an iframe.

Each payload is one matrix, one locality and one UTC day.

Usage
-----
    # Add a day to the page's library: writes
    # <out-dir>/<slug>/<locality>/<YYYY-MM-DD>.json and rebuilds <out-dir>/index.json.
    python export_payload.py --config ../Config_PARTNER_Sync_Matrix.json --slug partner \
                             --date 2026-10-27 --events events.json --out-dir ../web/data

    # No events yet? Generate deterministic sample events for a demo
    # (the locality can come from the events file or --locality/--locality-name).
    python export_payload.py --config ../Config_Abstracted_Sync_Matrix.json --slug abstracted \
                             --demo-events 14 --locality "POINT(-100 40)" \
                             --locality-name "Mid-north 40°N" --out-dir ../web/data

    # Write a single payload file, without touching the manifest.
    python export_payload.py --config ../Config_PARTNER_Sync_Matrix.json \
                             --events events.json --out partner-mid-north.json

    # Rebuild only the manifest (e.g. after deleting old days).
    python export_payload.py --rebuild-manifest ../web/data

--slug defaults to the config's title stub without "Sync Matrix" (e.g.
"PARTNER Sync Matrix" -> "partner"), and --label to "<Slug> Sync Matrix".

Events file format (start/end/icod are ISO 8601 UTC)::

    {"icod": "2026-10-27T19:28:00Z",
     "locality": {"name": "Mid-north 40°N", "point": "POINT(-100 40)"},
     "events": [{"row": "EO", "start": "2026-10-27T06:30:00Z", "end": "2026-10-27T07:00:00Z",
                 "status": "High", "label": "Collection window", "notes": "optional"}]}

ICOD (Information Cut-Off Date) is when the data was grabbed; anything received
after it is not in the plot. It is required (in the file, or with --icod) and is
never defaulted to the export time. A bare list of events is accepted only with
--icod.
"""

import argparse
import json
import random
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from astral import Observer
from astral.sun import dawn, dusk, elevation, sunrise, sunset
from timezonefinder import TimezoneFinder

PAYLOAD_VERSION = 1
DEFAULT_STATUS_COLORS = {"High": "red",
                         "Moderate": "#cb181d",
                         "Low": "orange",
                         "No Concern": "#525252",
                         "Planned": "orange"}

################################################################################
## HELPERS
################################################################################

def iso(dt: datetime) -> str:
    """Format an aware datetime as ISO 8601 UTC with a trailing Z."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text: str) -> datetime:
    """Parse ISO 8601 (with Z or offset) into an aware UTC datetime."""
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Timestamp %r has no timezone; use Z or an offset." % text)
    return dt.astimezone(timezone.utc)


def parse_wkt_point(wkt: str):
    """Return (lon, lat) from a WKT 'POINT(lon lat)' string."""
    match = re.match(r"\s*POINT\s*\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)\s*$", wkt, re.I)
    if not match:
        raise ValueError("Could not parse Locality Point %r" % wkt)
    return float(match.group(1)), float(match.group(2))


def unpack_colors(colors: dict) -> dict:
    """Invert the legacy {color: [keys...]} map into {key: color}."""
    return {key: color for color, keys in colors.items() for key in keys}

################################################################################
## PAYLOAD SECTIONS
################################################################################

def build_window(config: dict, day: date) -> dict:
    """Window covers one UTC day, split into X-Axis Max equal ticks."""
    start = datetime.combine(day, time(0, 0), tzinfo=timezone.utc)
    slots = int(config.get("X-Axis Max", 48))
    return {"start": iso(start),
            "end": iso(start + timedelta(days=1)),
            "tick_minutes": (24 * 60) // slots}


def build_groups(y_axis_data: dict, color_map: dict) -> list:
    """Groups and rows in display order, top to bottom.

    The matplotlib version plots the first group at the bottom (y = 0), so
    both the groups and the rows inside them are reversed here. A blank row
    label (e.g. the NEW config's [""]) means a single row named after its group.
    """
    groups = []
    for name, rows in reversed(list(y_axis_data.items())):
        groups.append({"id": name,
                       "label": name,
                       "color": color_map.get(name, "#525252"),
                       "rows": [{"id": row or name, "label": row or name} for row in reversed(rows)]})
    return groups


def build_alt_groupings(config: dict, color_map: dict, groups: list) -> list:
    """Other ways to group the same rows (config "Y-Axis Alternate Groupings").

    The page offers these in its "Group by" control. Each must contain exactly
    the rows of "Y-Axis Data", so events (which reference rows) land in the
    same place whichever grouping is shown.
    """
    row_ids = sorted(row["id"] for group in groups for row in group["rows"])
    alternates = []
    for label, y_axis_data in config.get("Y-Axis Alternate Groupings", {}).items():
        alt = build_groups(y_axis_data, color_map)
        alt_ids = sorted(row["id"] for group in alt for row in group["rows"])
        if alt_ids != row_ids:
            raise ValueError("Grouping %r does not have the same rows as \"Y-Axis Data\" "
                             "(missing: %s; extra: %s)"
                             % (label, sorted(set(row_ids) - set(alt_ids)) or "none",
                                sorted(set(alt_ids) - set(row_ids)) or "none"))
        alternates.append({"id": slugify(label), "label": label, "groups": alt})
    return alternates


def build_banners(config: dict, window_start: datetime, tick_minutes: int) -> list:
    """Convert legacy slot/y-unit banners into time-positioned banner rows."""
    if not config.get("Add Banners?"):
        return []

    banners = config.get("Banners", {})
    # Legacy banners stack downward with decreasing y; level 0 sits nearest the grid.
    levels = sorted({b["Lower Left Corner XY"][1] for b in banners.values()}, reverse=True)

    out = []
    for key, banner in banners.items():
        x, y = banner["Lower Left Corner XY"]
        start = window_start + timedelta(minutes=tick_minutes * x)
        out.append({"id": key,
                    "text": banner["Text"],
                    "start": iso(start),
                    "end": iso(start + timedelta(minutes=tick_minutes * banner["Banner Width"])),
                    "level": levels.index(y),
                    "fill": banner["Banner Face"],
                    "text_color": banner["Font Color"]})
    return out


def build_daylight(lon: float, lat: float, window_start: datetime, window_end: datetime,
                   step_minutes: int = 10) -> dict:
    """Sun elevation at the locality, sampled across the window.

    The renderer turns these samples into a smooth day/night gradient, so the
    three twilight stages (civil 0 to -6 deg, nautical to -12, astronomical to
    -18) shade progressively darker. This replaces the notebook's three fixed
    15-minute layers. Sampling the elevation (rather than computing sunrise/
    sunset intervals) also copes with polar day and night.
    """
    observer = Observer(latitude=lat, longitude=lon)
    steps = int((window_end - window_start).total_seconds() // (step_minutes * 60))
    elevations = [round(elevation(observer, window_start + timedelta(minutes=step_minutes * i)), 1)
                  for i in range(steps + 1)]

    # Named times for tooltips; any may be missing at high latitudes.
    sun_times = {}
    for name, fn in (("dawn", dawn), ("sunrise", sunrise), ("sunset", sunset), ("dusk", dusk)):
        try:
            t = fn(observer, window_start.date(), tzinfo=timezone.utc)
            if window_start <= t <= window_end:
                sun_times[name] = iso(t)
        except ValueError:
            pass

    return {"step_minutes": step_minutes, "elevations": elevations, "sun": sun_times}


def resolve_locality(config: dict, locality: dict = None) -> dict:
    """The one locality this payload covers.

    Each payload is one locality and one day. The locality comes from the
    events file ({"name": ..., "point": "POINT(lon lat)"} or name/lon/lat);
    the config's "Locality Point" is only a fallback for demos.
    """
    if locality:
        name = locality["name"]
        if "point" in locality:
            lon, lat = parse_wkt_point(locality["point"])
        else:
            lon, lat = float(locality["lon"]), float(locality["lat"])
    else:
        name = config.get("Locality Name", "Default")
        lon, lat = parse_wkt_point(config["Locality Point"])

    tz_name = TimezoneFinder().timezone_at(lat=lat, lng=lon)
    if tz_name is None:
        raise ValueError("No timezone found for %s (%f, %f)" % (name, lat, lon))
    return {"id": slugify(name), "name": name, "lon": lon, "lat": lat, "timezone": tz_name}


def build_end_of_local_day(tz_name: str, window_start: datetime, window_end: datetime) -> list:
    """Local-midnight markers (converted to UTC) that fall inside the window."""
    tz = ZoneInfo(tz_name)

    markers = []
    day = (window_start - timedelta(days=1)).date()
    while day <= window_end.date() + timedelta(days=1):
        midnight = datetime.combine(day, time(0, 0), tzinfo=tz).astimezone(timezone.utc)
        if window_start <= midnight <= window_end:
            markers.append({"time": iso(midnight),
                            "kind": "end_of_local_day",
                            "label": "End of local day (%s)" % tz_name})
        day += timedelta(days=1)
    return markers


def validate_events(events: list, groups: list, window_start: datetime, window_end: datetime) -> list:
    """Check rows and times; return events normalised to ISO Z strings."""
    row_ids = {row["id"] for group in groups for row in group["rows"]}
    clean = []
    for i, event in enumerate(events):
        if event["row"] not in row_ids:
            raise ValueError("Event %d: unknown row %r" % (i, event["row"]))
        start, end = parse_iso(event["start"]), parse_iso(event["end"])
        if end <= start:
            raise ValueError("Event %d: end must be after start" % i)
        if end <= window_start or start >= window_end:
            print("Warning: event %d (%s) is outside the window; skipped." % (i, event.get("label", "")))
            continue
        clean.append(dict(event, start=iso(start), end=iso(end)))
    return clean


def demo_events(groups: list, window_start: datetime, tick_minutes: int, count: int, seed: int) -> list:
    """Deterministic sample events snapped to the tick grid."""
    rng = random.Random(seed)
    rows = [row["id"] for group in groups for row in group["rows"]]
    slots = (24 * 60) // tick_minutes
    statuses = ["High", "Moderate", "Low", "No Concern"]
    events = []
    for i in range(count):
        slot = rng.randrange(0, slots - 4)
        length = rng.choice([1, 1, 2, 3, 4])
        start = window_start + timedelta(minutes=tick_minutes * slot)
        events.append({"id": "demo-%02d" % i,
                       "row": rng.choice(rows),
                       "start": iso(start),
                       "end": iso(start + timedelta(minutes=tick_minutes * length)),
                       "status": rng.choice(statuses),
                       "label": "Demo event %d" % (i + 1),
                       "notes": "Generated sample (seed %d)." % seed})
    return events

################################################################################
## MAIN
################################################################################

def resolve_icod(icod: str, icod_source: str, demo: bool, now: datetime):
    """Return (icod datetime, source label) for the payload.

    ICOD (Information Cut-Off Date) is when the data was grabbed: anything
    received after it is not in the plot. It must come from the data source,
    never from the export time, so a missing ICOD is an error. Demo payloads
    are the one exception and are labelled as such.
    """
    if demo:
        return (parse_iso(icod) if icod else now), "demo"
    if not icod:
        raise ValueError("No ICOD: give it as \"icod\" in the events file or with --icod. "
                         "ICOD is when the data was grabbed, not when this payload is built.")
    icod_dt = parse_iso(icod)
    if icod_dt > now + timedelta(minutes=5):
        raise ValueError("ICOD %s is in the future." % icod)
    return icod_dt, icod_source


def build_payload(config: dict, events: list = None, day: date = None,
                  demo_count: int = 0, seed: int = 7,
                  icod: str = None, icod_source: str = "data",
                  locality: dict = None) -> dict:
    now = datetime.now(timezone.utc)
    day = day or now.date()
    icod_dt, icod_source = resolve_icod(icod, icod_source, bool(demo_count), now)

    color_map = unpack_colors(config.get("Colors", {}))
    window = build_window(config, day)
    window_start, window_end = parse_iso(window["start"]), parse_iso(window["end"])
    groups = build_groups(config["Y-Axis Data"], color_map)
    alt_groupings = build_alt_groupings(config, color_map, groups)

    loc = resolve_locality(config, locality)
    daylight = build_daylight(loc["lon"], loc["lat"], window_start, window_end) if config.get("Show Sunrise/Sunset?") else None
    markers = build_end_of_local_day(loc["timezone"], window_start, window_end) if config.get("Show End of Local Day?") else []

    if demo_count:
        events = demo_events(groups, window_start, window["tick_minutes"], demo_count, seed)
    events = validate_events(events or [], groups, window_start, window_end)

    # Legacy configs may define status colors (e.g. the NEW config); fall back to defaults.
    status_colors = dict(DEFAULT_STATUS_COLORS)
    status_colors.update({k: v for k, v in color_map.items() if k in DEFAULT_STATUS_COLORS})

    return {"version": PAYLOAD_VERSION,
            "title": config["Sync Matrix Title Stub"],
            "subtitle": "%s · %s" % (loc["name"], window_start.strftime("%d %B %Y")),
            "icod": iso(icod_dt),
            "icod_source": icod_source,
            "generated": iso(now),
            "locality": loc,
            "window": window,
            "groups": groups,
            "grouping": config.get("Y-Axis Grouping Name", "Group"),
            "alt_groupings": alt_groupings,
            "events": events,
            "status_colors": status_colors,
            "daylight": daylight,
            "markers": markers,
            "banners": build_banners(config, window_start, window["tick_minutes"])}


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def default_slug(title_stub: str) -> str:
    """Matrix id from the config title, without the "Sync Matrix" suffix.

    "PARTNER Sync Matrix" -> "partner", so the default label becomes
    "Partner Sync Matrix" rather than "Partner Sync Matrix Sync Matrix".
    """
    return slugify(re.sub(r"\s*sync\s*matrix\s*$", "", title_stub, flags=re.I)) or slugify(title_stub)


def rebuild_manifest(data_dir: str) -> dict:
    """Scan <data_dir>/<matrix>/<locality>/<YYYY-MM-DD>.json into <data_dir>/index.json.

    One file is one locality on one day. The manifest is rebuilt from the
    files on disk every time, so adding or deleting a day only needs a re-run,
    never a hand edit.
    """
    root = Path(data_dir)
    matrices, files = [], 0
    for matrix_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        localities, title, label = [], matrix_dir.name, None
        for locality_dir in sorted(p for p in matrix_dir.iterdir() if p.is_dir()):
            dates, loc = [], {"name": locality_dir.name}
            for path in locality_dir.glob("*.json"):
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.stem):
                    continue
                with open(path, "r") as f:
                    payload = json.load(f)
                title, loc = payload.get("title", title), payload.get("locality", loc)
                label = payload.get("label", label)
                dates.append({"date": path.stem,
                              "file": "%s/%s/%s" % (matrix_dir.name, locality_dir.name, path.name),
                              "events": len(payload.get("events", [])),
                              "icod": payload.get("icod"),
                              "icod_source": payload.get("icod_source")})
            if dates:
                dates.sort(key=lambda d: d["date"], reverse=True)  # newest first
                localities.append({"id": locality_dir.name, "name": loc.get("name", locality_dir.name),
                                   "lat": loc.get("lat"), "timezone": loc.get("timezone"), "dates": dates})
                files += len(dates)
        if localities:
            # North to south, so the Locality dropdown reads like a map.
            localities.sort(key=lambda l: -(l["lat"] if l["lat"] is not None else 0))
            matrices.append({"id": matrix_dir.name, "label": label or title, "title": title,
                             "localities": localities})

    manifest = {"version": PAYLOAD_VERSION, "generated": iso(datetime.now(timezone.utc)), "matrices": matrices}
    with open(root / "index.json", "w") as f:
        json.dump(manifest, f, indent=2)
    print("Wrote %s (%d matrices, %d files)" % (root / "index.json", len(matrices), files))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rebuild-manifest", metavar="DATA_DIR", help="Only rebuild DATA_DIR/index.json")
    parser.add_argument("--config", help="Legacy Sync Matrix config JSON")
    parser.add_argument("--events", help="Events JSON: {\"icod\": ..., \"events\": [...]}")
    parser.add_argument("--demo-events", type=int, default=0, help="Generate N sample events instead")
    parser.add_argument("--seed", type=int, default=7, help="Seed for --demo-events")
    parser.add_argument("--date", help="UTC day to render, YYYY-MM-DD (default: today)")
    parser.add_argument("--icod", help="Information Cut-Off Date, ISO 8601 UTC (overrides the events file)")
    parser.add_argument("--locality", metavar="WKT", help="Locality as POINT(lon lat) (overrides the events file)")
    parser.add_argument("--locality-name", help="Name for --locality, e.g. 'Mid-north 40°N'")
    parser.add_argument("--out", help="Payload JSON to write")
    parser.add_argument("--out-dir", help="Data folder: write <slug>/<locality>/<date>.json and rebuild index.json")
    parser.add_argument("--slug", help="Matrix id for --out-dir (default: config title without "
                                       "'Sync Matrix', e.g. partner)")
    parser.add_argument("--label", help="Name for the Matrix dropdown (default: from --slug, e.g. Partner Sync Matrix)")
    args = parser.parse_args()

    if args.rebuild_manifest:
        rebuild_manifest(args.rebuild_manifest)
        return
    if not args.config or not (args.out or args.out_dir):
        parser.error("--config and one of --out/--out-dir are required")

    with open(args.config, "r") as f:
        config = json.load(f)

    events, icod, icod_source, locality = None, None, "data", None
    if args.events:
        with open(args.events, "r") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            events, icod, locality = loaded.get("events", []), loaded.get("icod"), loaded.get("locality")
        else:
            events = loaded
    if args.icod:
        icod, icod_source = args.icod, "cli"
    if args.locality:
        if not args.locality_name:
            parser.error("--locality needs --locality-name")
        locality = {"name": args.locality_name, "point": args.locality}

    day = date.fromisoformat(args.date) if args.date else None
    try:
        payload = build_payload(config, events, day, args.demo_events, args.seed, icod, icod_source, locality)
    except ValueError as err:
        parser.exit(2, "Error: %s\n" % err)

    # Name for the page's Matrix dropdown, e.g. "Partner Sync Matrix"; the chart keeps the config title.
    slug = args.slug or default_slug(config["Sync Matrix Title Stub"])
    payload["label"] = args.label or slug.replace("-", " ").title() + " Sync Matrix"

    out = args.out
    if args.out_dir:
        out = (Path(args.out_dir) / slug / payload["locality"]["id"] /
               (payload["window"]["start"][:10] + ".json"))
        out.parent.mkdir(parents=True, exist_ok=True)

    with open(out, "w") as f:
        json.dump(payload, f, indent=2)
    print("Wrote %s (%d groups, %d events)" % (out, len(payload["groups"]), len(payload["events"])))

    if args.out_dir:
        rebuild_manifest(args.out_dir)


if __name__ == "__main__":
    main()
