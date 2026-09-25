"""Drawing-position inspection boundaries and the measured-part GUI workflow."""
import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

from tolstack import Project
from tolstack.inspection import INSPECTION_FIELDS, evaluate_inspection
from tolstack.workflow import study_readiness, validate_study


def _row(**changes):
    row = dict(
        name="Hole 1", basic_x="10", basic_y="20", measured_x="10.03",
        measured_y="20.04", diameter="10.1", size_lower="10", size_upper="10.2",
        position_tolerance="0.2", modifier="RFS", feature_kind="hole",
    )
    row.update(changes)
    return row


def _evaluate(rows=None, **changes):
    settings = dict(
        drawing="TF-001 Rev B, drawing-specified standard",
        measurement_source="Part 001 / CMM run 17", datum_frame="A | B | C at RFS",
        units="mm", alignment_confirmed=True, scope_confirmed=True,
    )
    settings.update(changes)
    return evaluate_inspection([_row()] if rows is None else rows, **settings)


@pytest.mark.parametrize(
    "kind,modifier,diameter,expected_bonus",
    [("hole", "RFS", "10.05", 0.0), ("pin", "RFS", "10.05", 0.0),
     ("hole", "MMC", "10.05", 0.05), ("pin", "MMC", "10.05", 0.15),
     ("hole", "LMC", "10.05", 0.15), ("pin", "LMC", "10.05", 0.05)],
)
def test_measured_position_uses_diametral_error_and_correct_material_boundary(
    kind, modifier, diameter, expected_bonus,
):
    report = _evaluate([_row(feature_kind=kind, modifier=modifier, diameter=diameter)])
    result = report["features"][0]["evaluation"]
    assert result["position_error"] == pytest.approx(0.1)
    assert result["bonus_tolerance"] == pytest.approx(expected_bonus)
    assert result["allowed_tolerance"] == pytest.approx(0.2 + expected_bonus)
    assert result["position_margin"] == pytest.approx(0.1 + expected_bonus)
    assert result["size_margin"] == pytest.approx(0.05)
    assert report["passes_supported_checks"] is True
    if modifier == "MMC":
        assert result["virtual_condition"] == pytest.approx(9.8 if kind == "hole" else 10.4)
    else:
        assert result["virtual_condition"] is None


@pytest.mark.parametrize("kind", ["hole", "pin"])
@pytest.mark.parametrize("modifier", ["RFS", "MMC", "LMC"])
@pytest.mark.parametrize("diameter", ["9.9", "10.3"])
def test_bonus_cannot_rescue_out_of_size_measured_feature(kind, modifier, diameter):
    report = _evaluate([_row(
        feature_kind=kind, modifier=modifier, diameter=diameter,
        measured_x="10", measured_y="20",
    )])
    result = report["features"][0]["evaluation"]
    assert result["position_conforming"] is True
    assert result["size_conforming"] is False
    assert result["size_margin"] == pytest.approx(-0.1)
    assert result["passes"] is False
    assert report["passes_supported_checks"] is False
    assert result["bonus_tolerance"] <= 0.2 + 1e-12


def test_one_position_failure_fails_supported_checks_without_changing_size_result():
    report = _evaluate([_row(), _row(name="Hole 2", measured_x="10.2", measured_y="20")])
    result = report["features"][1]["evaluation"]
    assert result["size_conforming"] is True
    assert result["position_conforming"] is False
    assert result["position_margin"] == pytest.approx(-0.2)
    assert report["passes_supported_checks"] is False
    assert report["features"][0]["evaluation"]["passes"] is True


@pytest.mark.parametrize("changes", [
    {"drawing": " "}, {"measurement_source": ""}, {"datum_frame": ""},
    {"alignment_confirmed": False}, {"scope_confirmed": False}, {"units": "cm"},
])
def test_inspection_requires_traceability_and_explicit_alignment_scope(changes):
    with pytest.raises(ValueError):
        _evaluate(**changes)


@pytest.mark.parametrize("changes", [
    {"name": " "}, {"measured_x": ""}, {"measured_y": "nan"},
    {"diameter": "inf"}, {"size_lower": "-1"}, {"size_upper": "9"},
    {"position_tolerance": "-0.1"}, {"modifier": "MMB"}, {"feature_kind": "slot"},
])
def test_inspection_rejects_incomplete_nonfinite_and_unsupported_inputs(changes):
    with pytest.raises(ValueError):
        _evaluate([_row(**changes)])


def test_inspection_rejects_empty_and_duplicate_feature_lists():
    with pytest.raises(ValueError, match="at least one"):
        _evaluate([])
    with pytest.raises(ValueError, match="unique"):
        _evaluate([_row(), _row(name=" Hole 1 ")])


def test_report_keeps_supplied_units_input_snapshot_and_engine_limitations():
    original = _row()
    report = _evaluate([original], units="in")
    original["diameter"] = "999"
    assert report["units"] == "in"
    assert report["features"][0]["input"]["diameter"] == 10.1
    assert "whole-drawing" in " ".join(report["limitations"])
    assert "datum fitting" in " ".join(report["limitations"])
    assert "uncertainty" in " ".join(report["limitations"])
    assert json.loads(json.dumps(report, allow_nan=False)) == report


@pytest.mark.parametrize("inspection", [
    "invalid", {"rows": "invalid"}, {"rows": ["invalid"]},
    {"drawing": 3}, {"units": "cm"}, {"alignment_confirmed": "false"},
    {"scope_confirmed": 1}, {"rows": [{"name": ["invalid"]}]},
])
def test_saved_inspection_rejects_structurally_invalid_drafts(inspection):
    with pytest.raises(ValueError):
        validate_study({"inspection": inspection})


def test_partial_inspection_draft_can_be_saved_before_it_is_evaluable(tmp_path):
    project = Project("Unfinished inspection")
    project.study = {"inspection": {"rows": [{"name": "Hole 1", "diameter": ""}]}}
    path = tmp_path / "draft.tolforge.json"
    project.save(path)
    assert Project.load(path).study == project.study


def test_readiness_identifies_missing_datum_frame_and_geometry_links():
    project = Project("Readiness")
    findings = study_readiness(project, datum_count=3, frame_ready=False, unresolved_count=2)
    errors = [finding.message for finding in findings if finding.severity == "error"]
    assert any("datum frame" in message for message in errors)
    assert any("2 missing" in message for message in errors)
    assert any("circular pattern" in message for message in errors)


@pytest.fixture
def window(monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from gui.app import TolstackWindow

    app = QApplication.instance() or QApplication([])
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[1:]))
    instance = TolstackWindow()
    instance._test_warnings = warnings
    yield instance
    instance.close()
    app.processEvents()


def _enter_inspection(window):
    window.inspection_drawing_input.setText("TF-001 Rev B")
    window.inspection_source_input.setText("Part 001 / CMM 17")
    window.inspection_datum_input.setText("A | B | C at RFS")
    window.inspection_alignment_check.setChecked(True)
    window.inspection_scope_check.setChecked(True)
    window._inspection_add_row(values=_row())


def test_study_workspace_measured_entry_and_stale_report_invalidation(window):
    window._show_workspace("study")
    assert window.sidebar.currentWidget() is window.study_tab
    _enter_inspection(window)
    window._evaluate_inspection()
    assert window._last_inspection_report["passes_supported_checks"] is True
    assert "PASS supported checks" in window.inspection_table.item(0, len(INSPECTION_FIELDS)).text()
    window.inspection_table.item(0, INSPECTION_FIELDS.index("measured_x")).setText("10.3")
    assert window._last_inspection_report is None
    assert window.inspection_table.item(0, len(INSPECTION_FIELDS)).text() == "Not evaluated"
    window._export_inspection()
    assert window._test_warnings[-1][0] == "No current report"
    window._evaluate_inspection()
    assert window._last_inspection_report["passes_supported_checks"] is False


def test_changing_traceability_or_alignment_requires_new_inspection_evaluation(window):
    _enter_inspection(window)
    for widget, new_value in [
        (window.inspection_drawing_input, "Rev C"),
        (window.inspection_source_input, "Part 002"),
        (window.inspection_datum_input, "Revised alignment"),
        (window.study_objective_input, "Mounting pattern"),
        (window.study_assumptions_input, "Parallel axes"),
    ]:
        window._evaluate_inspection()
        assert window._last_inspection_report is not None
        widget.setText(new_value)
        assert window._last_inspection_report is None
    window._evaluate_inspection()
    window.inspection_units_combo.setCurrentText("in")
    assert window._last_inspection_report is None
    window._evaluate_inspection()
    window.inspection_alignment_check.setChecked(False)
    assert window._last_inspection_report is None
    window._evaluate_inspection()
    assert window._last_inspection_report is None
    assert window._test_warnings[-1][0] == "Inspection is not ready"


def test_inspection_csv_import_is_atomic_on_invalid_row(window, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    _enter_inspection(window)
    path = tmp_path / "measurements.csv"
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=INSPECTION_FIELDS)
        writer.writeheader()
        writer.writerow(_row(name="Hole 2"))
        writer.writerow(_row(name="Hole 3", measured_x="nan"))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(path), "CSV (*.csv)"))
    window._inspection_import_csv()
    assert window.inspection_table.rowCount() == 1
    assert window._test_warnings[-1][0] == "Could not import measurements"


def test_project_save_open_restores_inspection_draft_but_requires_rerun(window, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    _enter_inspection(window)
    window.study_objective_input.setText("Mounting holes conform to drawing")
    window.study_assumptions_input.setText("Measurements externally aligned")
    window.seed_input.setText("42")
    window._evaluate_inspection()
    assert window._last_inspection_report is not None
    path = tmp_path / "inspection.tolforge.json"
    window._project_save_to(str(path))
    assert path.is_file(), window._test_warnings
    saved = Project.load(path)
    assert saved.study["inspection"]["rows"][0]["name"] == "Hole 1"
    window.new_project()
    assert window.inspection_table.rowCount() == 0
    assert window._last_inspection_report is None
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(path), "JSON (*.json)"))
    window.open_project()
    assert window.inspection_drawing_input.text() == "TF-001 Rev B"
    assert window.study_objective_input.text() == "Mounting holes conform to drawing"
    assert window.seed_input.text() == "42"
    assert window.inspection_alignment_check.isChecked()
    assert window.inspection_scope_check.isChecked()
    assert window._inspection_rows() == saved.study["inspection"]["rows"]
    assert window._last_inspection_report is None
    window._evaluate_inspection()
    assert window._last_inspection_report["passes_supported_checks"] is True
    assert not window._test_warnings
