r"""Build a Sync Matrix JSON payload for the d3 renderer (web/index.html).

Python owns the data and the computation (sunrise/sunset, end of local day,
ICOD, validation); the browser only draws. The payload is plain JSON so it can
be committed to Git, served from any static host, or pushed into an iframe.

Each payload is one matrix, one locality and one UTC day.

Usage
-----
    # Add a day to the page's library: writes
    # <out-dir>/<matrix>/<locality>/<YYYY-MM-DD>.json and rebuilds <out-dir>/index.json.
    python export_payload.py --config ../config/partner.json --date 2026-10-27 \
                             --events events.json --out-dir ../web/data

    # No events yet? Generate deterministic sample events for a demo
    # (the locality can come from the events file or --locality/--locality-name).
    python export_payload.py --config ../config/abstracted.json --demo-events 14 \
                             --locality "POINT(-100 40)" --locality-name "Mid-north 40°N" \
                             --icod 2026-10-27T12:00:00Z --out-dir ../web/data

    # Write a single payload file, without touching the manifest.
    python export_payload.py --config ../config/partner.json \
                             --events events.json --out partner-mid-north.json

    # Rebuild only the manifest (e.g. after deleting old days).
    python export_payload.py --rebuild-manifest ../web/data

The matrix id (--slug) defaults to the config file name (config/partner.json ->
"partner"); the dropdown label comes from the config's "label". See
config/README.md for the config format.

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
DEFAULT_GROUP_COLOR = "#525252"   # ColorBrewer Greys, dark end
DEFAULT_GROUP_TINT = "#d9d9d9"    # ColorBrewer Greys, light end
STATUS_FILLS = ("solid", "tint", "none")

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
        raise ValueError("Could not parse point %r; expected POINT(lon lat)" % wkt)
    return float(match.group(1)), float(match.group(2))


def parse_hhmm(text: str) -> timedelta:
    """'HH:MM' time of day as an offset from midnight; '24:00' is the day's end."""
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if not match or int(match.group(1)) > 24 or int(match.group(2)) > 59 or \
            (int(match.group(1)) == 24 and int(match.group(2)) != 0):
        raise ValueError("Time %r is not HH:MM between 00:00 and 24:00" % text)
    return timedelta(hours=int(match.group(1)), minutes=int(match.group(2)))

################################################################################
## CONFIG
################################################################################

def row_id(row) -> str:
    """A row is a name ("Legion-1") or {"id": ..., "label": ...}."""
    return row if isinstance(row, str) else row["id"]


def load_config(path) -> dict:
    """Read a matrix config (config/*.json) and check it before anything is built.

    Fails with a clear message on: missing title/groups, a duplicate group or
    row, an alternative grouping whose rows differ from "groups" (events must
    land on the same row in every grouping), or a banner time that isn't
    HH:MM.
    """
    with open(path, "r") as f:
        config = json.load(f)
    for key in ("title", "groups"):
        if key not in config:
            raise ValueError("%s: missing %r" % (path, key))

    def rows_of(groups, where):
        names = [g["name"] for g in groups]
        if len(set(names)) != len(names):
            raise ValueError("%s: duplicate group name in %s" % (path, where))
        rows = [row_id(r) for g in groups for r in g["rows"]]
        dupes = sorted({r for r in rows if rows.count(r) > 1})
        if dupes:
            raise ValueError("%s: rows listed twice in %s: %s" % (path, where, dupes))
        return set(rows)

    rows = rows_of(config["groups"], "groups")
    for label, groups in config.get("alt_groupings", {}).items():
        alt = rows_of(groups, "alt_groupings[%r]" % label)
        if alt != rows:
            raise ValueError("%s: grouping %r does not have the same rows as \"groups\" "
                             "(missing: %s; extra: %s)"
                             % (path, label, sorted(rows - alt) or "none", sorted(alt - rows) or "none"))
    for status, style in config.get("status_styles", {}).items():
        if style.get("fill", "tint") not in STATUS_FILLS:
            raise ValueError("%s: status_styles[%r] fill must be one of %s" % (path, status, ", ".join(STATUS_FILLS)))
    for row, spec in config.get("satellites", {}).items():
        if row not in rows:
            raise ValueError("%s: satellites entry %r is not a row" % (path, row))
        if not spec.get("norad") or "min_elevation" not in spec:
            raise ValueError("%s: satellites[%r] needs \"norad\" and \"min_elevation\"" % (path, row))
    for banner in config.get("banners", []):
        if parse_hhmm(banner["end"]) <= parse_hhmm(banner["start"]):
            raise ValueError("%s: banner %r ends before it starts" % (path, banner.get("id")))
    return config

################################################################################
## PAYLOAD SECTIONS
################################################################################

def build_window(config: dict, day: date) -> dict:
    """Window covers one UTC day, with grid ticks every tick_minutes."""
    start = datetime.combine(day, time(0, 0), tzinfo=timezone.utc)
    return {"start": iso(start),
            "end": iso(start + timedelta(days=1)),
            "tick_minutes": int(config.get("tick_minutes", 30))}


def build_groups(groups: list) -> list:
    """Payload groups from the config's "groups" (already top to bottom)."""
    return [{"id": g["name"],
             "label": g["name"],
             "color": g.get("color", DEFAULT_GROUP_COLOR),
             "tint": g.get("tint", DEFAULT_GROUP_TINT),
             "rows": [{"id": row_id(r), "label": r if isinstance(r, str) else r.get("label", r["id"])}
                      for r in g["rows"]]}
            for g in groups]


def build_alt_groupings(config: dict) -> list:
    """Other ways to group the same rows, offered by the page's "Group by" control.

    load_config() has already checked each one has exactly the rows of
    "groups", so events land on the same row whichever grouping is shown.
    """
    return [{"id": slugify(label), "label": label, "groups": build_groups(groups)}
            for label, groups in config.get("alt_groupings", {}).items()]


def build_banners(config: dict, window_start: datetime) -> list:
    """Banner bars under the plot; start/end are times of day (HH:MM, UTC)."""
    return [{"id": b.get("id", "banner-%d" % (i + 1)),
             "text": b["text"],
             "start": iso(window_start + parse_hhmm(b["start"])),
             "end": iso(window_start + parse_hhmm(b["end"])),
             "level": b.get("level", 0),
             "fill": b["fill"],
             "text_color": b.get("text_color", "#ffffff")}
            for i, b in enumerate(config.get("banners", []))]


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


def resolve_locality(locality: dict = None) -> dict:
    """The one locality this payload covers.

    Each payload is one locality and one day. The locality comes from the
    events file ({"name": ..., "point": "POINT(lon lat)"} or name/lon/lat) or
    from --locality/--locality-name; there is no default.
    """
    if not locality:
        raise ValueError("No locality: give it as \"locality\" in the events file or with "
                         "--locality and --locality-name.")
    name = locality["name"]
    if "point" in locality:
        lon, lat = parse_wkt_point(locality["point"])
    else:
        lon, lat = float(locality["lon"]), float(locality["lat"])

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


def build_provenance(config: dict, source: str, icod: str, icod_source: str, overrides: dict = None) -> dict:
    """Provenance for the matrix ("all") and for each group (phenomenology).

    Each phenomenology can come from a different feed with its own ICOD, so
    each gets {"source", "icod", "icod_source", "notes"?}. Groups without an
    override share the matrix's provenance. The page shows a group's entry in
    the popup of its events and lists all of them on exports; this replaces
    the legacy per-phenomenology banners.
    """
    base = {"source": source, "icod": icod, "icod_source": icod_source}
    provenance = {"all": dict(base)}
    for group in config["groups"]:
        provenance[group["name"]] = dict(base, **(overrides or {}).get(group["name"], {}))
    return provenance


def build_payload(config: dict, events: list = None, day: date = None,
                  demo_count: int = 0, seed: int = 7,
                  icod: str = None, icod_source: str = "data",
                  locality: dict = None, source: str = None,
                  provenance: dict = None) -> dict:
    """One matrix, one locality, one UTC day.

    source: where the events came from (one line, shown on exports);
    provenance: per-group overrides for build_provenance().
    """
    now = datetime.now(timezone.utc)
    day = day or now.date()
    icod_dt, icod_source = resolve_icod(icod, icod_source, bool(demo_count), now)

    window = build_window(config, day)
    window_start, window_end = parse_iso(window["start"]), parse_iso(window["end"])
    groups = build_groups(config["groups"])

    loc = resolve_locality(locality)
    daylight = build_daylight(loc["lon"], loc["lat"], window_start, window_end) if config.get("show_daylight") else None
    markers = build_end_of_local_day(loc["timezone"], window_start, window_end) if config.get("show_end_of_local_day") else []

    if demo_count:
        events = demo_events(groups, window_start, window["tick_minutes"], demo_count, seed)
    events = validate_events(events or [], groups, window_start, window_end)

    if source is None:
        source = "Demo data: generated sample events" if demo_count else "Events file"

    return {"version": PAYLOAD_VERSION,
            "title": config["title"],
            "subtitle": "%s · %s" % (loc["name"], window_start.strftime("%d %B %Y")),
            "icod": iso(icod_dt),
            "icod_source": icod_source,
            "source": source,
            "provenance": build_provenance(config, source, iso(icod_dt), icod_source, provenance),
            "generated": iso(now),
            "locality": loc,
            "window": window,
            "groups": groups,
            "grouping": config.get("grouping", "Group"),
            "alt_groupings": build_alt_groupings(config),
            "events": events,
            "status_styles": config.get("status_styles", {}),
            "daylight": daylight,
            "markers": markers,
            "banners": build_banners(config, window_start),
            "label": config.get("label", config["title"])}


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


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
    parser.add_argument("--config", help="Matrix config, e.g. config/partner.json (see config/README.md)")
    parser.add_argument("--events", help="Events JSON: {\"icod\": ..., \"events\": [...]}")
    parser.add_argument("--demo-events", type=int, default=0, help="Generate N sample events instead")
    parser.add_argument("--seed", type=int, default=7, help="Seed for --demo-events")
    parser.add_argument("--date", help="UTC day to render, YYYY-MM-DD (default: today)")
    parser.add_argument("--icod", help="Information Cut-Off Date, ISO 8601 UTC (overrides the events file)")
    parser.add_argument("--locality", metavar="WKT", help="Locality as POINT(lon lat) (overrides the events file)")
    parser.add_argument("--locality-name", help="Name for --locality, e.g. 'Mid-north 40°N'")
    parser.add_argument("--out", help="Payload JSON to write")
    parser.add_argument("--out-dir", help="Data folder: write <matrix>/<locality>/<date>.json and rebuild index.json")
    parser.add_argument("--slug", help="Matrix id for --out-dir (default: the config file name, e.g. partner)")
    parser.add_argument("--label", help="Name for the Matrix dropdown (default: the config's \"label\")")
    args = parser.parse_args()

    if args.rebuild_manifest:
        rebuild_manifest(args.rebuild_manifest)
        return
    if not args.config or not (args.out or args.out_dir):
        parser.error("--config and one of --out/--out-dir are required")

    try:
        config = load_config(args.config)
    except ValueError as err:
        parser.exit(2, "Error: %s\n" % err)

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
        source = "Events file %s" % Path(args.events).name if args.events else None
        payload = build_payload(config, events, day, args.demo_events, args.seed, icod, icod_source, locality,
                                source=source)
    except ValueError as err:
        parser.exit(2, "Error: %s\n" % err)

    slug = args.slug or Path(args.config).stem
    if args.label:
        payload["label"] = args.label

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
