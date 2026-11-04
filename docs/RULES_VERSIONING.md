# Rules Versioning Strategy

## Purpose

Track which version of the prediction catalogue was used to generate pass windows, enabling:
1. Reproducibility: Understand why old predictions differ from current ones
2. Schema evolution: Add new rule parameters without breaking old data
3. Auditing: Know what thresholds/constraints were in effect when data was generated

## Version Fields

### `catalogue.json`

```json
{
  "version": "2026.11.02",
  "rules_schema_version": "1.0",
  "seclab": "UNCLASSIFIED",
  "satellites": { ... }
}
```

**`version`** (string, required)
- Format: `YYYY.MM.DD` (date-based versioning)
- Incremented when satellite thresholds change, satellites are added/removed, or SECLAB assignments change
- Example: Changing Sentinel-2 min_elevation from 78° to 75° bumps version to the date of the change
- This tracks the **content** of the catalogue

**`rules_schema_version`** (string, required)
- Format: Semantic versioning `MAJOR.MINOR`
- Current: `"1.0"` supports `min_elevation`, `max_elevation`, `needs_daylight`
- Increment MAJOR when adding required fields or removing fields
- Increment MINOR when adding optional fields
- This tracks the **structure** of the rules

### Data Files (when PR #30 merges)

Predicted data files (`data/predicted/<locality>/<date>.json`) will include:

```json
{
  "locality": ...,
  "evaluation_date": "2026-11-04",
  "icod": "2026-11-04T05:17:42Z",
  "rules": {
    "Sentinel-2": {"min_elevation": 78, "needs_daylight": true}
  },
  "rules_metadata": {
    "catalogue_version": "2026.11.02",
    "rules_schema_version": "1.0",
    "predicted_at": "2026-11-04T10:23:15Z"
  },
  "windows": [ ... ]
}
```

**`rules_metadata`** (object, optional)
- `catalogue_version`: The `version` from catalogue.json at prediction time
- `rules_schema_version`: The schema version used
- `predicted_at`: ISO 8601 timestamp when prediction ran

## Schema Evolution Examples

### Adding an Optional Field (MINOR version bump)

To add `min_sun_angle` for optical sensors:

1. Update `config/catalogue.json`:
   ```json
   {
     "version": "2026.12.15",
     "rules_schema_version": "1.1",  // Bumped MINOR
     "satellites": {
       "Sentinel-2": {
         "min_elevation": 78,
         "needs_daylight": true,
         "min_sun_angle": 10  // New optional field
       }
     }
   }
   ```

2. Update `python/predict_passes.py`:
   ```python
   RULE_KEYS = ("min_elevation", "max_elevation", "needs_daylight", "min_sun_angle")
   ```

3. Old data files (schema 1.0) remain valid—they lack `min_sun_angle` but that's OK for old predictions.

### Removing or Renaming a Field (MAJOR version bump)

If `needs_daylight` were replaced with `sensor_mode: optical|sar|rf`:

1. Bump to `rules_schema_version: "2.0"`
2. Update all reading code to handle both schemas:
   ```python
   if rules_schema >= "2.0":
       is_optical = rule.get("sensor_mode") == "optical"
   else:
       is_optical = rule.get("needs_daylight", False)
   ```

## Displaying Versions in UI

When PR #30's method panel shows rules, it could include:

```
How windows are calculated

Predicted with catalogue version 2026.11.02 (rules schema 1.0)
Generated: 2026-11-04 10:23 UTC
```

This makes provenance explicit to users.

## Migration Path

### Phase 1: Add version fields (this PR)
- Add `version` and `rules_schema_version` to `config/catalogue.json`
- Document versioning strategy (this file)
- No code changes yet (rules feature isn't in main)

### Phase 2: Write versions to data (after PR #30 merges)
- Update `python/workflow.py` to write `rules_metadata`
- Update `python/export_payload.py` to copy metadata to published payloads
- Add test that verifies versions are written

### Phase 3: Display versions in UI (optional enhancement)
- Show catalogue version in method panel
- Add version info to PNG/SVG exports

## Q&A

**Q: Why date-based versioning for catalogue.version?**
A: Changes happen when orbits are refreshed (daily) or when K updates thresholds. A date is more meaningful than an incrementing number.

**Q: Why not git commit SHA for versioning?**
A: The catalogue is user-editable. A SHA ties versioning to git, but the version should reflect the *content*, not the commit.

**Q: What if catalogue.version is missing?**
A: Treat as unversioned legacy data. The PR that adds rules (PR #30) was created before versioning, so early data files won't have metadata. That's OK—ICOD + source still provide provenance.

**Q: Does this slow down predictions?**
A: No. Two extra fields in the catalogue (~20 bytes) and ~50 bytes per data file for `rules_metadata`. Negligible.

## Implementation Checklist

- [x] Add `version` and `rules_schema_version` to `config/catalogue.json`
- [x] Document versioning strategy (this file)
- [ ] Update `python/workflow.py` to write `rules_metadata` (after PR #30 merges)
- [ ] Update `python/export_payload.py` to copy metadata to payloads
- [ ] Add test: `test_catalogue_version_is_written_to_data_files()`
- [ ] Update method panel to show catalogue version (optional)
- [ ] Update README to document versioning

---

**Last updated**: 2026-11-03
**Status**: Phase 1 (infrastructure added, awaiting PR #30 merge)
