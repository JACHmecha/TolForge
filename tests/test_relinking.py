"""Heuristic proposals explain ambiguity without changing stable identities."""

from pathlib import Path

import numpy as np
import pytest

from tolstack.domain import FeatureDefinition
from tolstack.features import FeatureSignature
from tolstack.relinking import (
    plan_relinking, portable_source_path, resolve_source_path,
    source_revision_status, validate_manual_assignment,
)


def signature(kind="plane", x=0, radius=None):
    return FeatureSignature(kind, np.array([x, 0., 0.]), np.array([0., 0., 1.]), radius, 4, 10.)


def feature(name="A", x=0, kind="plane", feature_id="saved-A"):
    return FeatureDefinition("part", name, kind, signature(kind, x, 1 if kind == "circle" else None).to_dict(), id=feature_id)


def test_unique_match_retains_numeric_comparison_and_id():
    saved = feature()
    diagnostic, = plan_relinking([saved], {5: {"plane": signature(x=.2)}})
    assert diagnostic.status == "attached"
    assert diagnostic.matched_index == 5
    assert diagnostic.feature_id == "saved-A"
    assert diagnostic.best_score == pytest.approx(.02)
    assert any("Center distance 0.2" in reason for reason in diagnostic.candidates[0].reasons)
    assert saved.signature["center"] == [0., 0., 0.]


def test_ambiguous_removed_and_occupied_features_are_explained():
    candidates = {1: {"plane": signature(x=.1)}, 2: {"plane": signature(x=.2)}}
    diagnostic, = plan_relinking([feature()], candidates)
    assert diagnostic.status == "ambiguous"
    assert diagnostic.matched_index is None
    assert diagnostic.runner_up_score == pytest.approx(.02)
    far, = plan_relinking([feature(x=100)], candidates)
    assert far.status == "unresolved" and far.best_score > .15
    empty, = plan_relinking([feature()], {})
    assert empty.candidates == ()
    claimed, = plan_relinking([feature()], {1: candidates[1]}, assignments={"other": 1})
    assert claimed.status == "unresolved"
    assert claimed.candidates[0].occupied_by == "other"


def test_two_saved_features_cannot_automatically_claim_one_entity():
    a, b = feature(), feature(name="B", feature_id="saved-B")
    diagnostics = plan_relinking([a, b], {1: {"plane": signature()}})
    assert all(item.status == "ambiguous" and item.matched_index is None for item in diagnostics)
    with pytest.raises(ValueError, match="two saved features"):
        plan_relinking([a, b], {}, assignments={a.id: 1, b.id: 1})


def test_no_signature_retains_manual_candidates_with_explicit_unavailable_score():
    saved = FeatureDefinition("part", "Legacy plane", "plane", id="legacy")
    item, = plan_relinking([saved], {3: {"plane": signature()}})
    assert item.status == "unresolved"
    assert item.candidates[0].score is None
    assert "unavailable" in item.candidates[0].reasons[0]
    assert validate_manual_assignment(saved, 3, {3: {"plane": signature()}}, {}) is not None


def test_manual_assignment_rejects_wrong_kind_used_entity_and_removed_candidate():
    saved = feature()
    candidates = {1: {"circle": signature("circle", radius=1)}, 2: {"plane": signature()}}
    with pytest.raises(ValueError, match="not a plane"):
        validate_manual_assignment(saved, 1, candidates, {})
    with pytest.raises(ValueError, match="already assigned"):
        validate_manual_assignment(saved, 2, candidates, {"other": 2})
    with pytest.raises(ValueError, match="no longer"):
        validate_manual_assignment(saved, 99, candidates, {})
    assert validate_manual_assignment(saved, 2, candidates, {saved.id: 2}).kind == "plane"


def test_relative_sources_resolve_against_project_and_rebase_on_save_as(tmp_path):
    source = tmp_path / "cad" / "part.step"
    project = tmp_path / "study" / "study.json"
    stored = portable_source_path(source, project)
    assert stored == "../cad/part.step"
    assert resolve_source_path(stored, project) == source
    assert resolve_source_path("relative.step") is None
    assert resolve_source_path(str(source)) == source
    assert resolve_source_path(None, project) is None
    other = tmp_path / "other" / "study.json"
    assert resolve_source_path(portable_source_path(source, other), other) == source


@pytest.mark.parametrize("expected,loaded,status,answer", [
    ("a" * 64, "a" * 64, "verified", "unchanged"),
    ("A" * 64, "a" * 64, "verified", "unchanged"),
    ("a" * 64, "b" * 64, "verified", "changed"),
    ("a" * 64, "b" * 64, "unverified", "unverified"),
    (None, "b" * 64, "verified", "unverified"),
    ("invented", "b" * 64, "verified", "unverified"),
    ("a" * 64, "invented", "verified", "unverified"),
])
def test_revision_comparison_never_trusts_a_stored_or_unverified_hash(expected, loaded, status, answer):
    assert source_revision_status(expected, loaded, status) == answer
