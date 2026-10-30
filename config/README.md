# Configuration

Everything that defines the Sync Matrix lives here, in three files, each with
one job. The builders, checks, tests and the daily refresh read them; nothing
else lists views, satellites or localities.

```
config/
  matrix.json       draws the chart: groups, rows, colours, groupings, and its views
  catalogue.json    the prediction catalogue: which spacecraft each row covers, and when a pass counts
  workflow.json     what gets built: the shared localities, the data stores and the page's library
```

The data the chart shows is kept apart from all three, in **data files** under
`data/` (one place on one UTC evaluation date; see below). The exporter joins
the matrix and a data file and writes one payload per view; the page reads
those payloads.

```
config/catalogue.json + orbits ─┐
                                ├─► data/<store>/<locality>/<date>.json ─┐
config/workflow.json ───────────┘                                         ├─► web/live/<view>/<locality>/<date>.json
config/matrix.json ───────────────────────────────────────────────────────┘
```

| To change… | Edit | Then run | Commit |
|---|---|---|---|
| A colour, group, row order or view | `matrix.json` | `python scripts/build_views.py` (redraws; no prediction) | `config/`, `web/` |
| A threshold or a spacecraft | `catalogue.json` | `python scripts/build_all.py` | `config/`, `data/`, `web/` |
| A locality or the days | `workflow.json` | `python scripts/build_all.py` | `config/`, `data/`, `web/` |

A new satellite row goes in both `matrix.json` (where it is drawn) and
`catalogue.json` (how it is predicted).

## matrix.json

One matrix draws every view. Shortened:

```json
{
  "tick_minutes": 30,
  "show_daylight": true,
  "show_end_of_local_day": false,
  "icod_ageing": {"ageing_after_hours": 30, "stale_after_hours": 54},
  "status_styles": {"Predicted": {"fill": "tint"}, "High": {"fill": "tint"}, "Low": {"fill": "tint"}},
  "grouping": "Phenomenology",
  "groups": [
    {"name": "EO", "color": "#08519c", "tint": "#c6dbef", "rows": ["GeoEye-1", "Legion-1", "Sentinel-2", "WorldView-1"]},
    {"name": "SAR", "rows": ["Capella-11", "Sentinel-1"]}
  ],
  "alt_groupings": {
    "Provider": [
      {"name": "Capella", "rows": ["Capella-11"]},
      {"name": "Vantor", "rows": ["GeoEye-1", "Legion-1", "WorldView-1"]},
      {"name": "Copernicus", "rows": ["Sentinel-1", "Sentinel-2"]}
    ]
  },
  "views": {
    "abstracted": {"title": "Abstracted Sync Matrix", "rows": "satellites"},
    "simplified": {"title": "Simplified Sync Matrix", "rows": "groups"}
  }
}
```

| Key | Required | Meaning |
|---|---|---|
| `views` | yes | The matrices on the page. The key is the view id (`web/live/simplified/…`, `?matrix=simplified`). `title` is the chart heading, `label` the name in the Matrix dropdown (default: `title`). `rows` is `satellites` (every row; Abstracted) or `groups` (one row per group, named after it, no other groupings; Simplified). A groups view rolls the same windows up: overlapping windows in a group become one bar ("2 EO passes", names in the notes); overlapping windows with different statuses are refused |
| `groups` | yes | Y-axis groups and rows, **top to bottom as drawn**. A row is a name, or `{"id", "label"}` when the label shown differs from the id the data uses. `color` (default grey `#525252`) keys the group everywhere: its strip or bar, its event boxes, its provenance in popups and its chip on exports; `tint` (default `#d9d9d9`) is the light fill of its event boxes |
| `alt_groupings` | | Other ways to group **the same rows** (e.g. Provider), offered by the page's Group by control in `satellites` views |
| `grouping` | | Name of `groups`' grouping, shown in the Group by control |
| `tick_minutes` | | Grid spacing (default 30); hour labels are always shown |
| `show_daylight` | | Day/night shading for the payload's locality |
| `show_end_of_local_day` | | Dashed line at local midnight |
| `icod_ageing` | | Colours the ICOD badge by the data's age (ColorBrewer RdYlGn): fresh (green) under `ageing_after_hours`, ageing (amber) from it, stale (red) from `stale_after_hours`. 30 and 54 h fit the daily refresh at 05:17 UTC: amber after one missed run, red after two. Demo data stays grey; without this key the badge is the plain ICOD colour |
| `status_styles` | | How a window's `status` is drawn. Colour is always the row's group colour; the status sets the style: `fill` is `solid` (the colour), `tint` (the group's `tint`, the default) or `none` (outline only), and optional `dash` is an SVG dash pattern, e.g. `"4 3"`. The current matrix uses `{"fill": "tint"}` for every status; every window, live and demo, is `Predicted` today |
| `banners` | | Optional bars under the plot; `start`/`end` are UTC times of day (`HH:MM`, up to `24:00`); `level` 0 is nearest the plot. Not used now: the legacy banners carried each phenomenology's provenance, which now comes from the data |

The exporter refuses a matrix with missing `groups`, a view without a title,
a duplicate group or row, an alternative grouping whose rows differ from
`groups` (windows must land on the same row in every grouping), an unknown
status fill, or a banner that ends before it starts.

### Colours

ColorBrewer2, the dark end of the 9-class sequential ramps, the same in every
view: **EO `#08519c`** (Blues), **IR `#cb181d`** (Reds), **SAR `#525252`**
(Greys), **RF `#238b45`** (Greens, tint `#c7e9c0`). Lighter tints come from
the same ramps.

Provider groups (`alt_groupings.Provider`) reuse that palette, plus purple
for Vantor and orange for Unseenlabs: **Capella `#525252`**, **Copernicus
`#08519c`**, **HawkEye 360 `#238b45`**, **NASA FIRMS `#cb181d`**,
**Unseenlabs `#d94801`** (Oranges, tint `#fdd0a2`), **Vantor `#6a51a3`**
(Purples, tint `#dadaeb`). Event boxes take
the colour of the group they are shown in, so under Group by Provider they
turn provider colours; the provenance in popups and exports stays per
phenomenology.

## catalogue.json

The prediction catalogue: per matrix row, the spacecraft and the rules for a
pass to count. It writes the predicted data files; it is not part of the
drawing.

```json
{
  "satellites": {
    "Sentinel-2": {"norad": [40697, 42063, 60989], "min_elevation": 78, "needs_daylight": true},
    "Sentinel-1": {"norad": [39634, 62261, 66315], "min_elevation": 44, "max_elevation": 61}
  }
}
```

`norad` lists NORAD catalogue numbers (a mission row like Sentinel-2 lists
each spacecraft); `min_elevation` is degrees above the locality's horizon for
a pass to count; optional `max_elevation` is for side-looking SAR (the highest
point must stay at or below it, so the locality is in the swath);
`needs_daylight` is for optical rows (sun up at the locality). Every row here
must be a row of `matrix.json`. `scripts/fetch_tles.py` downloads orbits for
every NORAD number listed.

### Pass thresholds

Elevation = 90° − incidence angle, so a threshold stands in for each sensor's
field of regard. They are approximations from published sensor geometry, not
tasking rules; tune them here.

| Rows | Elevation | Why |
|---|---|---|
| GeoEye-1, Legion-1…6, WorldView-1…3 | ≥ 40°, daylight | ~45° off-nadir pointing |
| Sentinel-2 | ≥ 78°, daylight | 290 km swath, ±10° from nadir |
| Sentinel-3 OLCI | ≥ 50°, daylight | 1270 km swath |
| Sentinel-3 SLSTR | ≥ 45° | 1400 km nadir swath (thermal, day and night) |
| Aqua / Terra MODIS | ≥ 25° | ±55° scan, 2330 km swath |
| NOAA-20 / NOAA-21 / S-NPP VIIRS | ≥ 20° | ±56° scan, 3040 km swath |
| Capella-11, -13…-20 | 35°–75° | incidence ~15–55° |
| Sentinel-1 (1A, 1C, 1D) | 44°–61° | IW mode, incidence ~29–46° |
| HE360 Cluster 1–3, 5–16 (HawkEye 360); BRO-5, -6, -8, -11…-23, -31, -32 (Unseenlabs) | ≥ 20°, day and night | Commercial RF: wide field of regard, no imaging footprint |

Capella-12 is not in Celestrak's catalogue, so it has no row. Sentinel-1B is
in orbit but out of service since 2021; Sentinel-3C is left out until it is
in routine operations.

**RF rows.** HawkEye 360 flies clusters of three satellites in formation; a
row is one cluster and uses its lead satellite (HAWK-A, HAWK-2A…), so a
cluster pass is one window rather than three drawn on top of each other.
Cluster 1 is the original HAWK-A/B/C trio; there is no cluster 4 in
Celestrak. SEAHAWK-1 is an ocean-colour cubesat, not RF. Unseenlabs rows are
the BRO satellites Celestrak lists by that name, one each: BRO-5, -6, -8,
-11 to -23, -31 and -32 (there are no BRO-7, -9, -10 or -24 to -30 there). Kleos Space (KSM1) is in Celestrak but left out
while its operational status is unclear.

## workflow.json

```json
{
  "localities": [
    {"name": "High Arctic 78°N", "point": "POINT(16 78)", "kind": "reference"},
    {"name": "London", "point": "POINT(-0.1278 51.5074)", "kind": "city"}
  ],
  "folder": "web/live",
  "libraries": {
    "predicted": {"store": "data/predicted", "days": 3, "keep_snapshots": 14},
    "demo": {"store": "data/demo", "locality": {"name": "Demo", "point": "POINT(-100 40)"},
             "days": [{"date": "2026-10-28", "icod": "2026-10-28T12:00:00Z"}],
             "events_per_day": 20}
  }
}
```

- **`localities`** are shared by every view. `point` is
  `POINT(longitude latitude)`, longitude first. `kind` (`reference`, `city`
  or `sea`) is optional and informational. The timezone, sunrise and sunset,
  and the predicted passes are all worked out from the point. The page lists
  them north to south. Optional **`evaluate`** lists the matrix groups
  predicted there, e.g. `["EO", "SAR"]` (default: all). A chart draws what its
  data file evaluated, so that place's charts show EO and SAR only.
- **`folder`** is the one library the page reads: every view of every data
  file in every store is drawn there.
- **Each source of data files** in `libraries` has a `store` under `data/`.
- **`libraries.predicted`**: `days` from the orbit snapshot's date and
  `keep_snapshots` kept in `data/tle`. The daily refresh overwrites this
  store only.
- **`libraries.demo`**: one extra `locality` (the **Demo** entry, always last
  in the page's Locality list; its point sets the day/night shading), the
  demo `days` (each with its demo ICOD) and `events_per_day` sample windows
  on the matrix's satellite rows, all `Predicted` like the live data.

`load_workflow` (`python/workflow.py`) checks it first: unique names, a valid
point on the globe, a timezone for every locality (the Demo one too), a
folder, a store for each source, and every catalogue row in the matrix. `POINT` takes longitude
first. A latitude-first point is caught only when it lands off the globe (its
longitude is above 90° either way, e.g. `POINT(51.5 -120)`); one that stays
on the globe, like London as `POINT(51.5074 -0.1278)`, is accepted, so check
the map after adding a place.

## Data files

One place on one UTC evaluation date, at
`data/<store>/<locality>/<YYYY-MM-DD>.json`. A data file names no matrix or
view: every view is drawn from it.

```json
{
  "locality": {"name": "London", "point": "POINT(-0.1278 51.5074)"},
  "evaluation_date": "2026-10-30",
  "icod": "2026-10-30T11:23:26Z",
  "icod_source": "celestrak",
  "source": "Predicted passes from Celestrak orbits (celestrak-2026-10-30T1123Z.json), computed with Skyfield",
  "evaluated": {"Sentinel-1": [39634, 62261, 66315]},
  "windows": [
    {"id": "Sentinel-1-39634-0612Z", "satellite": "Sentinel-1", "norad": 39634,
     "start": "2026-10-30T06:10:41Z", "end": "2026-10-30T06:13:02Z", "status": "Predicted",
     "label": "SENTINEL-1A pass", "notes": "Highest 52° at 0612Z (sun -9°)."}
  ]
}
```

| Key | Required | Meaning |
|---|---|---|
| `locality` | yes | `name` and `POINT(lon lat)` |
| `evaluation_date` | yes | The UTC day the windows cover |
| `icod` | yes | Information Cut-Off Date: when the data was grabbed; anything newer is not reflected. Never the export time |
| `icod_source` | | Where the ICOD came from (`celestrak`; `demo` marks demo data) |
| `source` | | One line on where the windows came from, shown on exports |
| `evaluated` | | Per row, the spacecraft checked, so "no passes" is told apart from "not checked". **The chart draws exactly these rows** (in every view and grouping; empty groups are dropped), and each group's provenance notes count them. Without it, the groups that have windows are drawn |
| `windows` | yes | Access windows: `satellite` (a matrix row), `start`, `end` (ISO 8601 UTC), `status` (a `status_styles` key), plus `norad` when the window comes from the catalogue, and optional `id`, `label`, `notes` shown in popups |
