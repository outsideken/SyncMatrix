"""Tests for config/workflow.json, the data store and the views drawn from it."""

import json
import shutil

import pytest

import export_payload as ep
import workflow as wf
from paths import REPO


def test_committed_workflow_loads():
    workflow = wf.load_workflow()
    assert len(wf.sites(workflow)) == len(workflow["localities"]) >= 1
    assert set(workflow["libraries"]) == {"predicted", "demo"}
    assert workflow["folder"] == "web/live"  # one library for the page


def test_data_files_name_no_matrix():
    # One data file draws every view: it carries the place, the date and the windows, not a matrix.
    for library in wf.load_workflow()["libraries"].values():
        path = wf.store_files(REPO / library["store"])[0]
        data = ep.load_data(path)
        assert not {"matrix", "view", "groups", "abstracted", "simplified"} & set(data)
        assert path.parent.name == ep.slugify(data["locality"]["name"])
        assert path.stem == data["evaluation_date"]


def test_every_store_file_is_drawn_in_every_view():
    # Both stores (predicted and demo) are drawn into the one library the page reads.
    workflow, matrix = wf.load_workflow(), wf.load_matrix()
    stored = {p.relative_to(p.parents[1]).as_posix() for p in wf.store_files(*wf.stores(workflow))}
    for view in matrix["views"]:
        drawn = {p.relative_to(REPO / workflow["folder"] / view).as_posix()
                 for p in (REPO / workflow["folder"] / view).glob("*/*.json")}
        assert drawn == stored, view


def test_demo_is_one_locality_listed_last():
    workflow = wf.load_workflow()
    manifest = json.loads((REPO / workflow["folder"] / "index.json").read_text())
    for matrix in manifest["matrices"]:
        *places, demo = matrix["localities"]
        assert demo["name"] == workflow["libraries"]["demo"]["locality"]["name"] and demo["demo"] is True
        assert [d["date"] for d in demo["dates"]] == sorted((d["date"] for d in workflow["libraries"]["demo"]["days"]),
                                                            reverse=True)
        assert not any(p.get("demo") for p in places)


def test_each_place_shows_the_groups_it_evaluates():
    # The examples: RF only at sea (one of them HE360 only), EO/SAR, EO/SAR/RF, IR only, and everything elsewhere.
    workflow, matrix = wf.load_workflow(), wf.load_matrix()
    group_of = ep.row_groups(matrix)
    every = [g["name"] for g in matrix["groups"]]
    for loc in workflow["localities"]:
        rows = wf.evaluated_rows(matrix, loc)
        wanted = [g for g in every if g in {group_of[r] for r in rows}]
        for view in ("abstracted", "simplified"):
            for path in (REPO / workflow["folder"] / view / ep.slugify(loc["name"])).glob("*.json"):
                payload = json.loads(path.read_text())
                assert [g["id"] for g in payload["groups"]] == wanted, (view, path.parent.name)
                if view == "abstracted":
                    assert {r["id"] for g in payload["groups"] for r in g["rows"]} == rows, path.parent.name
    mixes = {tuple(l.get("evaluate", every)) for l in workflow["localities"]}
    assert {("RF",), ("HawkEye 360",), ("EO", "SAR"), ("EO", "SAR", "RF"), ("IR",), tuple(every)} <= mixes


def test_evaluate_can_name_a_provider():
    # "HawkEye 360" (a Provider group) evaluates just its rows: the RF group with HE360 clusters only.
    workflow, matrix = wf.load_workflow(), wf.load_matrix()
    guinea = next(l for l in workflow["localities"] if l["name"] == "Gulf of Guinea")
    rows = wf.evaluated_rows(matrix, guinea)
    assert rows and all(r.startswith("HE360 Cluster") for r in rows)
    path = next((REPO / workflow["folder"] / "abstracted" / "gulf-of-guinea").glob("*.json"))
    payload = json.loads(path.read_text())
    assert [g["id"] for g in payload["groups"]] == ["RF"]
    assert [g["id"] for alt in payload["alt_groupings"] for g in alt["groups"]] == ["HawkEye 360"]
    data = json.loads(next((REPO / "data" / "predicted" / "gulf-of-guinea").glob("*.json")).read_text())
    assert set(data["evaluated"]) == rows and all(w["satellite"] in rows for w in data["windows"])


def test_evaluate_must_name_matrix_groups(workflow_copy, monkeypatch):
    path, data = workflow_copy
    data["localities"][0]["evaluate"] = ["EO", "COM"]
    with pytest.raises(ValueError, match="evaluate must list matrix groups .*got COM"):
        load(path, data, monkeypatch)
    data["localities"][0]["evaluate"] = []
    with pytest.raises(ValueError, match="evaluate must list matrix groups"):
        load(path, data, monkeypatch)


def test_demo_data_is_reproducible():
    workflow = wf.load_workflow()
    fresh = wf.demo_data(workflow, wf.load_matrix())
    store = REPO / workflow["libraries"]["demo"]["store"]
    assert len(fresh) == len(wf.store_files(store)) == len(workflow["libraries"]["demo"]["days"])
    assert fresh[0] == json.loads(wf.data_path(store, fresh[0]).read_text())


@pytest.fixture
def workflow_copy(tmp_path):
    """A copy of config/ to break in tests (matrix.json and catalogue.json are looked up next to it)."""
    config = tmp_path / "config"
    shutil.copytree(REPO / "config", config)
    path = config / "workflow.json"
    return path, json.loads(path.read_text())


def load(path, data, monkeypatch):
    path.write_text(json.dumps(data))
    monkeypatch.setattr(wf, "CONFIG", path.parent)
    return wf.load_workflow(path)


def test_duplicate_locality_is_an_error(workflow_copy, monkeypatch):
    path, data = workflow_copy
    data["localities"].append(dict(data["localities"][0]))
    with pytest.raises(ValueError, match="listed twice"):
        load(path, data, monkeypatch)


def test_latitude_first_point_is_caught(workflow_copy, monkeypatch):
    path, data = workflow_copy
    data["localities"].append({"name": "Swapped", "point": "POINT(51.5 -120.0)"})  # lat, lon by mistake
    with pytest.raises(ValueError, match="off the globe"):
        load(path, data, monkeypatch)


def test_catalogue_row_must_be_in_the_matrix(workflow_copy, monkeypatch):
    path, data = workflow_copy
    catalogue = path.parent / "catalogue.json"
    entries = json.loads(catalogue.read_text())
    entries["satellites"]["CIRCUS"] = {"norad": [1], "min_elevation": 10}
    catalogue.write_text(json.dumps(entries))
    with pytest.raises(ValueError, match="catalogue.json rows not in matrix.json: CIRCUS"):
        load(path, data, monkeypatch)


def test_library_needs_a_store(workflow_copy, monkeypatch):
    path, data = workflow_copy
    del data["libraries"]["demo"]["store"]
    with pytest.raises(ValueError, match="libraries.demo needs a store"):
        load(path, data, monkeypatch)


def test_demo_locality_name_must_be_new(workflow_copy, monkeypatch):
    path, data = workflow_copy
    data["libraries"]["demo"]["locality"]["name"] = "London"
    with pytest.raises(ValueError, match="'London' is listed twice"):
        load(path, data, monkeypatch)


def test_new_locality_is_picked_up(workflow_copy, monkeypatch):
    path, data = workflow_copy
    data["localities"].append({"name": "Nairobi", "point": "POINT(36.8219 -1.2921)", "kind": "city"})
    assert ("Nairobi", "POINT(36.8219 -1.2921)") in wf.sites(load(path, data, monkeypatch))


def test_published_windows_are_at_or_under_the_ceiling():
    # Every event in the public library, checked by its field and ranked by the matrix (not by text).
    workflow, matrix = wf.load_workflow(), wf.load_matrix()
    rank = ep.seclab_rank(matrix)
    ceiling = workflow["max_seclab"]
    payloads = list((REPO / workflow["folder"]).glob("*/*/*.json"))
    assert payloads
    for path in payloads:
        payload = json.loads(path.read_text())
        assert payload["seclabs"]["ceiling"] == ceiling, path
        for event in payload["events"]:
            assert rank[event["seclab"]] <= rank[ceiling], (path, event.get("label"))


def test_max_seclab_must_be_a_label(workflow_copy, monkeypatch):
    path, data = workflow_copy
    data["max_seclab"] = "Unclassified"
    with pytest.raises(ValueError, match="max_seclab must be a security label"):
        load(path, data, monkeypatch)
    del data["max_seclab"]
    with pytest.raises(ValueError, match="max_seclab must be a security label"):
        load(path, data, monkeypatch)


def test_labels_written_above_the_ceiling_are_refused(workflow_copy, monkeypatch):
    path, data = workflow_copy
    data["libraries"]["demo"]["seclab"] = "RESTRICTED"
    with pytest.raises(ValueError, match="libraries.demo seclab is RESTRICTED, above max_seclab UNCLASSIFIED"):
        load(path, data, monkeypatch)
    data["libraries"]["demo"]["seclab"] = "UNCLASSIFIED"
    catalogue = path.parent / "catalogue.json"
    entries = json.loads(catalogue.read_text())
    entries["satellites"]["Legion-1"]["seclab"] = "RESTRICTED"
    catalogue.write_text(json.dumps(entries))
    with pytest.raises(ValueError, match="catalogue.json Legion-1 seclab is RESTRICTED, above max_seclab"):
        load(path, data, monkeypatch)


def test_the_folder_ceiling_applies_to_every_store(tmp_path):
    # A store of its own cannot publish above the folder's ceiling: the check is on what is drawn.
    workflow, matrix = wf.load_workflow(), wf.load_matrix()
    [data] = wf.demo_data(dict(workflow, libraries=dict(workflow["libraries"], demo=dict(
        workflow["libraries"]["demo"], days=workflow["libraries"]["demo"]["days"][:1]))), matrix)
    data["windows"][0]["seclab"] = "RESTRICTED"
    wf.write_store(tmp_path / "other", [data])
    with pytest.raises(ValueError, match="above this library's ceiling UNCLASSIFIED"):
        wf.draw_library(matrix, [tmp_path / "other"], tmp_path / "web", workflow["max_seclab"])
    assert wf.draw_library(matrix, [tmp_path / "other"], tmp_path / "web", "RESTRICTED") == len(matrix["views"])


def test_published_rules_are_the_catalogues_for_the_rows_drawn():
    # The "How windows are calculated" panel reads these; they must be the catalogue's numbers, row by row.
    workflow, matrix = wf.load_workflow(), wf.load_matrix()
    catalogue = json.loads((REPO / "config" / "catalogue.json").read_text())["satellites"]
    group_of = ep.row_groups(matrix)
    order = [ep.row_id(r) for g in matrix["groups"] for r in g["rows"]]
    for loc in workflow["localities"]:
        rows = wf.evaluated_rows(matrix, loc)
        for view in ("abstracted", "simplified"):
            for path in (REPO / workflow["folder"] / view / ep.slugify(loc["name"])).glob("*.json"):
                payload = json.loads(path.read_text())
                assert list(payload["rules"]) == [r for r in order if r in rows], path
                for row, rule in payload["rules"].items():
                    spec = catalogue[row]
                    assert rule == dict({k: spec[k] for k in ("min_elevation", "max_elevation", "needs_daylight")
                                         if k in spec}, group=group_of[row]), (path, row)

    demo = sorted((REPO / workflow["folder"]).glob("*/demo/*.json"))
    assert demo and all(json.loads(p.read_text())["rules"] is None for p in demo)  # generated, not predicted


def test_catalogue_metadata_derives_hash_from_satellites():
    """catalogue_metadata() returns a hash of the satellites rules."""
    import workflow as wf
    
    # Small test catalogue
    cat1 = {
        "version": "2026.11.04",
        "satellites": {
            "TestSat-A": {"min_elevation": 40, "needs_daylight": True},
            "TestSat-B": {"min_elevation": 78}
        }
    }
    
    metadata = wf.catalogue_metadata(cat1)
    assert "rules_hash" in metadata
    assert "catalogue_version" in metadata
    assert metadata["catalogue_version"] == "2026.11.04"
    assert len(metadata["rules_hash"]) == 12
    assert all(c in "0123456789abcdef" for c in metadata["rules_hash"])
    
    # Same satellites = same hash
    cat2 = dict(cat1, version="2026.11.05")
    assert wf.catalogue_metadata(cat2)["rules_hash"] == metadata["rules_hash"]
    
    # Different satellites = different hash
    cat3 = dict(cat1, satellites={"TestSat-A": {"min_elevation": 41}})
    assert wf.catalogue_metadata(cat3)["rules_hash"] != metadata["rules_hash"]
    
    # No version is OK
    cat4 = {"satellites": cat1["satellites"]}
    metadata4 = wf.catalogue_metadata(cat4)
    assert "rules_hash" in metadata4
    assert "catalogue_version" not in metadata4


def test_predicted_data_includes_rules_metadata():
    """Predicted data files include rules_metadata with hash."""
    # Check one committed predicted file to verify the workflow writes it
    tokyo = REPO / "data/predicted/tokyo"
    assert tokyo.exists(), "tokyo predicted data missing (is a committed folder)"
    
    data_files = list(tokyo.glob("*.json"))
    assert data_files, "no tokyo predictions"
    
    data = json.loads(data_files[0].read_text())
    metadata = data.get("rules_metadata")
    
    assert metadata is not None, "missing rules_metadata"
    assert "rules_hash" in metadata, "missing rules_hash"
    assert len(metadata["rules_hash"]) == 12
    assert all(c in "0123456789abcdef" for c in metadata["rules_hash"])
    
    # If all tokyo files have the same hash, the rules were consistent
    hashes = {json.loads(p.read_text())["rules_metadata"]["rules_hash"] for p in data_files}
    assert len(hashes) == 1, f"inconsistent hashes in tokyo predictions: {hashes}"


def test_rules_hash_differs_by_evaluated_rows():
    """Places evaluating different rows get different rules_hash values."""
    import workflow as wf
    
    def place(cat, rows):
        """What predicted_data() hashes for a place evaluating `rows`."""
        return wf.catalogue_metadata(dict(cat, satellites={r: cat["satellites"][r] for r in rows}))["rules_hash"]
    
    before = {"satellites": {"A": {"min_elevation": 40}, "B": {"min_elevation": 78}}}
    after = {"satellites": {"A": {"min_elevation": 40}, "B": {"min_elevation": 75}}}  # only B changed
    
    # Different rows = different hash
    assert place(before, ["A"]) != place(before, ["B"])
    
    # B changed: a place with B changes its hash
    assert place(before, ["A", "B"]) != place(after, ["A", "B"])
    
    # A place without B keeps its hash when B changes
    assert place(before, ["A"]) == place(after, ["A"])
