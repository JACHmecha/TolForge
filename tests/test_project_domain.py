import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

from tolstack.domain import (
    AssemblyConstraint, DatumReference, DatumSystem, FeatureDefinition,
    PartDefinition, PartOccurrence, ResponseDefinition, ToleranceDefinition,
    LinearStackDefinition, StackTerm,
)
from tolstack.project import CURRENT_SCHEMA_VERSION, Project


def build_pin_hole_project() -> Project:
    project = Project(name="Pin and hole", id="project-1")
    base = project.add_part(PartDefinition(name="Base", id="part-base"))
    pin_part = project.add_part(PartDefinition(name="Pin", id="part-pin"))
    base_occ = project.add_occurrence(
        PartOccurrence(base.id, "Base:1", grounded=True, id="occ-base")
    )
    pin_occ = project.add_occurrence(PartOccurrence(pin_part.id, "Pin:1", id="occ-pin"))
    hole = project.add_feature(
        FeatureDefinition(base.id, "Mounting hole", "cylinder", id="feature-hole")
    )
    pin = project.add_feature(
        FeatureDefinition(pin_part.id, "Locating pin", "cylinder", id="feature-pin")
    )
    hole_tolerance = project.add_tolerance(
        ToleranceDefinition(
            "Hole size", "size", 10.0, 0.1, 0.0,
            feature_id=hole.id, modifier="MMC", id="tol-hole",
        )
    )
    project.add_stack(
        LinearStackDefinition(
            "Clearance stack",
            [StackTerm(hole_tolerance.id, sign=1, preview_mode="diametral", id="term-hole")],
            id="stack-1",
        )
    )
    datum = project.add_datum_reference(DatumReference(hole.id, "a", id="datum-a"))
    project.add_datum_system(DatumSystem("Base DRF", [datum.id], id="drf-base"))
    project.add_constraint(
        AssemblyConstraint(
            "Pin in hole", "concentric", base_occ.id, hole.id, pin_occ.id, pin.id,
            id="constraint-1",
        )
    )
    project.add_response(
        ResponseDefinition(
            "Diametral clearance", "clearance",
            base_occ.id, hole.id, pin_occ.id, pin.id,
            lower_limit=0.0, id="response-1",
        )
    )
    return project


def test_project_round_trip_preserves_ids_and_references(tmp_path):
    original = build_pin_hole_project()
    path = tmp_path / "pin-hole.tolforge.json"
    original.save(path)
    loaded = Project.load(path)
    assert loaded.to_dict() == original.to_dict()
    assert loaded.constraints["constraint-1"].feature_a_id == "feature-hole"
    assert loaded.stacks["stack-1"].terms[0].tolerance_id == "tol-hole"
    assert loaded.schema_version == CURRENT_SCHEMA_VERSION


def test_serialized_project_is_json_and_declares_units():
    payload = json.loads(json.dumps(build_pin_hole_project().to_dict()))
    assert payload["schema_version"] == 1
    assert payload["units"] == {"length": "mm", "angle": "deg"}
    assert isinstance(payload["parts"], list)


def test_rejects_feature_from_wrong_occurrence_part():
    project = build_pin_hole_project()
    with pytest.raises(ValueError, match="does not belong"):
        project.add_response(
            ResponseDefinition(
                "Invalid", "distance", "occ-base", "feature-pin",
                "occ-pin", "feature-hole",
            )
        )


def test_rejects_dangling_reference_when_loading():
    payload = build_pin_hole_project().to_dict()
    payload["features"][0]["part_definition_id"] = "missing-part"
    with pytest.raises(ValueError, match="unknown part"):
        Project.from_dict(payload)


def test_rejects_unversioned_bank_or_annotation_json():
    with pytest.raises(ValueError, match="not a versioned TolForge project"):
        Project.from_dict({"feature_refs": {}})


def test_tolerance_magnitudes_cannot_be_negative():
    with pytest.raises(ValueError, match="cannot be negative"):
        ToleranceDefinition("Bad", "size", 10.0, -0.1, 0.0)


def test_stack_rejects_unknown_tolerance_reference():
    project = Project("Broken stack")
    with pytest.raises(ValueError, match="unknown tolerance"):
        project.add_stack(
            LinearStackDefinition("Stack", [StackTerm("missing")])
        )
