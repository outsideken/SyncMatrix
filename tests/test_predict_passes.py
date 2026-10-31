"""Tests for python/predict_passes.py, against the committed TLE snapshot.

They check the physics and the rules, not exact times: passes respect each
row's elevation threshold, optical (EO) passes are in daylight, side-looking
SAR passes stay in the swath, every catalogue row is a matrix row, and the
Simplified roll-up merges overlaps.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

import export_payload as ep
import predict_passes as pp
from conftest import REPO

from astral import Observer
from astral.sun import elevation as sun_elevation

CONFIG = pp.load_catalogue(REPO / "config" / "catalogue.json")
MATRIX = ep.load_config(REPO / "config" / "matrix.json")
SNAPSHOT_PATH = sorted((REPO / "data" / "tle").glob("celestrak-*.json"))[-1]
SNAPSHOT = pp.load_snapshot(SNAPSHOT_PATH)
DAY = datetime.fromisoformat(SNAPSHOT["fetched"][:10]).replace(tzinfo=timezone.utc) + timedelta(days=1)
END = DAY + timedelta(days=1)
GROUP = ep.row_groups(MATRIX)

SITES = {"mid-north": (40, -100), "high-arctic": (78, 16), "equator": (0, 25)}


@pytest.fixture(scope="module", params=sorted(SITES))
def site(request):
    lat, lon = SITES[request.param]
    return lat, lon, pp.predict_windows(CONFIG, SNAPSHOT, lat, lon, DAY, END)


def peak_elevation(event, lat, lon):
    norad = event["norad"]
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
        assert e["status"] == "Predicted" and e["satellite"] in CONFIG["satellites"]
        assert "Celestrak" in e["notes"]


def test_passes_reach_the_rows_threshold(site):
    lat, lon, events = site
    for e in events[:12]:  # sampled: each check propagates the orbit every 10 s
        spec = CONFIG["satellites"][e["satellite"]]
        assert peak_elevation(e, lat, lon) >= spec["min_elevation"] - 0.5, e["id"]


def test_optical_passes_are_in_daylight(site):
    lat, lon, events = site
    observer = Observer(latitude=lat, longitude=lon)
    for e in events:
        if CONFIG["satellites"][e["satellite"]].get("needs_daylight"):
            peak = ep.parse_iso(e["start"]) + (ep.parse_iso(e["end"]) - ep.parse_iso(e["start"])) / 2
            assert sun_elevation(observer, peak) > -1, e["id"]


def test_optical_passes_need_the_sun_in_the_high_arctic():
    # The snapshot changes daily, so the season does too: when the sun never
    # rises at 78N that day there can be no EO passes; IR works in the dark.
    lat, lon = SITES["high-arctic"]
    events = pp.predict_windows(CONFIG, SNAPSHOT, lat, lon, DAY, END)
    observer = Observer(latitude=lat, longitude=lon)
    sun_up = any(sun_elevation(observer, DAY + timedelta(minutes=10 * i)) > 0 for i in range(145))
    if not sun_up:
        assert not [e for e in events if GROUP[e["satellite"]] == "EO"]
    assert [e for e in events if GROUP[e["satellite"]] == "IR"]


def test_side_looking_sar_stays_in_the_swath():
    lat, lon = SITES["mid-north"]
    events = pp.predict_windows(CONFIG, SNAPSHOT, lat, lon, DAY, END)
    for e in events:
        if e["satellite"] == "Sentinel-1":
            assert peak_elevation(e, lat, lon) <= CONFIG["satellites"]["Sentinel-1"]["max_elevation"] + 0.5


def test_unknown_norad_is_an_error():
    with pytest.raises(ValueError, match="not in the TLE snapshot"):
        pp.satellite(SNAPSHOT, 1)


def test_roll_up_merges_overlapping_passes():
    events = [{"row": "WorldView-1", "label": "WV-1 pass", "start": "2026-10-29T10:00:00Z", "end": "2026-10-29T10:05:00Z", "status": "Predicted", "seclab": "UNCLASSIFIED"},
              {"row": "Legion-1", "label": "LEGION 1 pass", "start": "2026-10-29T10:03:00Z", "end": "2026-10-29T10:08:00Z", "status": "Predicted", "seclab": "UNCLASSIFIED"},
              {"row": "Sentinel-1", "label": "S1A pass", "start": "2026-10-29T10:04:00Z", "end": "2026-10-29T10:06:00Z", "status": "Predicted", "seclab": "UNCLASSIFIED"},
              {"row": "Legion-2", "label": "LEGION 2 pass", "start": "2026-10-29T12:00:00Z", "end": "2026-10-29T12:02:00Z", "status": "Predicted", "seclab": "UNCLASSIFIED"}]
    rolled = ep.roll_up(events, GROUP, ep.seclab_rank(MATRIX))
    eo = [r for r in rolled if r["row"] == "EO"]
    assert [(r["start"][11:16], r["end"][11:16], r["label"]) for r in eo] == [
        ("10:00", "10:08", "2 EO passes"), ("12:00", "12:02", "1 EO pass")]
    assert eo[0]["notes"] == "WV-1; LEGION 1"
    assert [r["row"] for r in rolled].count("SAR") == 1


def test_catalogue_rows_are_matrix_rows():
    assert set(CONFIG["satellites"]) <= set(GROUP)


def test_catalogue_entries_need_norad_and_threshold(tmp_path):
    path = tmp_path / "catalogue.json"
    path.write_text(json.dumps({"satellites": {"Legion-1": {"norad": [59625]}}}))
    with pytest.raises(ValueError, match="needs \"norad\" and \"min_elevation\""):
        pp.load_catalogue(path)
    path.write_text(json.dumps({"satellites": {"Legion-1": {"norad": [59625], "min_elevation": 40}}}))
    with pytest.raises(ValueError, match="has no \"seclab\""):
        pp.load_catalogue(path)


def test_predicted_windows_carry_the_catalogue_label():
    catalogue = dict(CONFIG, satellites={"Legion-1": dict(CONFIG["satellites"]["Legion-1"], seclab="RESTRICTED"),
                                         "Legion-2": CONFIG["satellites"]["Legion-2"]})
    labels = {(e["satellite"], e["seclab"]) for e in pp.predict_windows(catalogue, SNAPSHOT, 0, 25, DAY, DAY + timedelta(days=3))}
    assert labels <= {("Legion-1", "RESTRICTED"), ("Legion-2", CONFIG["seclab"])} and labels


def test_live_simplified_provenance():
    # A place that evaluates everything: one provenance entry per phenomenology drawn.
    payload = json.loads(next((REPO / "web" / "live" / "simplified" / "tehran").glob("*.json")).read_text())
    prov = payload["provenance"]
    assert set(prov) == {"all", "EO", "IR", "SAR", "RF"}  # COM was a dummy row; it is gone
    for group in ("EO", "IR", "SAR", "RF"):
        assert prov[group]["icod"] == payload["icod"] and prov[group]["icod_source"] == "celestrak"
        assert "predicted pass" in prov[group]["notes"]


def test_live_notes_count_the_spacecraft_that_pass():
    # "N predicted passes from K of M configured satellites": K = spacecraft that pass.
    for path in (REPO / "web" / "live" / "abstracted").glob("*/*.json"):
        if path.parent.name == "demo":
            continue  # generated sample windows, not passes
        payload = json.loads(path.read_text())
        group_of = {r["id"]: g["id"] for g in payload["groups"] for r in g["rows"]}
        for group in (g["id"] for g in payload["groups"]):  # the groups this place evaluates
            events = [e for e in payload["events"] if group_of[e["row"]] == group]
            notes = payload["provenance"][group]["notes"]
            if events:
                spacecraft = len({e["label"] for e in events})
                assert notes.startswith("%d predicted pass" % len(events)), (path.name, notes)
                assert " from %d of " % spacecraft in notes, (path.name, notes)
            else:
                assert notes.startswith("No predicted passes"), (path.name, notes)


def test_windows_carry_the_pass_geometry_at_the_peak(site):
    # For a collection request: when the satellite is highest, where it is, and where the sun is.
    lat, lon, events = site
    observer = Observer(latitude=lat, longitude=lon)
    for e in events:
        g, spec = e["pass"], CONFIG["satellites"][e["satellite"]]
        assert e["start"] <= g["peak"] <= e["end"], e["id"]
        assert spec["min_elevation"] - 0.1 <= g["elevation"] <= spec.get("max_elevation", 90) + 0.1, e["id"]
        assert 0 <= g["azimuth"] < 360 and 0 <= g["sun_azimuth"] < 360
        assert g["sun_elevation"] == pytest.approx(sun_elevation(observer, ep.parse_iso(g["peak"])), abs=0.1)
        if spec.get("needs_daylight"):
            assert g["sun_elevation"] > 0
        # Clipped only where the window is the day's edge, not a rise or set.
        assert ("start" in g.get("clipped", [])) == (ep.parse_iso(e["start"]) == DAY), e["id"]
        assert ("end" in g.get("clipped", [])) == (ep.parse_iso(e["end"]) == END), e["id"]


def test_a_pass_cut_by_the_window_is_marked_clipped():
    lat, lon = SITES["mid-north"]
    e = next(e for e in pp.predict_windows(CONFIG, SNAPSHOT, lat, lon, DAY, END) if "clipped" not in e["pass"])
    sat, peak = pp.satellite(SNAPSHOT, e["norad"]), ep.parse_iso(e["pass"]["peak"])
    min_el = CONFIG["satellites"][e["satellite"]]["min_elevation"]
    [whole] = pp.passes(sat, lat, lon, ep.parse_iso(e["start"]) - timedelta(minutes=1),
                        ep.parse_iso(e["end"]) + timedelta(minutes=1), min_el)
    assert whole[5] == []
    [cut] = pp.passes(sat, lat, lon, peak - timedelta(seconds=30), peak + timedelta(seconds=30), min_el)
    assert cut[5] == ["start", "end"]
    assert cut[0] == peak - timedelta(seconds=30) and cut[2] == peak + timedelta(seconds=30)
    assert abs((cut[1] - peak).total_seconds()) < 1
