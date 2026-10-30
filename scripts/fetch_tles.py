"""Snapshot current orbits (TLE/OMM) for every satellite in config/catalogue.json.

Downloads each NORAD catalogue number from Celestrak's GP API, one request
at a time with a pause (Celestrak asks clients not to hammer it, and its data
only changes every few hours), and writes

    data/tle/celestrak-<YYYY-MM-DDTHHMMZ>.json
    {"source": ..., "fetched": "<UTC time of the download>", "satellites": [OMM records]}

The "fetched" time is the ICOD of everything predicted from this snapshot.
Committing the snapshot makes the predicted library reproducible.

    python scripts/fetch_tles.py
"""

import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
URL = "https://celestrak.org/NORAD/elements/gp.php?CATNR=%d&FORMAT=json"


def norads() -> list:
    ids = set()
    for spec in json.loads((REPO / "config" / "catalogue.json").read_text())["satellites"].values():
        ids.update(spec["norad"])
    return sorted(ids)


def main() -> int:
    import argparse
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    ids = norads()
    fetched = datetime.now(timezone.utc).replace(microsecond=0)
    records = []
    for i, norad in enumerate(ids):
        if i:
            time.sleep(1)
        request = urllib.request.Request(URL % norad, headers={"User-Agent": "SyncMatrix/1 (fetch_tles.py)"})
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode()
        found = json.loads(body) if body.strip().startswith("[") else []
        if not found:
            print("WARNING: NORAD %d not found at Celestrak" % norad)
            continue
        records.extend(found)
        print("%6d  %-26s epoch %s" % (norad, found[0]["OBJECT_NAME"], found[0]["EPOCH"][:16]))

    out = REPO / "data" / "tle" / ("celestrak-%s.json" % fetched.strftime("%Y-%m-%dT%H%MZ"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"source": URL.replace("%d", "<NORAD>"),
                               "fetched": fetched.strftime("%Y-%m-%dT%H:%M:%SZ"),
                               "satellites": records}, indent=1) + "\n")
    print("Wrote %s (%d of %d satellites)" % (out.relative_to(REPO), len(records), len(ids)))
    return 0 if len(records) == len(ids) else 1


if __name__ == "__main__":
    sys.exit(main())
