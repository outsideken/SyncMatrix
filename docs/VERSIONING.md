# Rules Versioning

## Purpose

Track which version of the prediction rules was used to generate pass windows, enabling reproducibility and debugging. Each prediction carries a hash of the exact rules that produced it.

## How It Works

When predictions are generated for a place, the rules for the rows that place evaluates are hashed to create a unique identifier. This hash is written to every predicted data file and published payload as `rules_hash`.

## Data Files

Predicted data files (`data/predicted/<locality>/<date>.json`) include:

```json
{
  "rules": {
    "Sentinel-2": {"min_elevation": 78, "needs_daylight": true}
  },
  "rules_metadata": {
    "catalogue_version": "2026.11.04",
    "rules_hash": "a1b2c3d4e5f6"
  }
}
```

- **`catalogue_version`** (optional): Human-readable label from `config/catalogue.json`
- **`rules_hash`**: First 12 hex characters of SHA256 hash of the rules for the rows this place evaluates

The hash is **derived**, not typed, so it's always correct. Two places with identical rules for the rows they evaluate get the same hash. A change to a row that only one place evaluates changes only that place's hash.

## Updating the Catalogue

When changing satellite thresholds:

```bash
# Edit config/catalogue.json
# Update relevant satellite rules
# Optionally update "version" label to today's date

# Regenerate all predictions
python scripts/build_all.py

# Commit with message explaining the change
git commit -m "Update Sentinel-2 min_elevation to 75°"
```

The hash updates automatically when you rebuild. No manual version bumps needed.

## Q&A

**Q: Why hash instead of manual versioning?**  
A: Manual versions can go stale if someone forgets to bump them. A hash is always correct.

**Q: What if rules_metadata is missing?**  
A: Treat as unversioned legacy data. Early predictions created before versioning was added won't have metadata. ICOD + source still provide provenance.

**Q: Why keep the optional `version` label?**  
A: It's human-readable in logs and commit messages. The hash is the source of truth.

**Q: Does this slow down predictions?**  
A: No. One hash computed once per locality per day (~1 ms), ~50 bytes per data file for `rules_metadata`.
