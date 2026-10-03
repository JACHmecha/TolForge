"""Recorded drawing coverage and evidence survive the Study GUI boundary."""

from copy import deepcopy
import hashlib
import json

import pytest

from tolstack.characteristics import CONTROL_FIELDS
from tolstack.inspection import INSPECTION_FIELDS
from tolstack.project import Project


@pytest.fixture
def window(monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from gui.app import TolstackWindow

    app = QApplication.instance() or QApplication([])
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, message: warnings.append((title, message)))
    instance = TolstackWindow()
    instance._test_warnings = warnings
    yield instance
    instance.close()
    app.processEvents()


def _measurements(window, **changes):
    window.inspection_drawing_input.setText("TF-001")
    window.inspection_source_input.setText("Part 001 / CMM 17")
    window.inspection_datum_input.setText("A | B | C")
    window.inspection_alignment_check.setChecked(True)
    window.inspection_scope_check.setChecked(True)
    values = dict(
        name="Hole 1", basic_x="10", basic_y="20", measured_x="10.03",
        measured_y="20.04", diameter="10.1", size_lower="10", size_upper="10.2",
        position_tolerance="0.2", modifier="RFS", feature_kind="hole",
    )
    values.update(changes)
    window._inspection_add_row(values=values)


def _control(window, control_id="position-1", balloon="1", **changes):
    values = dict(
        id=control_id, balloon=balloon, drawing="TF-001", revision="B",
        characteristic="position", specification="0.2", datum_references="A | B | C",
        feature_name="Hole 1",
    )
    values.update(changes)
    window._drawing_control_add_row(values=values)
    return values


def test_position_and_unsupported_profile_keep_coverage_incomplete(window):
    _measurements(window, diameter="10.3")  # Size fails, requested RFS position passes.
    _control(window)
    _control(window, "profile-2", "2", characteristic="profile", specification="surface profile 0.1")

    window._evaluate_inspection()

    assert not window._test_warnings
    report = window._last_inspection_report
    assert report["coverage"]["requested"] == 2
    assert report["coverage"]["evaluated"] == 1
    assert report["coverage"]["unsupported"] == 1
    assert report["coverage"]["complete"] is False
    assert report["coverage"]["passes_requested_controls"] is None
    assert report["passes_supported_checks"] is True
    assert "PASS" in window.characteristic_table.item(0, len(CONTROL_FIELDS)).text()
    assert "Unsupported" in window.characteristic_table.item(1, len(CONTROL_FIELDS)).text()
    assert "position PASS" in window.inspection_table.item(0, len(INSPECTION_FIELDS)).text()
    assert "1/2 requested controls evaluated" in window.inspection_result_label.text()
    assert report["evidence"]["input_snapshot"]["context"]["project"]["id"] == window.project.id


def test_each_control_uses_its_own_specification_on_one_measurement(window):
    _measurements(window)
    _control(window, "tight", "1", specification="0.08")
    _control(window, "loose", "2", specification="0.2")

    window._evaluate_inspection()

    report = window._last_inspection_report
    controls = {item["id"]: item for item in report["drawing_controls"]}
    assert controls["tight"]["passes"] is False
    assert controls["loose"]["passes"] is True
    assert report["coverage"]["passed"] == report["coverage"]["failed"] == 1
    assert report["coverage"]["passes_requested_controls"] is False
    text = window.inspection_table.item(0, len(INSPECTION_FIELDS)).text()
    assert "position FAIL (tight)" in text
    assert "position PASS (loose)" in text


def test_mismatched_datum_does_not_evaluate_a_requested_position(window):
    _measurements(window)
    _control(window, datum_references="A | B | D")

    window._evaluate_inspection()

    report = window._last_inspection_report
    assert report["coverage"]["evaluated"] == 0
    assert report["coverage"]["unevaluated"] == 1
    assert report["drawing_controls"][0]["passes"] is None
    assert "Unevaluated" in window.characteristic_table.item(0, len(CONTROL_FIELDS)).text()


def test_controls_roundtrip_without_persisting_dispositions(window, tmp_path):
    _measurements(window)
    expected = _control(window)
    _control(window, "profile", "2", characteristic="profile", specification="surface profile 0.1")
    window._evaluate_inspection()
    report_before = deepcopy(window._last_inspection_report)
    destination = tmp_path / "drawing.tolforge.json"

    window._project_save_to(str(destination))

    assert not window._test_warnings
    persisted = Project.load(destination)
    assert persisted.study["drawing_controls"][0] == expected
    assert all("status" not in control and "passes" not in control for control in persisted.study["drawing_controls"])
    window._project_open_from(str(destination))
    assert window._drawing_control_rows() == persisted.study["drawing_controls"]
    assert window._last_inspection_report is None
    assert window.characteristic_table.item(0, len(CONTROL_FIELDS)).text() == "Not evaluated"
    assert report_before["drawing_controls"][0]["status"] == "evaluated"


def test_control_edits_invalidate_export_and_leave_old_snapshot_identifiable(window, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    _measurements(window)
    _control(window)
    window._evaluate_inspection()
    old_report = deepcopy(window._last_inspection_report)
    destination = tmp_path / "first-report.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(destination), ""))
    window._export_inspection()
    old_bytes = destination.read_bytes()

    window.characteristic_table.item(0, CONTROL_FIELDS.index("specification")).setText("0.08")
    assert window._last_inspection_report is None
    window._export_inspection()
    assert window._test_warnings[-1][0] == "No current report"
    assert destination.read_bytes() == old_bytes
    window._evaluate_inspection()
    latest = window._last_inspection_report
    assert latest["evidence"]["input_snapshot_id"] != old_report["evidence"]["input_snapshot_id"]
    assert latest["evidence"]["input_digest"]["value"] != old_report["evidence"]["input_digest"]["value"]
    assert json.loads(old_bytes)["evidence"] == old_report["evidence"]


def test_invalid_control_cannot_replace_valid_project_but_stays_in_ui(window, tmp_path):
    _measurements(window)
    _control(window)
    destination = tmp_path / "valid.tolforge.json"
    window._project_save_to(str(destination))
    previous = destination.read_bytes()
    window.characteristic_table.item(0, CONTROL_FIELDS.index("specification")).setText("incomplete")

    window._project_save_to(str(destination))

    assert destination.read_bytes() == previous
    assert window._test_warnings[-1][0] == "Could not save project"
    assert window._drawing_control_rows()[0]["specification"] == "incomplete"
    assert window._last_inspection_report is None


def test_csv_import_hash_preserves_loaded_measurement_revision(window, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog
    from gui.inspection_import_dialog import ImportAlignedCsvDialog

    source = tmp_path / "measurements.csv"
    contents = (
        ",".join(INSPECTION_FIELDS) + "\n"
        "Hole 1,10,20,10.03,20.04,10.1,10,10.2,0.2,RFS,hole\n"
    ).encode("utf-8")
    source.write_bytes(contents)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(source), ""))
    def review(dialog):
        dialog.datum_frame_input.setText("A | B | C")
        dialog.alignment_method_input.setText("CMM 17")
        dialog.alignment_check.setChecked(True)
        dialog.accept()
        return dialog.result()
    monkeypatch.setattr(ImportAlignedCsvDialog, "exec", review)
    window._inspection_import_csv()
    _measurements(window, name="Hole 2")
    _control(window)
    source.write_bytes(contents.replace(b"10.03", b"10.30"))

    window._evaluate_inspection()

    report = window._last_inspection_report
    snapshot = report["evidence"]["input_snapshot"]
    descriptor = next(item for item in snapshot["source_evidence"] if item["kind"] == "inspection_csv")
    assert descriptor["import_sha256"] == hashlib.sha256(contents).hexdigest()
    assert descriptor["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert descriptor["matches_recorded_hash"] is False
    assert snapshot["inputs"]["measurement_rows"][0]["measured_x"] == "10.03"
    assert report["drawing_controls"][0]["passes"] is True
    destination = tmp_path / "csv-study.tolforge.json"
    assert window._project_save_to(str(destination))
    assert Project.load(destination).study["inspection"]["source_files"] == window._inspection_source_files


def test_drawing_context_edits_invalidate_scalar_and_cad_reports(window):
    _measurements(window)
    _control(window)
    window._add_table_row("Gap", 1, 0.1, 0.1, "+", None)
    window.run_analysis()
    assert window._last_analysis_report is not None
    first = window._last_analysis_report.to_dict()["evidence"]
    window._last_gdt_report = {"old": True}

    window.characteristic_table.item(0, CONTROL_FIELDS.index("revision")).setText("C")

    assert window._last_analysis_report is None
    assert window._last_gdt_report is None
    window.run_analysis()
    second = window._last_analysis_report.to_dict()["evidence"]
    assert second["input_snapshot_id"] != first["input_snapshot_id"]
    assert second["input_digest"]["value"] != first["input_digest"]["value"]
    assert first["input_snapshot"]["context"]["study"]["metadata"]["drawing_controls"][0]["revision"] == "B"
