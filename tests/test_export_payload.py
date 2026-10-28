"""Tests for python/export_payload.py.

These cover what reviews have been checking by hand: ICOD rules, the
default matrix label, the output layout, and day/night shading at the
latitudes that stress it (midnight sun, polar night, white nights, equator).
"""

import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

import export_payload as ep
from conftest import REPO

ABSTRACTED = REPO / "config" / "abstracted.json"
PARTNER = REPO / "config" / "partner.json"
EXPORTER = REPO / "python" / "export_payload.py"


def day_window(day: str):
    start = ep.parse_iso(day + "T00:00:00Z")
    return start, start + timedelta(days=1)


def run_exporter(*args):
    return subprocess.run([sys.executable, str(EXPORTER), *map(str, args)],
                          capture_output=True, text=True)

################################################################################
## ICOD
################################################################################

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)


def test_icod_missing_is_an_error():
    with pytest.raises(ValueError, match="No ICOD"):
        ep.resolve_icod(None, "data", demo=False, now=NOW)


def test_icod_in_the_future_is_an_error():
    with pytest.raises(ValueError, match="in the future"):
        ep.resolve_icod("2026-10-29T00:00:00Z", "data", demo=False, now=NOW)


def test_icod_keeps_its_source():
    icod, source = ep.resolve_icod("2026-10-28T06:00:00Z", "cli", demo=False, now=NOW)
    assert icod == datetime(2026, 10, 28, 6, 0, tzinfo=timezone.utc)
    assert source == "cli"


def test_demo_payloads_are_labelled_demo():
    _, source = ep.resolve_icod(None, "data", demo=True, now=NOW)
    assert source == "demo"


def test_exporter_cli_refuses_missing_icod(tmp_path):
    events = tmp_path / "events.json"
    events.write_text(json.dumps([{"row": "EO", "start": "2026-10-27T06:00:00Z",
                                   "end": "2026-10-27T07:00:00Z"}]))
    result = run_exporter("--config", PARTNER, "--date", "2026-10-27", "--events", events,
                          "--locality", "POINT(-100 40)", "--locality-name", "Mid-north 40°N",
                          "--out", tmp_path / "out.json")
    assert result.returncode == 2
    assert "No ICOD" in result.stderr

################################################################################
## Matrix id, label and output layout
################################################################################

def test_out_dir_layout_and_default_label(tmp_path):
    data = tmp_path / "data"
    for config, events in ((PARTNER, 3), (ABSTRACTED, 4)):
        result = run_exporter("--config", config, "--date", "2026-10-27",
                              "--icod", "2026-10-27T12:00:00Z", "--demo-events", events,
                              "--locality", "POINT(-100 40)", "--locality-name", "Mid-north 40°N",
                              "--out-dir", data)
        assert result.returncode == 0, result.stderr

    # Matrix id = config file name; dropdown label = the config's "label".
    assert (data / "partner" / "mid-north-40-n" / "2026-10-27.json").is_file()
    manifest = json.loads((data / "index.json").read_text())
    labels = {m["id"]: m["label"] for m in manifest["matrices"]}
    assert labels == {"abstracted": "Abstracted Sync Matrix", "partner": "Partner Sync Matrix"}


def test_manifest_lists_localities_north_to_south(tmp_path):
    data = tmp_path / "data"
    for name, point in (("South", "POINT(-70 -40)"), ("North", "POINT(25 65)"), ("Middle", "POINT(25 0)")):
        result = run_exporter("--config", ABSTRACTED, "--date", "2026-10-27",
                              "--demo-events", 1, "--locality", point, "--locality-name", name,
                              "--out-dir", data)
        assert result.returncode == 0, result.stderr
    manifest = json.loads((data / "index.json").read_text())
    assert [l["name"] for l in manifest["matrices"][0]["localities"]] == ["North", "Middle", "South"]

################################################################################
## Alternate groupings ("Group by")
################################################################################

def test_abstracted_offers_provider_grouping_over_the_same_rows():
    config = ep.load_config(ABSTRACTED)
    groups = ep.build_groups(config["groups"])
    [provider] = ep.build_alt_groupings(config)
    assert (provider["id"], provider["label"]) == ("provider", "Provider")
    assert [g["label"] for g in provider["groups"]] == ["Capella", "Copernicus", "NASA FIRMS", "Vantor"]
    assert {g["label"]: (g["color"], g["tint"]) for g in provider["groups"]} == {
        "Capella": ("#525252", "#d9d9d9"), "Copernicus": ("#08519c", "#c6dbef"),
        "NASA FIRMS": ("#cb181d", "#fcbba1"), "Vantor": ("#6a51a3", "#dadaeb")}
    row_ids = lambda gs: sorted(r["id"] for g in gs for r in g["rows"])
    assert row_ids(provider["groups"]) == row_ids(groups)


def test_partner_has_no_alternate_grouping():
    assert ep.build_alt_groupings(ep.load_config(PARTNER)) == []

################################################################################
## Config checks
################################################################################

def write_config(tmp_path, **changes):
    config = json.loads(ABSTRACTED.read_text())
    config.update(changes)
    path = tmp_path / "matrix.json"
    path.write_text(json.dumps(config))
    return path


def test_committed_configs_load():
    for path in (ABSTRACTED, PARTNER):
        assert ep.load_config(path)["groups"]


def test_alternate_grouping_must_have_the_same_rows(tmp_path):
    config = json.loads(ABSTRACTED.read_text())
    capella = next(g for g in config["alt_groupings"]["Provider"] if g["name"] == "Capella")
    capella["rows"].remove("Capella-11")
    with pytest.raises(ValueError, match=r"missing: \['Capella-11'\]"):
        ep.load_config(write_config(tmp_path, alt_groupings=config["alt_groupings"]))


def test_duplicate_row_is_an_error(tmp_path):
    groups = [{"name": "EO", "rows": ["GeoEye-1"]}, {"name": "IR", "rows": ["GeoEye-1"]}]
    with pytest.raises(ValueError, match="rows listed twice"):
        ep.load_config(write_config(tmp_path, groups=groups, alt_groupings={}))


def test_missing_title_is_an_error(tmp_path):
    path = write_config(tmp_path)
    config = json.loads(path.read_text())
    del config["title"]
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="missing 'title'"):
        ep.load_config(path)


def test_banner_times(tmp_path):
    with pytest.raises(ValueError, match="ends before it starts"):
        ep.load_config(write_config(tmp_path, banners=[{"text": "X", "start": "12:00", "end": "06:00", "fill": "red"}]))
    with pytest.raises(ValueError, match="not HH:MM"):
        ep.load_config(write_config(tmp_path, banners=[{"text": "X", "start": "00:00", "end": "25:00", "fill": "red"}]))
    start, _ = day_window("2026-10-27")
    [banner] = ep.build_banners({"banners": [{"text": "X", "start": "12:00", "end": "24:00", "fill": "red"}]}, start)
    assert (banner["start"], banner["end"]) == ("2026-10-27T12:00:00Z", "2026-10-28T00:00:00Z")


def test_row_with_separate_label():
    [group] = ep.build_groups([{"name": "COM", "rows": [{"id": "CIRCUS", "label": "Circus"}]}])
    assert group["rows"] == [{"id": "CIRCUS", "label": "Circus"}]
    assert group["color"] == ep.DEFAULT_GROUP_COLOR

################################################################################
## Events and locality
################################################################################

GROUPS = [{"id": "EO", "label": "EO", "color": "#525252", "rows": [{"id": "EO", "label": "EO"}]}]


def test_unknown_row_is_an_error():
    start, end = day_window("2026-10-27")
    with pytest.raises(ValueError, match="unknown row 'COM'"):
        ep.validate_events([{"row": "COM", "start": "2026-10-27T01:00:00Z", "end": "2026-10-27T02:00:00Z"}],
                           GROUPS, start, end)


def test_end_before_start_is_an_error():
    start, end = day_window("2026-10-27")
    with pytest.raises(ValueError, match="end must be after start"):
        ep.validate_events([{"row": "EO", "start": "2026-10-27T02:00:00Z", "end": "2026-10-27T01:00:00Z"}],
                           GROUPS, start, end)


def test_events_outside_the_window_are_skipped():
    start, end = day_window("2026-10-27")
    kept = ep.validate_events([{"row": "EO", "start": "2026-10-26T01:00:00Z", "end": "2026-10-26T02:00:00Z"},
                               {"row": "EO", "start": "2026-10-27T01:00:00+01:00", "end": "2026-10-27T03:00:00Z"}],
                              GROUPS, start, end)
    assert [(e["start"], e["end"]) for e in kept] == [("2026-10-27T00:00:00Z", "2026-10-27T03:00:00Z")]


def test_locality_is_required():
    with pytest.raises(ValueError, match="No locality"):
        ep.resolve_locality(None)


def test_locality_from_events_file_gets_a_timezone():
    loc = ep.resolve_locality({"name": "Mid-north 40°N", "point": "POINT(-100 40)"})
    assert loc == {"id": "mid-north-40-n", "name": "Mid-north 40°N", "lon": -100.0, "lat": 40.0,
                   "timezone": "America/Chicago"}

################################################################################
## Day/night shading across latitudes
################################################################################

def daylight(lon, lat, day):
    start, end = day_window(day)
    d = ep.build_daylight(lon, lat, start, end)
    assert len(d["elevations"]) == 24 * 60 // d["step_minutes"] + 1
    return d


def test_midnight_sun_high_arctic_june():
    d = daylight(16, 78, "2026-06-21")
    assert min(d["elevations"]) > 0
    assert "sunrise" not in d["sun"] and "sunset" not in d["sun"]


def test_polar_night_high_arctic_december():
    d = daylight(16, 78, "2026-12-21")
    assert max(d["elevations"]) < -6
    assert d["sun"] == {}  # not even civil dawn or dusk


def test_polar_night_antarctic_june():
    assert max(daylight(166, -78, "2026-06-21")["elevations"]) < -6


def test_white_night_subarctic_june():
    e = daylight(25, 65, "2026-06-21")["elevations"]
    assert min(e) > -6 and max(e) > 0  # never darker than civil twilight


def test_equator_has_short_twilight():
    sun = daylight(25, 0, "2026-09-22")["sun"]
    assert set(sun) == {"dawn", "sunrise", "sunset", "dusk"}
    twilight = ep.parse_iso(sun["sunrise"]) - ep.parse_iso(sun["dawn"])
    assert timedelta(minutes=15) < twilight < timedelta(minutes=30)

################################################################################
## End of local day
################################################################################

def test_end_of_local_day_on_european_dst_change():
    # 25 Oct 2026: Oslo leaves summer time, so local midnight is 23:00Z, not 22:00Z.
    start, end = day_window("2026-10-25")
    assert [m["time"] for m in ep.build_end_of_local_day("Europe/Oslo", start, end)] == ["2026-10-25T23:00:00Z"]


def test_end_of_local_day_quarter_hour_offset():
    # Kathmandu is UTC+5:45.
    start, end = day_window("2026-10-27")
    assert [m["time"] for m in ep.build_end_of_local_day("Asia/Kathmandu", start, end)] == ["2026-10-27T18:15:00Z"]

################################################################################
## Provenance per phenomenology
################################################################################

def test_provenance_defaults_to_the_matrix_for_every_group():
    config = ep.load_config(ABSTRACTED)
    prov = ep.build_provenance(config, "Events file x.json", "2026-10-28T12:00:00Z", "data")
    assert set(prov) == {"all", "EO", "IR", "SAR"}
    assert prov["EO"] == prov["all"] == {"source": "Events file x.json", "icod": "2026-10-28T12:00:00Z",
                                          "icod_source": "data"}


def test_provenance_overrides_per_phenomenology():
    config = ep.load_config(ABSTRACTED)
    prov = ep.build_provenance(config, "Feeds", "2026-10-28T12:00:00Z", "data",
                               {"IR": {"source": "NASA FIRMS", "icod": "2026-10-28T09:00:00Z"}})
    assert prov["IR"] == {"source": "NASA FIRMS", "icod": "2026-10-28T09:00:00Z", "icod_source": "data"}
    assert prov["EO"]["source"] == "Feeds"


def test_payload_carries_source_provenance_and_group_colours():
    payload = ep.build_payload(ep.load_config(ABSTRACTED), day=date(2026, 10, 27), demo_count=2,
                               icod="2026-10-27T12:00:00Z", locality={"name": "X", "point": "POINT(-100 40)"})
    assert payload["source"].startswith("Demo data")
    assert payload["provenance"]["SAR"]["icod_source"] == "demo"
    assert {g["label"]: g["color"] for g in payload["groups"]} == {"EO": "#08519c", "IR": "#cb181d", "SAR": "#525252"}
    assert payload["banners"] == []  # provenance replaces the legacy banners


def test_status_styles_and_tints():
    payload = ep.build_payload(ep.load_config(ABSTRACTED), day=date(2026, 10, 27), demo_count=1,
                               icod="2026-10-27T12:00:00Z", locality={"name": "X", "point": "POINT(-100 40)"})
    assert payload["status_styles"]["Predicted"] == {"fill": "tint"}  # solid outline + light tint, for now
    assert {g["label"]: g["tint"] for g in payload["groups"]} == {"EO": "#c6dbef", "IR": "#fcbba1", "SAR": "#d9d9d9"}


def test_status_style_fill_is_checked(tmp_path):
    with pytest.raises(ValueError, match="fill must be one of solid, tint, none"):
        ep.load_config(write_config(tmp_path, status_styles={"Predicted": {"fill": "stripes"}}))


def test_config_readme_sample_is_a_valid_config(tmp_path):
    # The sample in config/README.md must stay loadable, so the docs can't drift from the format.
    import re
    readme = (REPO / "config" / "README.md").read_text()
    sample = re.search(r"```json\n(.*?)\n```", readme, re.S).group(1)
    path = tmp_path / "sample.json"
    path.write_text(sample)
    config = ep.load_config(path)
    assert "status_styles" in config and "status_colors" not in config
    assert ep.build_groups(config["groups"])[1]["tint"] == "#d9d9d9"
