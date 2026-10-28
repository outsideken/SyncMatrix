# Sync Matrix (d3)

Python builds a JSON payload; a d3 page draws it. The page is made to be
embedded in a dashboard with an `<iframe>`.

```
config/<matrix>.json       matrix definitions: groups, rows, groupings, banners (see config/README.md)
python/export_payload.py   config + events -> payload JSON
scripts/build_demo_data.py rebuilds the demo library in web/data from config/
web/index.html             the renderer (embed this)
web/sync_matrix.js|css     renderer code and theme
web/vendor/d3.v7.9.0.min.js  vendored d3, so no CDN access is needed
web/data/index.json        manifest: matrices -> localities -> days (generated)
web/data/<matrix>/<locality>/<date>.json  one locality, one UTC day (demo events for now)
web/demo_dashboard.html    stand-in dashboard for testing iframe + postMessage
legacy/                    the original matplotlib notebook, its configs and PNGs (reference only)
```

## Matrices

Two matrices, defined in [`config/`](config/README.md):

- **Abstracted Sync Matrix** (`config/abstracted.json`): one row per satellite
  (or instrument), grouped by **phenomenology**, rows alphabetical (numbers in
  numeric order):
  - **EO**: GeoEye-1, Legion-1 to -6, WorldView-1 to -3 (Vantor); Sentinel-2;
    Sentinel-3 OLCI.
  - **IR**: the NASA FIRMS active-fire sources (Aqua and Terra MODIS; S-NPP,
    NOAA-20 and NOAA-21 VIIRS); Sentinel-3 SLSTR.
  - **SAR**: Capella Acadia satellites Capella-11 to -20; Sentinel-1.

  The same rows can be grouped by **provider** with the page's **Group by:
  Phenomenology | Provider** control: Capella; Copernicus (Sentinel-1, -2,
  -3 OLCI, -3 SLSTR); NASA FIRMS (MODIS and VIIRS); Vantor (GeoEye-1, Legion,
  WorldView).
- **Partner Sync Matrix** (`config/partner.json`): the phenomenology groups
  only (COM, IR, SAR, EO), drawn as grey bars without row labels. Always
  phenomenology, so the Group by control is hidden. The COM row's id is
  `CIRCUS`, which is what events reference.

To change a matrix, edit its config and run `python scripts/build_demo_data.py`
(CI fails if the committed demo data doesn't match the configs).

## Build payloads

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python python/export_payload.py --config config/partner.json \
    --date 2026-10-27 --events events.json --out-dir web/data
```

`--out-dir` writes `web/data/partner/mid-north-40-n/2026-10-27.json` (the
matrix id is the config file name) and rebuilds `web/data/index.json` from the
files on disk, so the new day shows up in the page's Date dropdown. After
deleting old days, run `export_payload.py --rebuild-manifest web/data`.
`--out FILE` writes a single payload without touching the manifest.

Use `--demo-events N` instead of `--events` for sample data; `--date` defaults
to today (UTC). The events file is

```json
{"icod": "2026-10-27T19:28:00Z",
 "locality": {"name": "Mid-north 40°N", "point": "POINT(-100 40)"},
 "events": [{"row": "EO", "start": "...", "end": "...", "status": "High", "label": "...", "notes": "..."}]}
```

with ISO 8601 UTC times; unknown rows or end-before-start fail loudly. Each
file is **one locality, one day**. The locality is required: in the events
file, or with `--locality "POINT(lon lat)" --locality-name "Mid-north 40°N"`.
Its timezone is looked up and stored in the payload.

`--label` overrides the name in the Matrix dropdown (default: the config's
`"label"`); the chart heading is the config's `"title"`.

## Daylight shading

The background shows day and night at the payload's locality. The
exporter samples the sun's elevation every 10 minutes (`daylight.elevations`)
and the page draws one smooth gradient: clear in daylight, then progressively
darker through civil (0 to -6 deg), nautical (to -12 deg) and astronomical
(to -18 deg) twilight to full night. This replaces the notebook's three fixed
15-minute layers. Hover the background for dawn, sunrise, sunset and dusk
times. Polar day and night need no special handling.

## ICOD (Information Cut-Off Date)

ICOD is when the data was grabbed: anything received after it is **not**
reflected in the matrix. It is provenance, so:

- It must come from the data source, as `"icod"` in the events file or `--icod`.
  The exporter refuses to run without one, or with one in the future, and never
  substitutes the export time. (The original notebook used `datetime.now()`
  because it ran on proxy data.)
- Demo payloads (`--demo-events`) are marked `icod_source: "demo"` and the page
  labels them **DEMO DATA**.
- The page always shows the ICOD and its age in the badge at the top right of
  the toolbar (with "DEMO DATA" for demo payloads), and each Date option lists
  its ICOD. When the toolbar is hidden (`controls=0` or single-file `data=`
  mode) the ICOD moves to the footer under the plot instead, so it is never
  lost. A payload without an ICOD is flagged in red as "ICOD not provided".
- To keep the chart simple, the ICOD is not drawn on the timeline by default.
  Add `icodmark=1` to the page URL to show a purple ICOD line with the period
  after it hatched ("After ICOD").
- Click messages to the dashboard carry the payload's `icod` and `icod_source`.

## Embed

```html
<iframe src="https://<host>/index.html?matrix=partner&refresh=60&title=0&origin=https://dashboard.example"
        style="width:100%;height:600px;border:0"></iframe>
```

By default the page reads `data/index.json` and shows **Matrix**, **Locality**
and **Date** dropdowns (with ◀ ▶ to step days). Locality only appears when the
chosen matrix has more than one. Changing one choice keeps the others when that
combination exists. The choice is written back into the page URL, so a reload
or shared link reopens the same view.

| Param | Meaning |
|---|---|
| `matrix`, `locality`, `date` | Initial selection (default: first matrix and locality, newest day) |
| `controls=0` | Hide the dropdowns (the dashboard selects via `postMessage`) |
| `daylight=0` | Start with the toolbar's **Day/night shading** switch off |
| `group=provider` | Start grouped by provider (Abstracted); default is the matrix's own grouping |
| `icodmark=1` | Draw the ICOD line and hatch the period after it (off by default) |
| `manifest` | Manifest URL (default `data/index.json`) |
| `data` | Draw this one payload instead; no manifest, no dropdowns |
| `refresh` | Re-fetch every N seconds (0 = once); new days appear in the dropdown |
| `title=0` | Hide the title when the dashboard panel has its own header |
| `theme=dark` | Dark palette |
| `origin` | Dashboard origin trusted for `postMessage` (default: same origin only) |

Messages: the dashboard may send `{type: "sync-matrix:select", matrix, locality, date}`,
`{type: "sync-matrix:data", payload}` or `{type: "sync-matrix:export", format: "png"|"svg"}`;
the page sends `sync-matrix:ready`, `sync-matrix:selection` (when the user
changes matrix/locality/date) and `sync-matrix:event-click` (with the event).

## Export

The toolbar's **Export: PNG | SVG** buttons download the chart as shown
(current matrix, locality, day, Y-axis grouping and day/night setting), e.g.
`abstracted_mid-north-40-n_2026-10-28_provider.png`. PNG is rendered at 2x for
slides; SVG scales cleanly. Every export carries its provenance under the
chart: the ICOD line (red, with DEMO DATA, for demo payloads) and
`Data: <file> · Y-axis: <grouping> · Exported <time>`. The title and subtitle
are always included, even with `title=0`.

When the toolbar is hidden (`controls=0`), the dashboard can trigger an export
with the `sync-matrix:export` message. Inside an `<iframe sandbox>`, downloads
need `allow-downloads`.

## Publishing through Git

Commit `web/`, including the new day files and the regenerated `index.json`.
With GitHub Pages the page and data share an origin, so the defaults just work. A raw GitHub
URL also works (it allows cross-origin reads) but is cached for about 5 minutes,
so a short `refresh` won't show changes faster than that. A private repo's raw
URLs need a token: don't put one in the iframe URL.

## Checks (CI)

`.github/workflows/ci.yml` runs on every pull request and on `main`. Run the
same checks locally before pushing:

```bash
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q tests --ignore=tests/browser
.venv/bin/python -m pytest -q tests/browser
.venv/bin/python scripts/check_data.py
.venv/bin/python scripts/check_demo_data.py
.venv/bin/python scripts/check_js_syntax.py
```

| Check | What it catches |
|---|---|
| `tests/` | Config checks (missing title, duplicate rows, a grouping with different rows, bad banner times), ICOD rules (missing or future ICOD fails, demo is labelled), locality required, the `<matrix>/<locality>/<date>.json` layout and labels, event validation, day/night shading at the extremes (midnight sun, polar night, white nights, equator), end of local day on a DST change and a +5:45 offset |
| `check_data.py` | A `web/data` file that doesn't parse, isn't in `index.json` (or is listed but missing), lacks an ICOD, or has events on unknown rows |
| `check_demo_data.py` | `web/data` out of date with `config/` or the exporter (rebuilds it into a temp folder and compares, ignoring timestamps) |
| `check_js_syntax.py` | Syntax errors in `web/*.js` and inline `<script>` blocks (needs Node.js) |
| `tests/browser/` | The real page in headless Chromium (Playwright), against the committed demo data: default view, layout (groups, 29 rows, 24 hour labels), localities north to south, ICOD badge, Group by Provider (same events), Partner always phenomenology, day/night switch, polar night and midnight sun shading, PNG/SVG export with provenance, single-file mode, the dashboard iframe. Any console error fails the test. In CI, failing pages are saved as screenshots (`playwright-results` artifact) |
