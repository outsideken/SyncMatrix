# Rules Versioning

## Purpose

Track which version of the prediction catalogue was used to generate pass windows, enabling reproducibility and schema evolution.

## Version Fields in `config/catalogue.json`

```json
{
  "version": "2026.11.04",
  "rules_schema_version": "1.0",
  "seclab": "UNCLASSIFIED",
  "satellites": { ... }
}
```

### `version` (string, required)
- Format: `YYYY.MM.DD` (date-based)
- Increment when satellite thresholds change, satellites are added/removed, or SECLAB assignments change
- Example: Changing Sentinel-2 min_elevation from 78° to 75° → bump to date of change
- Tracks the **content** of the catalogue

### `rules_schema_version` (string, required)
- Format: Semantic versioning `MAJOR.MINOR`
- Current: `"1.0"` supports `min_elevation`, `max_elevation`, `needs_daylight`
- Increment MAJOR when adding required fields or removing fields
- Increment MINOR when adding optional fields
- Tracks the **structure** of the rules

## Data Files

Predicted data files (`data/predicted/<locality>/<date>.json`) include:

```json
{
  "rules": {
    "Sentinel-2": {"min_elevation": 78, "needs_daylight": true}
  },
  "rules_metadata": {
    "catalogue_version": "2026.11.04",
    "rules_schema_version": "1.0"
  }
}
```

## Schema Evolution

### Adding an Optional Field (MINOR version bump)

To add `min_sun_angle` for optical sensors:

1. Update `config/catalogue.json`:
   - Bump `rules_schema_version` to `"1.1"`
   - Bump `version` to current date
   - Add `min_sun_angle` to relevant satellites

2. Update `python/predict_passes.py`:
   ```python
   RULE_KEYS = ("min_elevation", "max_elevation", "needs_daylight", "min_sun_angle")
   ```

3. Old data files (schema 1.0) remain valid—they lack the new field but that's OK for historical predictions.

### Breaking Changes (MAJOR version bump)

If removing or renaming fields:
- Bump to `rules_schema_version: "2.0"`
- Update all reading code to handle both schemas

## Updating the Catalogue

When changing satellite thresholds:

```bash
# Edit config/catalogue.json
# Update "version" to today's date: YYYY.MM.DD
# Update relevant satellite rules

# Regenerate all predictions
python scripts/build_all.py

# Commit with message explaining the change
git commit -m "Update Sentinel-2 min_elevation to 75° (catalogue version 2026.12.15)"
```

## Q&A

**Q: Why date-based versioning for catalogue.version?**  
A: Changes happen when orbits are refreshed (daily) or when thresholds are updated. A date is more meaningful than an incrementing number.

**Q: Why not git commit SHA for versioning?**  
A: The version should reflect the content, not the commit. The catalogue is user-editable and may be updated without git.

**Q: What if rules_metadata is missing?**  
A: Treat as unversioned legacy data. Early predictions created before versioning was added won't have metadata. ICOD + source still provide provenance.

**Q: Does this slow down predictions?**  
A: No. Two extra fields in the catalogue (~20 bytes) and ~50 bytes per data file for `rules_metadata`. Negligible impact.
