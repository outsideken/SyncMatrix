# Configuration

Everything that defines the Sync Matrix lives here, in three kinds of file.
The builders, checks, tests and the daily refresh read them; nothing else
lists matrices or localities.

```
config/
  defaults.json          settings every matrix shares
  matrices/<id>.json     one per matrix: only what differs from the defaults
  workflow.json          what gets built: the shared localities and the libraries
```

**To add a locality or change the days**, edit `workflow.json`, then run
`python scripts/build_all.py` and commit `config/` with the rebuilt `web/data`
and `web/live`. **To change a matrix**, edit its file in `matrices/` (or a
shared setting in `defaults.json`) and do the same.

## workflow.json

```json
{
  "localities": [
    {"name": "High Arctic 78°N", "point": "POINT(16 78)", "kind": "reference"},
    {"name": "London", "point": "POINT(-0.1278 51.5074)", "kind": "city"}
  ],
  "libraries": {
    "predicted": {"folder": "web/live", "days": 3, "keep_snapshots": 14,
                  "passes_from": "abstracted", "roll_ups": ["simplified"]},
    "demo": {"folder": "web/data",
             "days": [{"date": "2026-10-28", "icod": "2026-10-28T12:00:00Z"}],
             "matrices": {"abstracted": {"events_per_day": 20, "seed_offset": 0},
                          "simplified": {"events_per_day": 8, "seed_offset": 7}}}
  }
}
```

- **`localities`** are shared by every matrix and both libraries. `point` is
  `POINT(longitude latitude)`, longitude first. `kind` (`reference` or `city`)
  is optional and informational. The timezone, sunrise and sunset, and the
  predicted passes are all worked out from the point. The page lists them
  north to south. **Add new localities at the end**: the demo library seeds its
  sample events from a locality's position, so appending leaves existing demo
  data unchanged.
- **`libraries.predicted`**: `days` from the orbit snapshot's date,
  `keep_snapshots` kept in `data/tle`, `passes_from` (the matrix whose
  `satellites` are predicted) and `roll_ups` (matrices built by rolling those
  passes up into their groups).
- **`libraries.demo`**: the demo `days` (each with its demo ICOD) and, per
  matrix, `events_per_day` and `seed_offset`.

`load_workflow` (`python/workflow.py`) checks it first: unique names, a valid
point on the globe (a latitude-first point is caught), a timezone for every
locality, and every named matrix exists.

## defaults.json and matrices/

A matrix file holds only what differs; it is **merged over `defaults.json`**
(dicts merge key by key, anything else in the matrix file replaces the
default). The merge is declarative: a setting comes from the matrix file or
from the defaults, never from another matrix, so the order of files doesn't
matter. The file name is the matrix id (`matrices/simplified.json` →
`simplified`, used in `web/data/simplified/…` and `?matrix=simplified`).

`defaults.json`:

```json
{
  "tick_minutes": 30,
  "show_daylight": true,
  "show_end_of_local_day": false,
  "status_styles": {"Predicted": {"fill": "tint"}, "Collected": {"fill": "solid"}},
  "grouping": "Phenomenology"
}
```

A matrix, e.g. `matrices/abstracted.json` (shortened):

```json
{
  "title": "Abstracted Sync Matrix",
  "label": "Abstracted Sync Matrix",
  "groups": [
    {"name": "EO", "rows": ["GeoEye-1", "Legion-1", "WorldView-1"]},
    {"name": "SAR", "color": "#525252", "tint": "#d9d9d9", "rows": ["Capella-11", "Sentinel-1"]}
  ],
  "alt_groupings": {
    "Provider": [
      {"name": "Capella", "rows": ["Capella-11"]},
      {"name": "Vantor", "rows": ["GeoEye-1", "Legion-1", "WorldView-1"]},
      {"name": "Copernicus", "rows": ["Sentinel-1"]}
    ]
  }
}
```

Every key, in either file:

| Key | Required | Meaning |
|---|---|---|
| `title` | yes | Chart heading |
| `label` | | Name in the page's Matrix dropdown (default: `title`) |
| `tick_minutes` | | Grid spacing (default 30); hour labels are always shown |
| `show_daylight` | | Day/night shading for the payload's locality |
| `show_end_of_local_day` | | Dashed line at local midnight |
| `status_styles` | | How an event's `status` is drawn. Colour is always the row's phenomenology (its group's `color`); the status sets the style: `fill` is `solid` (the colour), `tint` (the group's `tint`, the default) or `none` (outline only), and optional `dash` is an SVG dash pattern, e.g. `"4 3"`. The current configs use `{"fill": "tint"}` for every status |
| `grouping` | | Name of `groups`' grouping, shown in the Group by control |
| `groups` | yes | Y-axis groups and rows, **top to bottom as drawn**. A row is a name, or `{"id", "label"}` when the label shown differs from the id events use. `color` (default grey `#525252`) keys the group everywhere: its strip or bar, its event boxes, its provenance in popups and its chip on exports; `tint` (default `#d9d9d9`) is the light fill of its event boxes |
| `alt_groupings` | | Other ways to group **the same rows** (e.g. Provider), offered by the page's Group by control |
| `banners` | | Optional bars under the plot; `start`/`end` are UTC times of day (`HH:MM`, up to `24:00`); `level` 0 is nearest the plot. Not used by the current matrices: the legacy banners carried each phenomenology's provenance, which now comes from the data (see below) |
| `satellites` | | For predicted passes: per row, `norad` (list of NORAD catalogue numbers; a mission row like Sentinel-2 lists each spacecraft), `min_elevation` (degrees above the locality's horizon for a pass to count), optional `max_elevation` (side-looking SAR: the highest point must stay at or below this so the locality is in the swath) and `needs_daylight` (optical rows: sun up at the locality) |

### Pass thresholds (Abstracted)

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

Capella-12 is not in Celestrak's catalogue, so it has no row. Sentinel-1B is
in orbit but out of service since 2021; Sentinel-3C is left out until it is
in routine operations.

The exporter refuses a config with a missing `title`/`groups`, a duplicate
group or row, an alternative grouping whose rows differ from `groups` (events
must land on the same row in every grouping), or a banner that ends before it
starts. There is no default locality: each payload's locality comes from its
events file or `--locality`.

After editing a config, rebuild the demo data with
`python scripts/build_demo_data.py`.

### Phenomenology colours

ColorBrewer2, the dark end of the 9-class sequential ramps, the same in both
matrices: **EO `#08519c`** (Blues), **IR `#cb181d`** (Reds), **SAR `#525252`**
(Greys), **COM `#238b45`** (Greens). Lighter tints, if needed, come from the
same ramps.

Provider groups (Abstracted's `alt_groupings.Provider`) reuse that palette,
plus purple for Vantor: **Capella `#525252`**, **Copernicus `#08519c`**,
**NASA FIRMS `#cb181d`**, **Vantor `#6a51a3`** (Purples, tint `#dadaeb`).
Event boxes take the colour of the group they are shown in, so under Group by
Provider they turn provider colours; the provenance in popups and exports
stays per phenomenology.
