"""Requested drawing controls govern dispositions and explicit coverage gaps."""

from copy import deepcopy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

from tolstack.characteristics import CONTROL_FIELDS, validate_drawing_controls
from tolstack.inspection import evaluate_inspection
from tolstack.project import Project
from tolstack.workflow import validate_study


def _control(**changes):
    control = dict(
        id="position-1", balloon="1", drawing="TF-001", revision="B",
        characteristic="position", specification="0.2",
        datum_references="A | B | C", feature_name="Hole 1",
    )
    control.update(changes)
    return control


def _row(**changes):
    row = dict(
        name="Hole 1", basic_x="10", basic_y="20", measured_x="10.03", measured_y="20.04",
        diameter="10.1", size_lower="10", size_upper="10.2", position_tolerance="0.2",
        modifier="RFS", feature_kind="hole",
    )
    row.update(changes)
    return row


def _evaluate(controls, rows=None, **changes):
    settings = dict(
        drawing="TF-001 Rev B", measurement_source="Part 001 / CMM 17",
        datum_frame="A | B | C", units="mm", alignment_confirmed=True, scope_confirmed=True,
        drawing_controls=controls,
    )
    settings.update(changes)
    return evaluate_inspection([_row()] if rows is None else rows, **settings)


def test_position_and_unsupported_profile_report_both_without_whole_request_pass():
    controls = [_control(), _control(
        id="profile-2", balloon="2", characteristic="surface profile",
        specification="0.1 all around", feature_name="Unmeasured outer surface",
    )]
    report = _evaluate(controls)

    position, profile = report["drawing_controls"]
    assert position["status"] == "evaluated"
    assert position["supported"] is True
    assert position["passes"] is True
    assert position["evidence"]["evaluation"]["position_error"] == pytest.approx(0.1)
    assert profile["status"] == "unsupported"
    assert profile["supported"] is False
    assert profile["passes"] is None
    assert profile["evidence"] is None
    assert report["coverage"] == dict(
        requested=2, evaluated=1, unevaluated=0, unsupported=1,
        passed=1, failed=0, complete=False, passes_requested_controls=None, inventory_declared=True,
    )
    assert report["passes_supported_checks"] is True
    assert len(report["features"]) == 1


def test_each_requested_control_uses_its_own_drawing_limits_on_the_same_feature():
    controls = [
        _control(id="tight-position", balloon="1", specification="0.05"),
        _control(id="loose-position", balloon="2", specification="0.2"),
        _control(id="size-control", balloon="3", characteristic="size", specification="10:10.2"),
    ]
    report = _evaluate(controls, [_row(position_tolerance="9", size_lower="9", size_upper="9.1")])

    tight, loose, size = report["drawing_controls"]
    assert tight["passes"] is False
    assert loose["passes"] is True
    assert size["passes"] is True
    assert tight["effective_specification"] == {"position_tolerance": 0.05}
    assert loose["effective_specification"] == {"position_tolerance": 0.2}
    assert size["effective_specification"] == {"size_lower": 10.0, "size_upper": 10.2}
    assert [row["control_id"] for row in report["features"]] == [control["id"] for control in controls]
    assert [row["requested_control_passes"] for row in report["features"]] == [False, True, True]
    assert tight["evidence"]["evaluation"]["position_margin"] == pytest.approx(-0.05)
    assert report["coverage"]["complete"] is True
    assert report["coverage"]["passes_requested_controls"] is False
    assert report["coverage"]["passed"] == 2
    assert report["coverage"]["failed"] == 1


@pytest.mark.parametrize("characteristic,specification,row_changes,requested_passes,unrequested_field", [
    ("position", "0.2", {"diameter": "9.9"}, True, "size_conforming"),
    ("size", "10:10.2", {"measured_x": "12"}, True, "position_conforming"),
])
def test_unrequested_check_cannot_fail_requested_drawing_coverage(
    characteristic, specification, row_changes, requested_passes, unrequested_field,
):
    report = _evaluate([_control(characteristic=characteristic, specification=specification)], [_row(**row_changes)])
    result = report["features"][0]

    assert result["evaluation"][unrequested_field] is False
    assert result["evaluation"]["passes"] is False
    assert result["requested_control_passes"] is requested_passes
    assert report["passes_supported_checks"] is True
    assert report["coverage"]["passes_requested_controls"] is True


def test_only_linked_supported_measurement_rows_are_evaluated():
    unrelated = _row(name="Unrequested unfinished feature", diameter="invalid", measured_x="nan")
    report = _evaluate([_control()], [_row(), unrelated])

    assert len(report["features"]) == 1
    assert report["coverage"]["evaluated"] == 1
    assert report["coverage"]["passes_requested_controls"] is True


def test_invalid_linked_measurement_fails_with_control_identity():
    with pytest.raises(ValueError, match="Drawing control 1 \\(position-1\\)"):
        _evaluate([_control()], [_row(measured_x="nan")])


def test_ambiguous_measurement_names_cannot_silently_select_one_row():
    with pytest.raises(ValueError, match="unique"):
        _evaluate([_control()], [_row(), _row(name=" Hole 1 ", measured_x="99")])


def test_missing_and_unlinked_measurements_remain_unevaluated():
    report = _evaluate([
        _control(), _control(id="unlinked", balloon="2", feature_name=""),
    ], [], drawing="", measurement_source="", datum_frame="", alignment_confirmed=False, scope_confirmed=False)

    assert report["features"] == []
    assert report["passes_supported_checks"] is None
    assert all(control["status"] == "unevaluated" and control["passes"] is None for control in report["drawing_controls"])
    assert report["coverage"]["unevaluated"] == 2
    assert report["coverage"]["complete"] is False
    assert report["coverage"]["passes_requested_controls"] is None
    assert report["alignment_confirmed"] is False


def test_unsupported_control_does_not_invoke_a_numeric_solver():
    report = _evaluate([_control(characteristic="flatness", specification="Drawing note 4")], [_row(diameter="invalid")])
    assert report["features"] == []
    assert report["drawing_controls"][0]["status"] == "unsupported"
    assert report["coverage"]["unsupported"] == 1
    assert report["coverage"]["complete"] is False


def test_explicit_mismatched_datum_references_are_unevaluated():
    report = _evaluate([_control(datum_references="A | D | C")], [_row(measured_x="invalid")])

    control = report["drawing_controls"][0]
    assert control["status"] == "unevaluated"
    assert control["supported"] is True
    assert control["passes"] is None
    assert "alignment is unverified" in control["reason"]
    assert report["features"] == []


def test_frame_whitespace_and_case_preserve_the_recorded_alignment():
    control_frame = " a| b | c "
    report = _evaluate([_control(datum_references=control_frame)])
    assert report["drawing_controls"][0]["status"] == "evaluated"
    assert report["drawing_controls"][0]["effective_datum_frame"] == control_frame.strip()


@pytest.mark.parametrize("rows", [None, []])
def test_position_control_without_drawing_datum_references_remains_unevaluated(rows):
    report = _evaluate([_control(datum_references="")], rows)
    control = report["drawing_controls"][0]
    assert control["status"] == "unevaluated"
    assert control["effective_datum_frame"] is None
    assert control["passes"] is None
    assert "datum references are missing" in control["reason"]
    assert report["features"] == []
    assert report["coverage"]["complete"] is False


def test_size_control_may_omit_drawing_datum_references():
    report = _evaluate([_control(characteristic="size", specification="10:10.2", datum_references="")])
    assert report["drawing_controls"][0]["status"] == "evaluated"
    assert report["drawing_controls"][0]["effective_datum_frame"] == "A | B | C"


@pytest.mark.parametrize("setting", ["alignment_confirmed", "scope_confirmed"])
def test_referenced_supported_check_still_requires_confirmed_engine_scope(setting):
    with pytest.raises(ValueError, match="Confirm"):
        _evaluate([_control()], **{setting: False})


@pytest.mark.parametrize("controls", [None, []])
def test_legacy_inspection_keeps_combined_feature_result_and_has_no_inventory_claim(controls):
    report = _evaluate(controls, [_row(diameter="9.9")])
    assert report["report_version"] == 1
    assert report["features"][0]["evaluation"]["passes"] is False
    assert report["passes_supported_checks"] is False
    assert report["drawing_controls"] == []
    assert report["coverage"]["requested"] == 0
    assert report["coverage"]["inventory_declared"] is False
    assert report["coverage"]["complete"] is False
    assert report["coverage"]["passes_requested_controls"] is None


@pytest.mark.parametrize("characteristic,specification", [
    ("position", "-0.1"), ("position", "nan"), ("position", "inf"), ("position", "1e400"),
    ("position", "Ø0.2"), ("size", "10"), ("size", "10:9"), ("size", "0:10"),
    ("size", "10:inf"), ("size", "10:10.2:10.3"), ("size", "limits from note"),
])
def test_invalid_supported_specifications_are_rejected_even_before_measurement(characteristic, specification):
    with pytest.raises(ValueError, match="specification"):
        validate_drawing_controls([_control(characteristic=characteristic, specification=specification, feature_name="")])


@pytest.mark.parametrize("field", CONTROL_FIELDS[:6])
def test_partial_control_definitions_are_drafts_not_valid_engineering_requests(field):
    with pytest.raises(ValueError, match="draft recovery"):
        validate_study({"drawing_controls": [_control(**{field: ""})]})


def test_ids_and_balloon_scope_are_unique_without_restricting_other_revisions():
    with pytest.raises(ValueError, match="ID.*unique"):
        validate_drawing_controls([_control(), _control(balloon="2")])
    with pytest.raises(ValueError, match="Balloon.*unique"):
        validate_drawing_controls([_control(), _control(id="another", drawing=" tf-001 ", revision=" b ")])
    controls = validate_drawing_controls([
        _control(), _control(id="another-revision", revision="C"),
        _control(id="another-drawing", drawing="TF-002"),
    ])
    assert len(controls) == 3


def test_project_inventory_round_trip_preserves_ids_and_unsupported_specification(tmp_path):
    project = Project("Drawing inventory")
    controls = [_control(), _control(id="profile", balloon="2", characteristic="profile", specification="Note 7, all around")]
    project.study = {"drawing_controls": controls, "custom": {"owner_note": "Reviewed request list"}}
    destination = tmp_path / "inventory.tolforge.json"
    project.save(destination)
    loaded = Project.load(destination)
    assert loaded.study == project.study
    assert loaded.study["drawing_controls"][1]["specification"] == "Note 7, all around"


def test_report_is_a_detached_snapshot_and_inventory_changes_create_new_input_identity():
    controls = [_control()]
    rows = [_row()]
    original = deepcopy(controls)
    report = _evaluate(controls, rows)
    serialized = json.dumps(report, allow_nan=False, sort_keys=True)
    assert controls == original
    rows[0]["diameter"] = "10.15"
    controls[0]["specification"] = "0.05"
    changed = _evaluate(controls, rows)

    assert json.dumps(report, allow_nan=False, sort_keys=True) == serialized
    assert report["drawing_controls"][0]["specification"] == "0.2"
    assert report["drawing_controls"][0]["evidence"]["input"]["diameter"] == 10.1
    assert changed["coverage"]["failed"] == 1
    assert changed["evidence"]["input_digest"]["value"] != report["evidence"]["input_digest"]["value"]


def test_evidence_preserves_unused_measurements_and_unsupported_control_definitions():
    controls = [_control(), _control(
        id="profile-control", balloon="2", characteristic="profile", specification="Note 4 all around",
        feature_name="Outer surface", datum_references="A | D",
    )]
    rows = [_row(), _row(name="Unused draft", diameter="incomplete", measured_x="")]
    original_rows = deepcopy(rows)
    original_controls = deepcopy(controls)
    report = _evaluate(controls, iter(rows))
    snapshot = report["evidence"]["input_snapshot"]["inputs"]

    assert snapshot["measurement_rows"] == original_rows
    assert snapshot["submitted_drawing_controls"] == original_controls
    assert len(snapshot["evaluated_inputs"]) == 1
    rows[1]["diameter"] = "99"
    controls[1]["specification"] = "Changed drawing note"
    assert snapshot["measurement_rows"] == original_rows
    assert snapshot["submitted_drawing_controls"] == original_controls


def test_plain_drawing_and_measurement_references_have_explicit_unavailable_hashes():
    report = _evaluate([_control()])
    sources = report["evidence"]["input_snapshot"]["source_evidence"]
    assert {source["kind"] for source in sources} == {"drawing", "measurement"}
    assert all(source["sha256"] is None and source["hash_status"] == "unavailable" for source in sources)
    assert all(source["unavailable_reason"] == "no_file_path_supplied" for source in sources)


def test_report_context_retains_project_ids_and_evaluation_time_source_hash_without_mutating_caller(tmp_path):
    import hashlib

    source = tmp_path / "measurements.csv"
    source.write_bytes(b"measured data at evaluation")
    context = {
        "project": {"id": "project-id"}, "study": {"id": "study-id"},
        "sources": [{"kind": "inspection_csv", "path": str(source)}],
    }
    before = deepcopy(context)
    report = _evaluate([_control()], report_context=context)
    snapshot = report["evidence"]["input_snapshot"]
    assert context == before
    assert snapshot["context"]["project"]["id"] == "project-id"
    assert snapshot["context"]["study"]["id"] == "study-id"
    csv_evidence = next(item for item in snapshot["source_evidence"] if item["kind"] == "inspection_csv")
    assert csv_evidence["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    serialized = json.dumps(report, sort_keys=True)
    source.write_bytes(b"file changed after evaluation")
    assert json.dumps(report, sort_keys=True) == serialized
    newer = _evaluate([_control()], report_context=context)
    assert newer["evidence"]["input_digest"]["value"] != report["evidence"]["input_digest"]["value"]


@pytest.mark.parametrize("declared_inventory", [False, True])
def test_inspection_captures_inputs_context_and_source_before_solver_runs(tmp_path, monkeypatch, declared_inventory):
    import hashlib
    from tolstack import inspection

    source = tmp_path / "measurements.csv"
    source.write_bytes(b"source at evaluation start")
    context = {"project": {"id": "original-project"}, "sources": [{"kind": "inspection_csv", "path": str(source)}]}
    rows = [_row()]
    controls = [_control()] if declared_inventory else None
    original_solver = inspection.evaluate_position

    def run_with_external_changes(*args, **kwargs):
        source.write_bytes(b"source changed while calculating")
        context["project"]["id"] = "changed-project"
        rows[0]["diameter"] = "999"
        if controls:
            controls[0]["specification"] = "99"
        return original_solver(*args, **kwargs)

    monkeypatch.setattr(inspection, "evaluate_position", run_with_external_changes)
    report = _evaluate(controls, rows, report_context=context)
    snapshot = report["evidence"]["input_snapshot"]
    csv_source = next(item for item in snapshot["source_evidence"] if item["kind"] == "inspection_csv")
    assert csv_source["sha256"] == hashlib.sha256(b"source at evaluation start").hexdigest()
    assert snapshot["context"]["project"]["id"] == "original-project"
    assert snapshot["inputs"]["measurement_rows"][0]["diameter"] == "10.1"
    assert report["features"][0]["input"]["diameter"] == 10.1
    assert report["evidence"]["report_kind_version"] == (2 if declared_inventory else 1)
    if declared_inventory:
        assert snapshot["inputs"]["submitted_drawing_controls"][0]["specification"] == "0.2"


@pytest.mark.parametrize("source_files", [
    "invalid", ["invalid"], [{"kind": "inspection_csv"}], [{"kind": 1, "path": "measurements.csv"}],
    [{"kind": "inspection_csv", "path": ""}],
    [{"kind": "inspection_csv", "path": "measurements.csv", "import_sha256": "invalid"}],
])
def test_invalid_source_descriptors_are_rejected_at_study_boundary(source_files):
    with pytest.raises(ValueError, match="Inspection source"):
        validate_study({"inspection": {"source_files": source_files}})


def test_source_descriptors_and_unknown_finite_metadata_round_trip_without_rewriting(tmp_path):
    project = Project("Imported inspection evidence")
    project.study = {"inspection": {"source_files": [{
        "kind": "inspection_csv", "path": "measurements.csv", "import_sha256": "a" * 64,
        "custom": {"fixture": "B", "temperature": 20.1},
    }], "unknown": {"datum_fit_residual": 0.001}}}
    destination = tmp_path / "inspection.tolforge.json"
    project.save(destination)
    assert Project.load(destination).study == project.study
