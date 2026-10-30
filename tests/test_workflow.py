"""Tests for config/workflow.json, config/defaults.json and the matrix merge."""

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


def test_matrices_inherit_the_defaults():
    defaults = json.loads((REPO / "config" / "defaults.json").read_text())
    for matrix in ("abstracted", "simplified"):
        own = json.loads(wf.matrix_path(matrix).read_text())
        merged = wf.load_matrix(matrix)
        for key, value in defaults.items():
            if key not in own:
                assert merged[key] == value, (matrix, key)


def test_merge_is_deep_and_override_wins():
    base = {"status_styles": {"Predicted": {"fill": "tint"}, "High": {"fill": "solid"}}, "tick_minutes": 30}
    over = {"status_styles": {"High": {"fill": "none"}}, "tick_minutes": 15}
    assert ep.merge(base, over) == {"status_styles": {"Predicted": {"fill": "tint"}, "High": {"fill": "none"}},
                                    "tick_minutes": 15}


@pytest.fixture
def workflow_copy(tmp_path):
    """A copy of config/ to break in tests (matrices are looked up next to it)."""
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


def test_unknown_matrix_is_an_error(workflow_copy, monkeypatch):
    path, data = workflow_copy
    data["libraries"]["predicted"]["roll_ups"] = ["partner"]
    with pytest.raises(ValueError, match="config/matrices/partner.json doesn't exist"):
        load(path, data, monkeypatch)


def test_new_locality_is_picked_up(workflow_copy, monkeypatch):
    path, data = workflow_copy
    data["localities"].append({"name": "Nairobi", "point": "POINT(36.8219 -1.2921)", "kind": "city"})
    assert ("Nairobi", "POINT(36.8219 -1.2921)") in wf.sites(load(path, data, monkeypatch))
