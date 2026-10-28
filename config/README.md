# Matrix configs

One JSON file per matrix. The file name is the matrix id (`partner.json` →
`partner`, used in `web/data/partner/…` and `?matrix=partner`). The exporter
checks a config before building anything (`load_config` in
`python/export_payload.py`).

```json
{
  "title": "Abstracted Sync Matrix",
  "label": "Abstracted Sync Matrix",
  "tick_minutes": 30,
  "show_daylight": true,
  "show_end_of_local_day": false,
  "status_colors": {"High": "red", "Moderate": "#cb181d", "Low": "orange", "No Concern": "#525252"},
  "grouping": "Phenomenology",
  "groups": [
    {"name": "EO", "rows": ["GeoEye-1", "Legion-1", "WorldView-1"]},
    {"name": "SAR", "color": "#525252", "rows": ["Capella-11", "Sentinel-1"]}
  ],
  "alt_groupings": {
    "Provider": [
      {"name": "Capella", "rows": ["Capella-11"]},
      {"name": "Vantor", "rows": ["GeoEye-1", "Legion-1", "WorldView-1"]},
      {"name": "Copernicus", "rows": ["Sentinel-1"]}
    ]
  },
  "banners": [
    {"id": "Banner #1", "text": "BANNER #1", "start": "00:00", "end": "24:00",
     "level": 0, "fill": "#252525", "text_color": "yellow"}
  ]
}
```

| Key | Required | Meaning |
|---|---|---|
| `title` | yes | Chart heading |
| `label` | | Name in the page's Matrix dropdown (default: `title`) |
| `tick_minutes` | | Grid spacing (default 30); hour labels are always shown |
| `show_daylight` | | Day/night shading for the payload's locality |
| `show_end_of_local_day` | | Dashed line at local midnight |
| `status_colors` | | Event colour by `status` |
| `grouping` | | Name of `groups`' grouping, shown in the Group by control |
| `groups` | yes | Y-axis groups and rows, **top to bottom as drawn**. A row is a name, or `{"id", "label"}` when the label shown differs from the id events use. `color` is optional (default grey) |
| `alt_groupings` | | Other ways to group **the same rows** (e.g. Provider), offered by the page's Group by control |
| `banners` | | Bars under the plot; `start`/`end` are UTC times of day (`HH:MM`, up to `24:00`); `level` 0 is nearest the plot |

The exporter refuses a config with a missing `title`/`groups`, a duplicate
group or row, an alternative grouping whose rows differ from `groups` (events
must land on the same row in every grouping), or a banner that ends before it
starts. There is no default locality: each payload's locality comes from its
events file or `--locality`.

After editing a config, rebuild the demo data with
`python scripts/build_demo_data.py`.
