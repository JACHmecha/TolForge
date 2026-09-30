"""Saved geometric fingerprints must be safe for 3D feature reattachment."""

from copy import deepcopy
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

from tolstack.domain import FeatureDefinition, PartDefinition
from tolstack.features import FeatureSignature
from tolstack.project import Project


def circle_signature():
    return {"kind": "circle", "center": [0.0, 0.0, 0.0], "normal": [0.0, 0.0, 1.0],
            "radius": 1.0, "point_count": 16, "bbox_diagonal": 2.0}


def project_with_signature():
    project = Project("Feature validation", id="legacy-project")
    project.add_part(PartDefinition("Plate", id="part"))
    project.add_feature(FeatureDefinition("part", "Hole", "circle", id="feature",
                                          signature=circle_signature()))
    return project


@pytest.mark.parametrize("field,value", [
    ("kind", "unknown"), ("center", [0, 0]), ("center", [0, 0, 0, 0]),
    ("center", [[0], [0], [0]]), ("center", [True, 0, 0]),
    ("center", ["0", 0, 0]), ("center", [0, float("nan"), 0]),
    ("normal", []), ("normal", [0, 1]), ("normal", [0, 1, 0, 0]),
    ("normal", [False, 0, 1]), ("normal", [0, 0, float("inf")]),
    ("radius", -1), ("radius", 0), ("radius", True), ("radius", "1"),
    ("radius", float("nan")), ("point_count", True), ("point_count", -1),
    ("point_count", 2.5), ("point_count", "16"), ("point_count", float("inf")),
    ("bbox_diagonal", -2), ("bbox_diagonal", True), ("bbox_diagonal", "2"),
    ("bbox_diagonal", float("inf")),
])
def test_invalid_signature_is_rejected_by_adapter_project_load_and_mutated_save(tmp_path, field, value):
    signature = circle_signature()
    signature[field] = value
    with pytest.raises(ValueError):
        FeatureSignature.from_dict(signature)

    project = project_with_signature()
    destination = tmp_path / "project.json"
    project.save(destination)
    previous = destination.read_bytes()
    payload = project.to_dict()
    payload["features"][0]["signature"] = signature
    with pytest.raises(ValueError):
        Project.from_dict(payload)
    invalid_source = tmp_path / "invalid-project.json"
    invalid_source.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        Project.load(invalid_source)

    project.features["feature"].signature = signature
    with pytest.raises(ValueError):
        project.save(destination)
    assert destination.read_bytes() == previous


@pytest.mark.parametrize("field", ["kind", "center"])
def test_required_signature_fields_have_validation_errors(field):
    data = circle_signature()
    del data[field]
    with pytest.raises(ValueError):
        FeatureSignature.from_dict(data)


@pytest.mark.parametrize("kind", ["circle", "cylinder", "plane", "point", "generic"])
def test_signature_optional_defaults_and_extra_legacy_data_remain_supported(tmp_path, kind):
    data = {"kind": kind, "center": [0.000012345678912345, 2, 3],
            "legacy_fingerprint": {"checked": True, "note": "Imported CAD"}}
    signature = FeatureSignature.from_dict(data)
    assert signature.normal is None
    assert signature.radius is None
    assert signature.point_count == 0
    assert signature.bbox_diagonal == 0.0
    assert signature.center[0] == data["center"][0]

    project = project_with_signature()
    project.features["feature"].signature = deepcopy(data)
    destination = tmp_path / "legacy.json"
    project.save(destination)
    restored = Project.load(destination)
    assert restored.features["feature"].signature == data


def test_nonpositive_radius_is_rejected_for_cylinders():
    data = circle_signature()
    data.update(kind="cylinder", radius=-0.1)
    with pytest.raises(ValueError, match="positive"):
        FeatureSignature.from_dict(data)


def test_zero_normal_remains_optional_and_large_finite_normal_is_normalized_safely():
    data = circle_signature()
    data["normal"] = [0, 0, 0]
    assert FeatureSignature.from_dict(data).normal is None
    data["normal"] = [1e308, 1e308, 1e308]
    normal = FeatureSignature.from_dict(data).normal
    assert np.all(np.isfinite(normal))
    assert np.linalg.norm(normal) == pytest.approx(1.0)


def test_mutated_in_memory_signature_revalidates_on_export():
    signature = FeatureSignature.from_dict(circle_signature())
    signature.center = np.array([0, 0])
    with pytest.raises(ValueError, match="three"):
        signature.to_dict()


def test_integral_legacy_numeric_count_is_preserved_as_a_count():
    data = circle_signature()
    data["point_count"] = 16.0
    assert FeatureSignature.from_dict(data).point_count == 16
