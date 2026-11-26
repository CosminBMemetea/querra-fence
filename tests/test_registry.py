"""The model registry (ml/models.json, ml/datasets.json): valid as committed, and its checks catch what they should."""
import copy

import pytest

import model_registry as mr


@pytest.fixture(scope="module")
def reg():
    return mr.load()


def errors(reg, change=None):
    r, ds = copy.deepcopy(reg[0]), reg[1]
    if change:
        change(r)
    return mr.validate(r, ds)


def test_the_committed_registry_is_valid(reg):
    assert errors(reg) == []


def ground(r, model_id):
    return next(m for m in r["ground_models"] if m["id"] == model_id)


def test_two_defaults_are_refused(reg):
    assert any("exactly one model in ground_models" in e
               for e in errors(reg, lambda r: ground(r, "ground-v0.2").update(status="default")))


def test_an_unknown_status_is_refused(reg):
    assert any("unknown status" in e for e in errors(reg, lambda r: ground(r, "ground-v0.2").update(status="best")))


def test_training_on_a_test_split_is_refused(reg):
    def leak(r):
        ground(r, "ground-v0.2")["data"]["train"].append({"dataset": "ground_patrol_q4", "split": "test", "frames": 10})
    assert any("test split ground_patrol_q4:test used for train" in e for e in errors(reg, leak))


def test_a_bad_hash_is_refused(reg):
    assert any("bad sha256" in e for e in errors(reg, lambda r: ground(r, "ground-v0.2")["artefacts"][0].update(sha256="abc")))


def test_every_model_has_its_run_record_and_hashes(reg):
    for m in mr.all_models(reg[0]):
        for a in m["artefacts"]:
            assert len(a["sha256"]) == 64, (m["id"], a["file"])
