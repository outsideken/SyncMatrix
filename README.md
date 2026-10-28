# Sync Matrix (d3)

Python builds a JSON payload; a d3 page draws it. The page is made to be
embedded in a dashboard with an `<iframe>`.

```
python/export_payload.py   legacy Config_*.json (+ events) -> payload JSON
web/index.html             the renderer (embed this)
web/sync_matrix.js|css     renderer code and theme
web/vendor/d3.v7.9.0.min.js  vendored d3, so no CDN access is needed
web/data/index.json        manifest: matrices -> localities -> days (generated)
web/data/<matrix>/<locality>/<date>.json  one locality, one UTC day (demo events for now)
web/demo_dashboard.html    stand-in dashboard for testing iframe + postMessage
```

The original matplotlib notebook, configs and PNGs are included. Two Partner
settings changed for the d3 version, in both `Config_PARTNER_Sync_Matrix.json`
and the notebook cell that writes it: `"Show Sunrise/Sunset?"` is now `true`
(so Partner gets day/night shading), and the `Commercial` group is renamed
`COM` (its row id is still `CIRCUS`, which is what events reference).
Re-running that notebook cell reproduces the committed configs.

## Build payloads

```bash
python3 -m venv .venv && .venv/bin/pip install astral timezonefinder
.venv/bin/python python/export_payload.py --config Config_PARTNER_Sync_Matrix.json \
    --slug partner --date 2026-10-27 --events events.json --out-dir web/data
```

`--out-dir` writes `web/data/partner/tehran/2026-10-27.json` and rebuilds
`web/data/index.json` from the files on disk, so the new day shows up in the
page's Date dropdown. After deleting old days, run
`export_payload.py --rebuild-manifest web/data`. `--out FILE` still writes a
single payload without touching the manifest.

Use `--demo-events N` instead of `--events` for sample data; `--date` defaults
to today (UTC). The events file is

```json
{"icod": "2026-10-27T19:28:00Z",
 "locality": {"name": "Tehran", "point": "POINT(51.389722 35.688889)"},
 "events": [{"row": "EO", "start": "...", "end": "...", "status": "High", "label": "...", "notes": "..."}]}
```

with ISO 8601 UTC times; unknown rows or end-before-start fail loudly. Each
file is **one locality, one day**. The locality can also be given with
`--locality "POINT(lon lat)" --locality-name Tehran`; the config's
`"Locality Point"` is only a fallback for demos. Its timezone is looked up and
stored in the payload.

`--label` sets the name in the Matrix dropdown (default from `--slug`, e.g.
`Partner Sync Matrix`); the chart heading keeps the config's title.

## Daylight shading

The background shows day and night at the payload's locality. The
exporter samples the sun's elevation every 10 minutes (`daylight.elevations`)
and the page draws one smooth gradient: clear in daylight, then progressively
darker through civil (0 to -6 deg), nautical (to -12 deg) and astronomical
(to -18 deg) twilight to full night. This replaces the notebook's three fixed
15-minute layers, so `"Number of Shading Layers"` and `"Shading Time Delta"`
are no longer used. Hover the background for dawn, sunrise, sunset and dusk
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

The config's `"Show ICOD?"` flag is no longer used: ICOD is always shown.

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
| `icodmark=1` | Draw the ICOD line and hatch the period after it (off by default) |
| `manifest` | Manifest URL (default `data/index.json`) |
| `data` | Draw this one payload instead; no manifest, no dropdowns |
| `refresh` | Re-fetch every N seconds (0 = once); new days appear in the dropdown |
| `title=0` | Hide the title when the dashboard panel has its own header |
| `theme=dark` | Dark palette |
| `origin` | Dashboard origin trusted for `postMessage` (default: same origin only) |

Messages: the dashboard may send `{type: "sync-matrix:select", matrix, locality, date}`
or `{type: "sync-matrix:data", payload}`; the page sends `sync-matrix:ready`,
`sync-matrix:selection` (when the user changes matrix/locality/date) and
`sync-matrix:event-click` (with the event).

## Publishing through Git

Commit `web/`, including the new day files and the regenerated `index.json`.
With GitHub Pages the page and data share an origin, so the defaults just work. A raw GitHub
URL also works (it allows cross-origin reads) but is cached for about 5 minutes,
so a short `refresh` won't show changes faster than that. A private repo's raw
URLs need a token: don't put one in the iframe URL.
