"""Tests for python/predict_passes.py, against the committed TLE snapshot.

They check the physics and the rules, not exact times: passes respect each
row's elevation threshold, optical (EO) passes are in daylight, side-looking
SAR passes stay in the swath, and the Partner roll-up merges overlaps.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

import export_payload as ep
import predict_passes as pp
from conftest import REPO

from astral import Observer
from astral.sun import elevation as sun_elevation

CONFIG = ep.load_config(REPO / "config" / "abstracted.json")
SNAPSHOT_PATH = sorted((REPO / "data" / "tle").glob("celestrak-*.json"))[-1]
SNAPSHOT = pp.load_snapshot(SNAPSHOT_PATH)
DAY = datetime.fromisoformat(SNAPSHOT["fetched"][:10]).replace(tzinfo=timezone.utc) + timedelta(days=1)
END = DAY + timedelta(days=1)
GROUP = {r: g["name"] for g in CONFIG["groups"] for r in g["rows"]}

SITES = {"mid-north": (40, -100), "high-arctic": (78, 16), "equator": (0, 25)}


@pytest.fixture(scope="module", params=sorted(SITES))
def site(request):
    lat, lon = SITES[request.param]
    return lat, lon, pp.predict_events(CONFIG, SNAPSHOT, lat, lon, DAY, END)


def peak_elevation(event, lat, lon):
    norad = int(event["id"].split("-")[-2])
    sat = pp.satellite(SNAPSHOT, norad)
    best = 0
    t = ep.parse_iso(event["start"])
    while t <= ep.parse_iso(event["end"]):
        alt, _, _ = (sat - pp.wgs84.latlon(lat, lon)).at(pp.TS.from_datetime(t)).altaz()
        best = max(best, alt.degrees)
        t += timedelta(seconds=10)
    return best


def test_every_row_has_satellites_in_the_snapshot():
    for row, spec in CONFIG["satellites"].items():
        for norad in spec["norad"]:
            assert pp.satellite(SNAPSHOT, norad) is not None, row


def test_passes_are_inside_the_day_and_well_formed(site):
    _, _, events = site
    assert events, "expected some passes in a day"
    for e in events:
        assert DAY <= ep.parse_iso(e["start"]) <= ep.parse_iso(e["end"]) <= END
        assert e["status"] == "Predicted" and e["row"] in CONFIG["satellites"]
        assert "Celestrak" in e["notes"]


def test_passes_reach_the_rows_threshold(site):
    lat, lon, events = site
    for e in events[:12]:  # sampled: each check propagates the orbit every 10 s
        spec = CONFIG["satellites"][e["row"]]
        assert peak_elevation(e, lat, lon) >= spec["min_elevation"] - 0.5, e["id"]


def test_optical_passes_are_in_daylight(site):
    lat, lon, events = site
    observer = Observer(latitude=lat, longitude=lon)
    for e in events:
        if CONFIG["satellites"][e["row"]].get("needs_daylight"):
            peak = ep.parse_iso(e["start"]) + (ep.parse_iso(e["end"]) - ep.parse_iso(e["start"])) / 2
            assert sun_elevation(observer, peak) > -1, e["id"]


def test_no_optical_passes_in_high_arctic_late_october():
    lat, lon = SITES["high-arctic"]
    events = pp.predict_events(CONFIG, SNAPSHOT, lat, lon, DAY, END)
    assert not [e for e in events if GROUP[e["row"]] == "EO"]  # sun never gets up
    assert [e for e in events if GROUP[e["row"]] == "IR"]      # thermal works in the dark


def test_side_looking_sar_stays_in_the_swath():
    lat, lon = SITES["mid-north"]
    events = pp.predict_events(CONFIG, SNAPSHOT, lat, lon, DAY, END)
    for e in events:
        if e["row"] == "Sentinel-1":
            assert peak_elevation(e, lat, lon) <= CONFIG["satellites"]["Sentinel-1"]["max_elevation"] + 0.5


def test_unknown_norad_is_an_error():
    with pytest.raises(ValueError, match="not in the TLE snapshot"):
        pp.satellite(SNAPSHOT, 1)


def test_roll_up_merges_overlapping_passes():
    events = [{"row": "WorldView-1", "label": "WV-1 pass", "start": "2026-10-29T10:00:00Z", "end": "2026-10-29T10:05:00Z"},
              {"row": "Legion-1", "label": "LEGION 1 pass", "start": "2026-10-29T10:03:00Z", "end": "2026-10-29T10:08:00Z"},
              {"row": "Sentinel-1", "label": "S1A pass", "start": "2026-10-29T10:04:00Z", "end": "2026-10-29T10:06:00Z"},
              {"row": "Legion-2", "label": "LEGION 2 pass", "start": "2026-10-29T12:00:00Z", "end": "2026-10-29T12:02:00Z"}]
    rolled = pp.roll_up(events, GROUP)
    eo = [r for r in rolled if r["row"] == "EO"]
    assert [(r["start"][11:16], r["end"][11:16], r["label"]) for r in eo] == [
        ("10:00", "10:08", "2 EO passes"), ("12:00", "12:02", "1 EO pass")]
    assert eo[0]["notes"] == "WV-1; LEGION 1"
    assert [r["row"] for r in rolled].count("SAR") == 1


def test_config_satellites_must_be_rows(tmp_path):
    config = json.loads((REPO / "config" / "abstracted.json").read_text())
    config["satellites"]["Not-A-Row"] = {"norad": [1], "min_elevation": 10}
    path = tmp_path / "abstracted.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="'Not-A-Row' is not a row"):
        ep.load_config(path)


def test_live_partner_provenance():
    payload = json.loads(next((REPO / "web" / "live" / "partner").glob("*/*.json")).read_text())
    prov = payload["provenance"]
    assert prov["COM"]["icod"] is None and "No data source" in prov["COM"]["source"]  # no COM feed
    for group in ("EO", "IR", "SAR"):
        assert prov[group]["icod"] == payload["icod"] and prov[group]["icod_source"] == "celestrak"
        assert "predicted pass" in prov[group]["notes"]
