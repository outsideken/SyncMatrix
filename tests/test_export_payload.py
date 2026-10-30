"""Tests for python/export_payload.py.

These cover what reviews have been checking by hand: ICOD rules, the
matrix views and their labels, data files, the output layout, and day/night
shading at the latitudes that stress it (midnight sun, polar night, white
nights, equator).
"""

import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

import export_payload as ep
from conftest import REPO

MATRIX = REPO / "config" / "matrix.json"
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


def write_data(tmp_path, name="Mid-north 40°N", point="POINT(-100 40)", **changes):
    data = {"locality": {"name": name, "point": point}, "evaluation_date": "2026-10-27",
            "icod": "2026-10-27T12:00:00Z", "icod_source": "data", "source": "Test feed",
            "windows": [{"satellite": "Legion-3", "start": "2026-10-27T06:00:00Z", "end": "2026-10-27T06:10:00Z",
                         "status": "High", "label": "LEGION 3 pass"},
                        {"satellite": "WorldView-2", "start": "2026-10-27T06:05:00Z", "end": "2026-10-27T06:20:00Z",
                         "status": "Low", "label": "WORLDVIEW-2 pass"},
                        {"satellite": "Sentinel-1", "start": "2026-10-27T18:00:00Z", "end": "2026-10-27T18:04:00Z",
                         "status": "Predicted", "norad": 39634}]}
    data.update(changes)
    path = tmp_path / ("%s.json" % ep.slugify(name))
    path.write_text(json.dumps(data))
    return path


def test_exporter_cli_refuses_missing_icod(tmp_path):
    result = run_exporter("--data", write_data(tmp_path, icod=None), "--view", "simplified",
                          "--out", tmp_path / "out.json")
    assert result.returncode == 2
    assert "No ICOD" in result.stderr

################################################################################
## Views, labels and output layout
################################################################################

def test_out_dir_layout_and_view_labels(tmp_path):
    out = tmp_path / "web"
    result = run_exporter("--data", write_data(tmp_path), "--out-dir", out)
    assert result.returncode == 0, result.stderr

    # One data file, every view: view id = folder; dropdown label = the view's title.
    for view in ("abstracted", "simplified"):
        assert (out / view / "mid-north-40-n" / "2026-10-27.json").is_file()
    manifest = json.loads((out / "index.json").read_text())
    labels = {m["id"]: m["label"] for m in manifest["matrices"]}
    assert labels == {"abstracted": "Abstracted Sync Matrix", "simplified": "Simplified Sync Matrix"}


def test_manifest_lists_localities_north_to_south(tmp_path):
    out = tmp_path / "web"
    for name, point in (("South", "POINT(-70 -40)"), ("North", "POINT(25 65)"), ("Middle", "POINT(25 0)")):
        result = run_exporter("--data", write_data(tmp_path, name, point), "--view", "abstracted", "--out-dir", out)
        assert result.returncode == 0, result.stderr
    manifest = json.loads((out / "index.json").read_text())
    assert [m["id"] for m in manifest["matrices"]] == ["abstracted"]
    assert [l["name"] for l in manifest["matrices"][0]["localities"]] == ["North", "Middle", "South"]


def test_both_views_draw_the_same_windows(tmp_path):
    matrix = ep.load_config(MATRIX)
    data = ep.load_data(write_data(tmp_path))
    abstracted, simplified = (ep.build_view(matrix, v, data) for v in ("abstracted", "simplified"))
    assert [e["row"] for e in abstracted["events"]] == ["Legion-3", "WorldView-2", "Sentinel-1"]
    # Simplified: the overlapping EO windows are one bar with the first status in status_styles order.
    assert [(e["row"], e["start"], e["end"], e["status"], e["label"]) for e in simplified["events"]] == [
        ("EO", "2026-10-27T06:00:00Z", "2026-10-27T06:20:00Z", "High", "2 EO windows"),
        ("SAR", "2026-10-27T18:00:00Z", "2026-10-27T18:04:00Z", "Predicted", "1 SAR pass")]
    assert simplified["events"][0]["notes"] == "LEGION 3; WORLDVIEW-2"
    assert abstracted["icod"] == simplified["icod"] == "2026-10-27T12:00:00Z"


def test_simplified_draws_the_groups_as_rows():
    config = ep.load_config(MATRIX, "simplified")
    assert [(g["name"], g["rows"]) for g in config["groups"]] == [("EO", ["EO"]), ("IR", ["IR"]), ("SAR", ["SAR"])]
    assert config["label"] == "Simplified Sync Matrix"


def test_data_file_checks(tmp_path):
    with pytest.raises(ValueError, match="window 0 is missing status"):
        ep.load_data(write_data(tmp_path, windows=[{"satellite": "EO", "start": "x", "end": "y"}]))
    with pytest.raises(ValueError, match="missing 'evaluation_date'"):
        path = write_data(tmp_path)
        data = json.loads(path.read_text())
        del data["evaluation_date"]
        path.write_text(json.dumps(data))
        ep.load_data(path)
    data = ep.load_data(write_data(tmp_path, windows=[{"satellite": "CIRCUS", "start": "2026-10-27T06:00:00Z",
                                                        "end": "2026-10-27T07:00:00Z", "status": "High"}]))
    with pytest.raises(ValueError, match="'CIRCUS' is not a row"):
        ep.build_view(ep.load_config(MATRIX), "abstracted", data)


def test_unknown_view_is_an_error():
    with pytest.raises(ValueError, match="no view 'partner'"):
        ep.load_config(MATRIX, "partner")


def test_group_notes_count_evaluated_spacecraft(tmp_path):
    matrix = ep.load_config(MATRIX)
    data = ep.load_data(write_data(tmp_path, evaluated={"Legion-3": [60452], "WorldView-2": [35946],
                                                         "Sentinel-1": [39634, 62261]}))
    notes = ep.build_view(matrix, "simplified", data)["provenance"]
    assert notes["EO"]["notes"] == "2 predicted passes from 2 of 2 configured satellites"
    assert notes["SAR"]["notes"] == "1 predicted pass from 1 of 2 configured satellites"
    assert notes["IR"]["source"] == "No data source for IR"  # nothing evaluated: no feed, no ICOD
    # Without "evaluated" (demo), every group shares the file's provenance.
    assert ep.build_view(matrix, "simplified", ep.load_data(write_data(tmp_path)))["provenance"]["IR"]["source"] == "Test feed"

################################################################################
## Alternate groupings ("Group by")
################################################################################

def test_abstracted_offers_provider_grouping_over_the_same_rows():
    config = ep.load_config(MATRIX, "abstracted")
    groups = ep.build_groups(config["groups"])
    [provider] = ep.build_alt_groupings(config)
    assert (provider["id"], provider["label"]) == ("provider", "Provider")
    assert [g["label"] for g in provider["groups"]] == ["Capella", "Copernicus", "NASA FIRMS", "Vantor"]
    assert {g["label"]: (g["color"], g["tint"]) for g in provider["groups"]} == {
        "Capella": ("#525252", "#d9d9d9"), "Copernicus": ("#08519c", "#c6dbef"),
        "NASA FIRMS": ("#cb181d", "#fcbba1"), "Vantor": ("#6a51a3", "#dadaeb")}
    row_ids = lambda gs: sorted(r["id"] for g in gs for r in g["rows"])
    assert row_ids(provider["groups"]) == row_ids(groups)


def test_simplified_has_no_alternate_grouping():
    assert ep.build_alt_groupings(ep.load_config(MATRIX, "simplified")) == []

################################################################################
## Config checks
################################################################################

def write_config(tmp_path, **changes):
    config = json.loads(MATRIX.read_text())
    config.update(changes)
    path = tmp_path / "matrix.json"
    path.write_text(json.dumps(config))
    return path


def test_committed_matrix_loads():
    matrix = ep.load_config(MATRIX)
    assert list(matrix["views"]) == ["abstracted", "simplified"]
    for view in matrix["views"]:
        assert ep.load_config(MATRIX, view)["groups"]


def test_alternate_grouping_must_have_the_same_rows(tmp_path):
    config = json.loads(MATRIX.read_text())
    capella = next(g for g in config["alt_groupings"]["Provider"] if g["name"] == "Capella")
    capella["rows"].remove("Capella-11")
    with pytest.raises(ValueError, match=r"missing: \['Capella-11'\]"):
        ep.load_config(write_config(tmp_path, alt_groupings=config["alt_groupings"]))


def test_duplicate_row_is_an_error(tmp_path):
    groups = [{"name": "EO", "rows": ["GeoEye-1"]}, {"name": "IR", "rows": ["GeoEye-1"]}]
    with pytest.raises(ValueError, match="rows listed twice"):
        ep.load_config(write_config(tmp_path, groups=groups, alt_groupings={}))


def test_missing_title_is_an_error(tmp_path):
    path = write_config(tmp_path, views={})
    with pytest.raises(ValueError, match="missing 'title'"):
        ep.load_config(path)
    path = write_config(tmp_path, views={"abstracted": {"rows": "satellites"}})
    with pytest.raises(ValueError, match="view 'abstracted' has no title"):
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
    config = ep.load_config(MATRIX, "abstracted")
    prov = ep.build_provenance(config, "Events file x.json", "2026-10-28T12:00:00Z", "data")
    assert set(prov) == {"all", "EO", "IR", "SAR"}
    assert prov["EO"] == prov["all"] == {"source": "Events file x.json", "icod": "2026-10-28T12:00:00Z",
                                          "icod_source": "data"}


def test_provenance_overrides_per_phenomenology():
    config = ep.load_config(MATRIX, "abstracted")
    prov = ep.build_provenance(config, "Feeds", "2026-10-28T12:00:00Z", "data",
                               {"IR": {"source": "NASA FIRMS", "icod": "2026-10-28T09:00:00Z"}})
    assert prov["IR"] == {"source": "NASA FIRMS", "icod": "2026-10-28T09:00:00Z", "icod_source": "data"}
    assert prov["EO"]["source"] == "Feeds"


def test_payload_carries_source_provenance_and_group_colours():
    payload = ep.build_payload(ep.load_config(MATRIX, "abstracted"), day=date(2026, 10, 27), demo_count=2,
                               icod="2026-10-27T12:00:00Z", locality={"name": "X", "point": "POINT(-100 40)"})
    assert payload["source"].startswith("Demo data")
    assert payload["provenance"]["SAR"]["icod_source"] == "demo"
    assert {g["label"]: g["color"] for g in payload["groups"]} == {"EO": "#08519c", "IR": "#cb181d", "SAR": "#525252"}
    assert payload["banners"] == []  # provenance replaces the legacy banners


def test_status_styles_and_tints():
    payload = ep.build_payload(ep.load_config(MATRIX, "abstracted"), day=date(2026, 10, 27), demo_count=1,
                               icod="2026-10-27T12:00:00Z", locality={"name": "X", "point": "POINT(-100 40)"})
    assert payload["status_styles"]["Predicted"] == {"fill": "tint"}  # solid outline + light tint, for now
    assert {g["label"]: g["tint"] for g in payload["groups"]} == {"EO": "#c6dbef", "IR": "#fcbba1", "SAR": "#d9d9d9"}


def test_status_style_fill_is_checked(tmp_path):
    with pytest.raises(ValueError, match="fill must be one of solid, tint, none"):
        ep.load_config(write_config(tmp_path, status_styles={"Predicted": {"fill": "stripes"}}))


def test_config_readme_samples_are_valid(tmp_path):
    # The samples in config/README.md must stay loadable, so the docs can't drift from the format:
    # matrix.json, catalogue.json, workflow.json, then a data file drawn in every view of that matrix.
    import re
    import predict_passes as pp
    readme = (REPO / "config" / "README.md").read_text()
    matrix, catalogue, workflow, data = [json.loads(b) for b in re.findall(r"```json\n(.*?)\n```", readme, re.S)]
    assert {"localities", "libraries"} <= set(workflow) and workflow["localities"][0]["point"].startswith("POINT(")
    assert all({"store", "folder"} <= set(lib) for lib in workflow["libraries"].values())
    (tmp_path / "catalogue.json").write_text(json.dumps(catalogue))
    assert set(pp.load_catalogue(tmp_path / "catalogue.json")["satellites"]) <= set(ep.row_groups(matrix))
    (tmp_path / "matrix.json").write_text(json.dumps(matrix))
    matrix = ep.load_config(tmp_path / "matrix.json")
    assert ep.build_groups(matrix["groups"])[1]["tint"] == "#d9d9d9"  # default tint
    (tmp_path / "data.json").write_text(json.dumps(data))
    data = ep.load_data(tmp_path / "data.json")
    for view in matrix["views"]:
        payload = ep.build_view(matrix, view, data)
        assert payload["events"] and payload["icod"] == data["icod"]
