"""Rebuild the demo library in web/data from config/*.json.

Seven neutral sites from 78N to 78S and eight cities, on four dates chosen to exercise the
day/night shading (June solstice, September equinox, 28 Oct 2026, December
solstice), for every matrix. Events are deterministic samples (fixed seeds),
so re-running this reproduces the committed files apart from their
"generated" timestamp. ICODs are fixed demo values.

    python scripts/build_demo_data.py            # rebuild web/data
    python scripts/build_demo_data.py --out DIR  # build elsewhere (e.g. to compare)
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python"))

import export_payload as ep  # noqa: E402

# Neutral latitude sites (day/night extremes), then city localities (city
# centres). The predicted-pass library uses the same list.
SITES = [("High Arctic 78°N", "POINT(16 78)"),
         ("Arctic 70°N", "POINT(25 70)"),
         ("Subarctic 65°N", "POINT(25 65)"),
         ("Mid-north 40°N", "POINT(-100 40)"),
         ("Equator 0°", "POINT(25 0)"),
         ("Mid-south 40°S", "POINT(-70 -40)"),
         ("Antarctic 78°S", "POINT(166 -78)"),
         ("London", "POINT(-0.1278 51.5074)"),
         ("Tehran", "POINT(51.3890 35.6892)"),
         ("Kiev", "POINT(30.5234 50.4501)"),
         ("Tokyo", "POINT(139.6917 35.6895)"),
         ("Kathmandu", "POINT(85.3240 27.7172)"),
         ("Cairo", "POINT(31.2357 30.0444)"),
         ("Gao", "POINT(-0.0444 16.2717)"),
         ("Assisi", "POINT(12.6176 43.0707)")]

# (day, ICOD): past days cut off that evening; today and the December plan at 28 Oct 1200Z.
DAYS = [("2026-06-21", "2026-06-21T18:00:00Z"),
        ("2026-09-22", "2026-09-22T18:00:00Z"),
        ("2026-10-28", "2026-10-28T12:00:00Z"),
        ("2026-12-21", "2026-10-28T12:00:00Z")]

# Matrix -> (sample events per day, seed offset).
MATRICES = {"abstracted": (20, 0), "simplified": (8, 7)}


def seed_for(site_index: int, day: str) -> int:
    return site_index * 100 + int(day[5:7]) * 10 + int(day[-1])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(REPO / "web" / "data"), help="Data folder to write")
    args = parser.parse_args()
    out_dir = Path(args.out)

    for matrix, (count, offset) in MATRICES.items():
        config = ep.load_config(REPO / "config" / ("%s.json" % matrix))
        for i, (name, point) in enumerate(SITES, start=1):
            for day, icod in DAYS:
                payload = ep.build_payload(config, day=date.fromisoformat(day), demo_count=count,
                                           seed=seed_for(i, day) + offset, icod=icod,
                                           locality={"name": name, "point": point})
                path = out_dir / matrix / payload["locality"]["id"] / ("%s.json" % day)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, indent=2))
    ep.rebuild_manifest(out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
