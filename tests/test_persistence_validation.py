"""Engineering state must be revalidated after mutation at persistence boundaries."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

from tolstack.bank import DimensionBank, DimensionTemplate
from tolstack.domain import (
    AssemblyConstraint, DatumReference, DatumSystem, Distribution,
    FeatureDefinition, LinearStackDefinition, PartDefinition, PartOccurrence,
    PositionControlDefinition, PositionPatternMember, ResponseDefinition,
    StackTerm, ToleranceDefinition,
)
from tolstack.project import Project


def engineering_project():
    project = Project("Validation example", id="legacy-project")
    project.add_part(PartDefinition("Plate", id="part"))
    project.add_occurrence(PartOccurrence("part", "Plate:1", id="occurrence"))
    project.add_feature(FeatureDefinition("part", "Hole", "circle", id="feature"))
    project.add_tolerance(ToleranceDefinition(
        "Diameter", "size", 10.0, 0.2, 0.1, feature_id="feature", id="tolerance",
        distribution=Distribution("normal", {"cpk": 1.33}),
    ))
    project.add_stack(LinearStackDefinition(
        "Chain", [StackTerm("tolerance", id="term")], id="stack",
    ))
    project.add_datum_reference(DatumReference("feature", "A", id="datum"))
    project.add_datum_system(DatumSystem("Frame", ["datum"], id="system"))
    project.add_position_control(PositionControlDefinition(
        "Position", "system", 0.2, members=[PositionPatternMember(
            "Hole", "feature", 1.0, 2.0, "tolerance", "tolerance", "tolerance",
            id="member",
        )], id="control",
    ))
    project.add_constraint(AssemblyConstraint(
        "Contact", "contact", "occurrence", "feature", "occurrence", "feature",
        id="constraint",
    ))
    project.add_response(ResponseDefinition(
        "Distance", "distance", "occurrence", "feature", "occurrence", "feature",
        lower_limit=0.0, upper_limit=1.0, id="response",
    ))
    return project


def set_path(root, path, value):
    for component in path[:-1]:
        root = root[component] if isinstance(root, (dict, list)) else getattr(root, component)
    if isinstance(root, (dict, list)):
        root[path[-1]] = value
    else:
        setattr(root, path[-1], value)


INVALID_PROJECT_MUTATIONS = [
    (("name",), ""),
    (("id",), None),
    (("schema_version",), True),
    (("parts", "part", "id"), "changed-key"),
    (("parts", "part", "name"), "  "),
    (("parts", "part", "source_file"), 1),
    (("occurrences", "occurrence", "transform", "translation"), (0, float("nan"), 0)),
    (("occurrences", "occurrence", "transform", "rotation"), (2, 0, 0, 0)),
    (("occurrences", "occurrence", "transform", "rotation"), (1e308, 0, 0, 0)),
    (("occurrences", "occurrence", "transform", "translation"), "123"),
    (("occurrences", "occurrence", "transform", "translation"), (0, 0)),
    (("occurrences", "occurrence", "grounded"), 1),
    (("occurrences", "occurrence", "part_definition_id"), "missing"),
    (("features", "feature", "kind"), "unknown"),
    (("features", "feature", "metadata"), {"fit": [0.0, {"radius": float("inf")}]}),
    (("features", "feature", "signature"), {"center": [0, float("nan"), 0]}),
    (("features", "feature", "metadata"), []),
    (("features", "feature", "signature"), [1, 2, 3]),
    (("tolerances", "tolerance", "nominal"), float("nan")),
    (("tolerances", "tolerance", "nominal"), "10"),
    (("tolerances", "tolerance", "tolerance_plus"), -0.1),
    (("tolerances", "tolerance", "tolerance_minus"), float("inf")),
    (("tolerances", "tolerance", "tolerance_minus"), True),
    (("tolerances", "tolerance", "modifier"), "unknown"),
    (("tolerances", "tolerance", "feature_id"), "missing"),
    (("tolerances", "tolerance", "distribution", "kind"), "unknown"),
    (("tolerances", "tolerance", "distribution", "parameters"), []),
    (("tolerances", "tolerance", "distribution", "parameters", "cpk"), 0),
    (("tolerances", "tolerance", "distribution", "parameters", "cpk"), float("nan")),
    (("tolerances", "tolerance", "distribution", "parameters", "cpk"), True),
    (("tolerances", "tolerance", "distribution", "correlation_group"), 2),
    (("stacks", "stack", "terms", 0, "id"), ""),
    (("stacks", "stack", "terms", 0, "sign"), True),
    (("stacks", "stack", "terms", 0, "sign"), 1.0),
    (("stacks", "stack", "terms", 0, "preview_mode"), "unknown"),
    (("stacks", "stack", "terms", 0, "tolerance_id"), "missing"),
    (("stacks", "stack", "response_id"), "missing"),
    (("datum_references", "datum", "label"), ""),
    (("datum_references", "datum", "modifier"), "unknown"),
    (("datum_systems", "system", "datum_reference_ids"), []),
    (("datum_systems", "system", "datum_reference_ids"), ["datum", "datum"]),
    (("datum_systems", "system", "datum_reference_ids"), ["missing"]),
    (("position_controls", "control", "base_tolerance_diameter"), -0.1),
    (("position_controls", "control", "mmc_size"), float("nan")),
    (("position_controls", "control", "lmc_size"), float("inf")),
    (("position_controls", "control", "members", 0, "basic_x"), float("nan")),
    (("position_controls", "control", "members", 0, "feature_id"), "missing"),
    (("position_controls", "control", "members", 0, "size_tolerance_id"), "missing"),
    (("constraints", "constraint", "kind"), "unknown"),
    (("responses", "response", "feature_b_id"), "missing"),
    (("responses", "response", "lower_limit"), 2.0),
    (("responses", "response", "upper_limit"), float("nan")),
    (("study",), {"lower_limit": True, "upper_limit": 2.0}),
    (("study",), {"extra": {"values": [float("-inf")]}}),
    (("study",), {"extra": object()}),
    (("parts",), []),
    (("parts", "part"), {"id": "part"}),
]


@pytest.mark.parametrize("path,value", INVALID_PROJECT_MUTATIONS)
def test_mutated_project_is_rejected_before_overwriting_valid_file(tmp_path, path, value):
    project = engineering_project()
    destination = tmp_path / "project.json"
    project.save(destination)
    previous = destination.read_bytes()
    set_path(project, path, value)
    with pytest.raises(ValueError):
        project.validate()
    with pytest.raises(ValueError):
        project.save(destination)
    assert destination.read_bytes() == previous


@pytest.mark.parametrize("collection,key,child_list", [
    ("stacks", "stack", "terms"),
    ("position_controls", "control", "members"),
])
def test_mutated_duplicate_nested_ids_are_rejected(collection, key, child_list):
    project = engineering_project()
    children = getattr(getattr(project, collection)[key], child_list)
    children.append(children[0])
    with pytest.raises(ValueError, match="duplicate"):
        project.validate()


@pytest.mark.parametrize("field,value", [
    ("nominal", float("nan")), ("tol_plus", -0.1), ("tol_minus", float("inf")),
    ("cpk", 0.0), ("cpk", -1.0), ("cpk", float("nan")), ("cpk", True), ("name", ""),
])
def test_bank_add_load_and_save_share_validation_and_preserve_prior_data(tmp_path, field, value):
    valid = DimensionTemplate("Spacer", 1.234567890123, 0.1, 0.2, 1.33)
    bank = DimensionBank({"Spacer": valid})
    destination = tmp_path / "bank.json"
    bank.save(destination)
    previous = destination.read_bytes()
    candidate = DimensionTemplate("Spacer", 2.0, 0.1, 0.2, 1.33)
    setattr(candidate, field, value)
    with pytest.raises(ValueError):
        bank.add(candidate, overwrite=True)
    assert bank.get("Spacer") is valid

    valid_payload = json.loads(previous)
    valid_payload["Spacer"][field] = value
    bad_input = tmp_path / "invalid-bank.json"
    bad_input.write_text(json.dumps(valid_payload), encoding="utf-8")
    with pytest.raises(ValueError):
        DimensionBank.load(bad_input)

    setattr(valid, field, value)
    with pytest.raises(ValueError):
        bank.save(destination)
    assert destination.read_bytes() == previous
    with pytest.raises(ValueError):
        bank.to_dimension("Spacer")


@pytest.mark.parametrize("loader", [Project.load, DimensionBank.load])
@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1e400"])
def test_nonfinite_json_is_rejected_at_any_depth(tmp_path, loader, literal):
    source = tmp_path / "nonfinite.json"
    source.write_text('{"unknown": {"nested": [1, ' + literal + ']}}', encoding="utf-8")
    with pytest.raises(ValueError, match="finite"):
        loader(source)


@pytest.mark.parametrize("loader", [Project.load, DimensionBank.load])
def test_json_duplicate_keys_cannot_silently_replace_data(tmp_path, loader):
    source = tmp_path / "duplicate.json"
    source.write_text('{"id": "one", "id": "two"}', encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate"):
        loader(source)


def test_finite_legacy_metadata_and_custom_ids_round_trip_without_precision_loss(tmp_path):
    project = engineering_project()
    exact = 0.000012345678912345
    project.features["feature"].metadata = {
        "engineering-note": "Custom legacy metadata", "optional": None,
        "checked": True, "measurements": [{"x": exact, "flags": [False, "raw"]}],
    }
    project.study = {"units_confirmed": True, "custom": {"nested": [exact, True]}}
    destination = tmp_path / "project.json"
    project.save(destination)
    assert Project.load(destination).to_dict() == project.to_dict()

    bank = DimensionBank()
    bank.add(DimensionTemplate("  Árbol  ", exact, 0.0, exact, None))
    bank.add(DimensionTemplate("Normal", 10.000012345678, 0.1, 0.2, 1.33123456789))
    destination = tmp_path / "bank.json"
    bank.save(destination)
    loaded = DimensionBank.load(destination)
    assert loaded.entries == bank.entries
    assert loaded.to_dimension("  Árbol  ").nominal == exact


@pytest.mark.parametrize("template_type", ["domain", "bank"])
def test_finite_inputs_with_overflowed_bounds_are_rejected(template_type):
    with pytest.raises(ValueError, match="bound.*finite"):
        if template_type == "domain":
            ToleranceDefinition("Size", "size", 1e308, 1e308, 0.0)
        else:
            DimensionTemplate("Size", 1e308, 1e308, 0.0)


@pytest.mark.parametrize("field,value", [
    ("nominal", float("inf")), ("tolerance_minus", -1),
    ("id", ""), ("distribution", {"kind": "normal"}),
])
def test_project_add_revalidates_mutable_entity_without_inserting_it(field, value):
    entity = ToleranceDefinition("Source", "size", 10, 0.1, 0.2)
    setattr(entity, field, value)
    project = Project("Add validation")
    with pytest.raises(ValueError):
        project.add_tolerance(entity)
    assert project.tolerances == {}


@pytest.mark.parametrize("field,value", [
    ("parts", {}), ("features", [None]), ("units", []), ("study", []),
    ("schema_version", 1.5), ("id", []),
])
def test_malformed_project_structure_is_rejected(field, value):
    payload = engineering_project().to_dict()
    payload[field] = value
    with pytest.raises(ValueError):
        Project.from_dict(payload)


def test_bank_key_and_template_name_must_agree(tmp_path):
    source = tmp_path / "bank.json"
    source.write_text(json.dumps({"Outer": {"name": "Inner", "nominal": 0,
                                           "tol_plus": 0, "tol_minus": 0}}), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match"):
        DimensionBank.load(source)


def test_cycles_in_mutated_metadata_are_rejected_with_a_validation_error():
    project = engineering_project()
    project.features["feature"].metadata["self"] = project.features["feature"].metadata
    with pytest.raises(ValueError, match="circular"):
        project.validate()
