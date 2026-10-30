"""Tests for config/workflow.json, the data store and the views drawn from it."""

import json
import shutil

import pytest

import export_payload as ep
import workflow as wf
from conftest import REPO


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
