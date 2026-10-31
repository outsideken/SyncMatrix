r"""Build Sync Matrix JSON payloads for the d3 renderer (web/index.html).

Python owns the data and the computation (sunrise/sunset, end of local day,
ICOD, validation); the browser only draws. The payload is plain JSON so it can
be committed to Git, served from any static host, or pushed into an iframe.

Two inputs, joined here:

- the matrix configuration (config/matrix.json): groups, rows, colours, other
  groupings, and the views drawn from it (Abstracted: every satellite row;
  Simplified: one row per group);
- a data file: one place on one UTC evaluation date, with its ICOD and the
  access windows (load_data() has the format). It names no matrix.

Each payload is one view, one locality and one UTC day.

Usage
-----
    # Draw every view of a data file into the page's library: writes
    # <out-dir>/<view>/<locality>/<YYYY-MM-DD>.json and rebuilds <out-dir>/index.json.
    python export_payload.py --data ../data/predicted/london/2026-10-30.json --out-dir ../web/live

    # One view, one payload file, without touching the manifest.
    python export_payload.py --data london.json --view simplified --out simplified-london.json

    # Rebuild only the manifest (e.g. after deleting old days).
    python export_payload.py --rebuild-manifest ../web/live

See config/README.md for the matrix and data formats.

ICOD (Information Cut-Off Date) is when the data was grabbed; anything received
after it is not in the plot. It is required and is never defaulted to the
export time; demo data says so with "icod_source": "demo".
"""

import argparse
import json
import random
import re
import unicodedata
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
MATRIX = Path(__file__).resolve().parents[1] / "config" / "matrix.json"

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


VIEW_ROWS = ("satellites", "groups")


def check_config(config: dict, where) -> dict:
    """Check a matrix (or one view of it) before anything is built.

    Fails with a clear message on: missing groups, a duplicate group or row,
    an alternative grouping whose rows differ from "groups" (events must land
    on the same row in every grouping), an unknown status fill, a banner time
    that isn't HH:MM, a view without a title, or a security label list that
    is empty, repeats a name or lacks a colour.
    """
    if "groups" not in config:
        raise ValueError("%s: missing 'groups'" % where)
    if "title" not in config and not config.get("views"):
        raise ValueError("%s: missing 'title' (or 'views', each with a title)" % where)
    for view_id, view in config.get("views", {}).items():
        if "title" not in view:
            raise ValueError("%s: view %r has no title" % (where, view_id))
        if view.get("rows", "satellites") not in VIEW_ROWS:
            raise ValueError("%s: view %r rows must be one of %s" % (where, view_id, ", ".join(VIEW_ROWS)))

    def rows_of(groups, label):
        names = [g["name"] for g in groups]
        if len(set(names)) != len(names):
            raise ValueError("%s: duplicate group name in %s" % (where, label))
        rows = [row_id(r) for g in groups for r in g["rows"]]
        dupes = sorted({r for r in rows if rows.count(r) > 1})
        if dupes:
            raise ValueError("%s: rows listed twice in %s: %s" % (where, label, dupes))
        return set(rows)

    rows = rows_of(config["groups"], "groups")
    for label, groups in config.get("alt_groupings", {}).items():
        alt = rows_of(groups, "alt_groupings[%r]" % label)
        if alt != rows:
            raise ValueError("%s: grouping %r does not have the same rows as \"groups\" "
                             "(missing: %s; extra: %s)"
                             % (where, label, sorted(rows - alt) or "none", sorted(alt - rows) or "none"))
    for status, style in config.get("status_styles", {}).items():
        if style.get("fill", "tint") not in STATUS_FILLS:
            raise ValueError("%s: status_styles[%r] fill must be one of %s" % (where, status, ", ".join(STATUS_FILLS)))
    for banner in config.get("banners", []):
        if parse_hhmm(banner["end"]) <= parse_hhmm(banner["start"]):
            raise ValueError("%s: banner %r ends before it starts" % (where, banner.get("id")))
    ageing = config.get("icod_ageing")
    if ageing is not None:
        hours = [ageing.get(k) for k in ("ageing_after_hours", "stale_after_hours")]
        if not all(isinstance(h, (int, float)) and h > 0 for h in hours) or hours[0] >= hours[1]:
            raise ValueError("%s: icod_ageing needs 0 < ageing_after_hours < stale_after_hours" % where)
    labels = config.get("seclabs")
    names = [l.get("name") for l in labels or []]
    if not labels or not all(names) or len(set(names)) != len(names) or not all(l.get("color") for l in labels):
        raise ValueError("%s: seclabs must list security labels lowest first, each with a unique name "
                         "and a color" % where)
    return config


def seclab_rank(matrix: dict) -> dict:
    """Security label -> its rank: its position in the matrix's "seclabs" list, lowest first.

    The rank is never the label's spelling: "RESTRICTED" sorts before
    "UNCLASSIFIED" as text, so a string comparison would invert a ceiling.
    """
    return {l["name"]: i for i, l in enumerate(matrix["seclabs"])}


def highest_seclab(labels, rank: dict) -> str:
    """The highest of these labels (a merged bar, a chart banner)."""
    return max(labels, key=rank.__getitem__)


def check_seclabs(matrix: dict, data: dict, ceiling: str) -> None:
    """Every window has a known label at or under the library's ceiling.

    The ceiling is the highest label the library may publish (web/live is a
    public site: UNCLASSIFIED). A window above it fails the build; it is
    never dropped quietly.
    """
    rank = seclab_rank(matrix)
    if ceiling not in rank:
        raise ValueError("Ceiling %r is not a security label (%s)" % (ceiling, ", ".join(rank)))
    for i, w in enumerate(data["windows"]):
        label = w["seclab"]
        if label not in rank:
            raise ValueError("Window %d (%s): unknown security label %r (%s)"
                             % (i, w.get("id", w["satellite"]), label, ", ".join(rank)))
        if rank[label] > rank[ceiling]:
            raise ValueError("Window %d (%s) is %s, above this library's ceiling %s; it cannot be published here"
                             % (i, w.get("id", w["satellite"]), label, ceiling))


def load_config(path, view: str = None) -> dict:
    """Read and check the matrix configuration (config/matrix.json).

    One matrix draws the chart: groups, rows, colours, other groupings. Its
    "views" are the matrices on the page (Abstracted, Simplified); with
    `view`, return that view as the config build_payload() draws.
    """
    with open(path, "r") as f:
        matrix = check_config(json.load(f), path)
    return view_config(matrix, view) if view else matrix


def view_config(matrix: dict, view_id: str) -> dict:
    """One view of the matrix, in the shape build_payload() draws.

    rows "satellites" (Abstracted) draws every row; rows "groups"
    (Simplified) draws each group as one row named after it, with no other
    groupings, and its events are the group's windows rolled up (roll_up()).
    """
    view = matrix.get("views", {}).get(view_id)
    if view is None:
        raise ValueError("The matrix has no view %r (views: %s)" % (view_id, ", ".join(matrix.get("views", {}))))
    config = {k: v for k, v in matrix.items() if k != "views"}
    config.update(title=view["title"], label=view.get("label", view["title"]))
    if view.get("rows", "satellites") == "groups":
        config["groups"] = [dict(g, rows=[g["name"]]) for g in matrix["groups"]]
        config.pop("alt_groupings", None)
    return check_config(config, "view %r" % view_id)


def row_groups(matrix: dict) -> dict:
    """Row id -> its group's name (e.g. "Legion-3" -> "EO")."""
    return {row_id(r): g["name"] for g in matrix["groups"] for r in g["rows"]}

################################################################################
## DATA
################################################################################

def load_data(path) -> dict:
    """Read and check one data file: one place on one UTC evaluation date.

    {"locality": {"name": "London", "point": "POINT(-0.1278 51.5074)"},
     "evaluation_date": "2026-10-30",
     "icod": "2026-10-30T05:17:42Z", "icod_source": "celestrak",
     "source": "one line on where the windows came from",
     "evaluated": {"Sentinel-2": [40697, 42063, 60989]},     (optional)
     "windows": [{"satellite": "Sentinel-2", "start": ..., "end": ...,
                  "status": "Predicted", "seclab": "UNCLASSIFIED",
                  "norad": 40697,                            (norad: from the catalogue)
                  "id": ..., "label": ..., "notes": ...}]}   (optional)

    It names no matrix: build_view() draws it in every view. "evaluated"
    lists the catalogue's spacecraft per row, so a row that was checked and
    had no passes is told apart from one that was not checked. "seclab" is
    the window's security label; it is required and never defaulted.
    """
    with open(path, "r") as f:
        data = json.load(f)
    where = Path(path).name
    for key in ("locality", "evaluation_date", "icod", "windows"):
        if key not in data:
            raise ValueError("%s: missing %r" % (where, key))
    date.fromisoformat(data["evaluation_date"])
    for i, window in enumerate(data["windows"]):
        missing = [k for k in ("satellite", "start", "end", "status", "seclab") if k not in window]
        if missing:
            raise ValueError("%s: window %d is missing %s" % (where, i, ", ".join(missing)))
    return data


def window_events(matrix: dict, data: dict) -> list:
    """The data's windows as events on the matrix's satellite rows."""
    rows = row_groups(matrix)
    events = []
    for i, w in enumerate(data["windows"]):
        if w["satellite"] not in rows:
            raise ValueError("Window %d: %r is not a row of the matrix" % (i, w["satellite"]))
        event = {"row": w["satellite"], "start": w["start"], "end": w["end"], "status": w["status"],
                 "seclab": w["seclab"]}
        event.update({k: w[k] for k in ("id", "label", "notes") if k in w})
        events.append(event)
    return events


def roll_up(events: list, row_group: dict, rank: dict) -> list:
    """Summarise per-satellite events by group (e.g. EO, IR, SAR) for a groups view.

    Overlapping windows in the same group become one event listing them, with
    their shared status (all windows are Predicted today). Overlapping windows
    with different statuses are an error rather than a silent choice. Different
    security labels are not: the merged bar takes the highest (rank: seclab_rank()).
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
            names = [e["label"][:-5] if e.get("label", "").endswith(" pass") else e["row"] for e in m["members"]]
            statuses = sorted({e["status"] for e in m["members"]})
            if len(statuses) > 1:
                raise ValueError("Overlapping %s windows at %s have different statuses (%s); a merged bar has one"
                                 % (group, m["start"], ", ".join(statuses)))
            out.append({"id": "%s-%s" % (group, m["start"][11:16].replace(":", "")),
                        "row": group,
                        "start": m["start"],
                        "end": m["end"],
                        "status": statuses[0],
                        "seclab": highest_seclab((e["seclab"] for e in m["members"]), rank),
                        "label": "%d %s pass%s" % (len(names), group, "" if len(names) == 1 else "es"),
                        "notes": "; ".join(names)})
    out.sort(key=lambda e: (e["start"], e["row"]))
    return out


def group_notes(matrix: dict, data: dict, events: list) -> dict:
    """Per-phenomenology provenance notes from the data's "evaluated" rows.

    Pass counts per group, from how many of the evaluated spacecraft. A group
    with no evaluated rows had no feed, so it gets no source or ICOD. Data
    without "evaluated" (demo) shares the file's provenance.
    """
    evaluated = data.get("evaluated")
    if evaluated is None or data.get("icod_source") == "demo":
        return {}  # demo shares the file's provenance: no pass counts for sample windows
    rows = row_groups(matrix)
    out = {}
    for group in matrix["groups"]:
        name = group["name"]
        group_rows = [r for r, g in rows.items() if g == name and r in evaluated]
        if not group_rows:
            out[name] = {"source": "No data source for %s" % name, "icod": None, "icod_source": None}
            continue
        configured = sum(len(evaluated[r]) for r in group_rows)
        group_events = [e for e in events if rows[e["row"]] == name]
        passing = len({e.get("label") for e in group_events})  # one label per spacecraft ("LEGION 3 pass")
        if group_events:
            notes = "%d predicted pass%s from %d of %d configured satellites" % (
                len(group_events), "" if len(group_events) == 1 else "es", passing, configured)
        else:
            notes = "No predicted passes from the %d configured satellites" % configured
        out[name] = {"notes": notes}
    return out


def covered_matrix(matrix: dict, data: dict) -> dict:
    """The matrix cut down to what the data file covers, so a chart shows only that.

    With "evaluated", only those rows (a file that checked EO and SAR draws
    EO and SAR; an EO row checked with no passes still shows, empty). Without
    it, the groups that have windows. Other groupings keep the same rows;
    groups left empty are dropped. A file covering nothing draws everything.
    """
    groups_of = row_groups(matrix)
    if data.get("evaluated") is not None:
        keep = set(data["evaluated"])
    else:
        with_windows = {groups_of.get(w["satellite"]) for w in data["windows"]}
        keep = {r for r, g in groups_of.items() if g in with_windows}
    if not keep & set(groups_of):
        return matrix

    def cut(groups):
        return [dict(g, rows=[r for r in g["rows"] if row_id(r) in keep]) for g in groups
                if any(row_id(r) in keep for r in g["rows"])]

    out = dict(matrix, groups=cut(matrix["groups"]))
    if "alt_groupings" in matrix:
        out["alt_groupings"] = {label: cut(groups) for label, groups in matrix["alt_groupings"].items()}
    return out


def build_view(matrix: dict, view_id: str, data: dict, ceiling: str = None) -> dict:
    """One view's payload for one data file (one place, one evaluation date).

    The chart shows what the data file covers (covered_matrix()). A colour or
    group change only re-runs this over the stored data files; the windows
    are not recomputed. ceiling: the highest security label the library may
    publish (default: the lowest label); it travels in the payload.
    """
    ceiling = ceiling or matrix["seclabs"][0]["name"]
    check_seclabs(matrix, data, ceiling)
    events = window_events(matrix, data)
    matrix = covered_matrix(matrix, data)
    config = view_config(matrix, view_id)
    notes = group_notes(matrix, data, events)
    if matrix["views"][view_id].get("rows", "satellites") == "groups":
        events = roll_up(events, row_groups(matrix), seclab_rank(matrix))
    return build_payload(config, events, date.fromisoformat(data["evaluation_date"]),
                         icod=data["icod"], icod_source=data.get("icod_source", "data"),
                         locality=data["locality"], source=data.get("source", "Data file"), provenance=notes,
                         ceiling=ceiling)


def write_views(matrix: dict, data_files, out_dir, ceiling: str = None) -> int:
    """Draw every view of every data file into <out_dir>/<view>/<locality>/<date>.json.

    ceiling: the highest security label the library may publish (build_view()).
    """
    out_dir, count = Path(out_dir), 0
    for path in data_files:
        data = load_data(path)
        for view_id in matrix["views"]:
            payload = build_view(matrix, view_id, data, ceiling)
            out = out_dir / view_id / payload["locality"]["id"] / ("%s.json" % data["evaluation_date"])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(payload, indent=2))
            count += 1
    rebuild_manifest(out_dir)
    return count

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
    -18) shade progressively darker. This replaces the original matplotlib version's three fixed
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
    data file ({"name": ..., "point": "POINT(lon lat)"} or name/lon/lat);
    there is no default.
    """
    if not locality:
        raise ValueError("No locality: give it as \"locality\" in the data file.")
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


def demo_events(groups: list, window_start: datetime, tick_minutes: int, count: int, seed: int,
                seclab: str) -> list:
    """Deterministic sample events snapped to the tick grid, all Predicted like the live data."""
    rng = random.Random(seed)
    rows = [row["id"] for group in groups for row in group["rows"]]
    slots = (24 * 60) // tick_minutes
    events = []
    for i in range(count):
        slot = rng.randrange(0, slots - 4)
        length = rng.choice([1, 1, 2, 3, 4])
        start = window_start + timedelta(minutes=tick_minutes * slot)
        events.append({"id": "demo-%02d" % i,
                       "row": rng.choice(rows),
                       "start": iso(start),
                       "end": iso(start + timedelta(minutes=tick_minutes * length)),
                       "status": "Predicted",
                       "seclab": seclab,
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
    if demo or icod_source == "demo":
        return (parse_iso(icod) if icod else now), "demo"
    if not icod:
        raise ValueError("No ICOD: give it as \"icod\" in the data file. "
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
                  provenance: dict = None, ceiling: str = None) -> dict:
    """One matrix, one locality, one UTC day.

    source: where the events came from (one line, shown on exports);
    provenance: per-group overrides for build_provenance(); ceiling: the
    library's highest security label (default: the lowest label).
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
        events = demo_events(groups, window_start, window["tick_minutes"], demo_count, seed,
                             config["seclabs"][0]["name"])
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
            "icod_ageing": config.get("icod_ageing"),
            # Labels lowest first, and the library's ceiling: the page banners the highest label drawn.
            "seclabs": {"labels": config["seclabs"], "ceiling": ceiling or config["seclabs"][0]["name"]},
            "daylight": daylight,
            "markers": markers,
            "banners": build_banners(config, window_start),
            "label": config.get("label", config["title"])}


def slugify(text: str) -> str:
    """URL id for a name: accents dropped (Galápagos -> galapagos), anything else to dashes."""
    plain = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")


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
            dates, loc, demo = [], {"name": locality_dir.name}, False
            for path in locality_dir.glob("*.json"):
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.stem):
                    continue
                with open(path, "r") as f:
                    payload = json.load(f)
                title, loc = payload.get("title", title), payload.get("locality", loc)
                label = payload.get("label", label)
                demo = demo or payload.get("icod_source") == "demo"
                dates.append({"date": path.stem,
                              "file": "%s/%s/%s" % (matrix_dir.name, locality_dir.name, path.name),
                              "events": len(payload.get("events", [])),
                              "icod": payload.get("icod"),
                              "icod_source": payload.get("icod_source")})
            if dates:
                dates.sort(key=lambda d: d["date"], reverse=True)  # newest first
                entry = {"id": locality_dir.name, "name": loc.get("name", locality_dir.name),
                         "lat": loc.get("lat"), "timezone": loc.get("timezone"), "dates": dates}
                if demo:
                    entry["demo"] = True
                localities.append(entry)
                files += len(dates)
        if localities:
            # North to south, so the Locality dropdown reads like a map; demo data last.
            localities.sort(key=lambda l: (l.get("demo", False), -(l["lat"] if l["lat"] is not None else 0)))
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
    parser.add_argument("--matrix", default=str(MATRIX), help="Matrix configuration (default: config/matrix.json)")
    parser.add_argument("--data", help="Data file: one place on one evaluation date (see load_data)")
    parser.add_argument("--view", help="One view, e.g. simplified (default: every view; --out needs one)")
    parser.add_argument("--out", help="Payload JSON to write (one view)")
    parser.add_argument("--out-dir", help="Library folder: write <view>/<locality>/<date>.json and rebuild index.json")
    parser.add_argument("--max-seclab", help="Highest security label to publish (default: the lowest label)")
    args = parser.parse_args()

    if args.rebuild_manifest:
        rebuild_manifest(args.rebuild_manifest)
        return
    if not args.data or not (args.out or args.out_dir):
        parser.error("--data and one of --out/--out-dir are required")
    if args.out and not args.view:
        parser.error("--out writes one payload: give --view")

    try:
        matrix = load_config(args.matrix)
        if args.out:
            payload = build_view(matrix, args.view, load_data(args.data), args.max_seclab)
            with open(args.out, "w") as f:
                json.dump(payload, f, indent=2)
            print("Wrote %s (%d groups, %d events)" % (args.out, len(payload["groups"]), len(payload["events"])))
        else:
            if args.view:
                matrix = dict(matrix, views={args.view: matrix["views"][args.view]})
            write_views(matrix, [args.data], args.out_dir, args.max_seclab)
    except (ValueError, KeyError) as err:
        parser.exit(2, "Error: %s\n" % err)


if __name__ == "__main__":
    main()
