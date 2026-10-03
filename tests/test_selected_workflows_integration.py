"""Measurement ancestry and loaded CAD evidence survive real project workflows."""

from copy import deepcopy
import hashlib
import json

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox, QTableWidgetItem

from gui.app import TolstackWindow
from gui.inspection_import_dialog import ImportAlignedCsvDialog
from tolstack import PartDefinition, drafts
from tolstack.inspection import INSPECTION_FIELDS


@pytest.fixture
def window(monkeypatch, tmp_path):
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(drafts, "draft_directory", lambda: tmp_path / "drafts")
    monkeypatch.setattr(TolstackWindow, "_init_step_preview_renderer", lambda self: None)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Discard)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[1:]))
    gui = TolstackWindow()
    gui._project_change_timer.stop()
    gui.warnings = warnings
    yield gui
    gui.close()
    application.processEvents()


def import_measurement(window, tmp_path, monkeypatch):
    source = tmp_path / "measurements.csv"
    contents = ("feature,id,bx,by,mx,my,diameter\n"
                "Hole 1,CMM-H01,10,20,10.03,20.04,10.1\n").encode()
    source.write_bytes(contents)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(source), ""))

    def review(dialog):
        columns = dict(name="feature", basic_x="bx", basic_y="by", measured_x="mx",
                       measured_y="my", diameter="diameter")
        constants = dict(size_lower="10", size_upper="10.2", position_tolerance="0.2",
                         modifier="RFS", feature_kind="hole")
        for field, (combo, constant) in dialog.mapping_inputs.items():
            combo.setCurrentIndex(combo.findData(columns.get(field)))
            if field in constants:
                constant.setText(constants[field])
        dialog.source_id_combo.setCurrentIndex(dialog.source_id_combo.findData("id"))
        dialog.datum_frame_input.setText("A | B | C")
        dialog.alignment_method_input.setText("CMM program AL-17")
        dialog.fitting_method_input.setText("Least squares circles")
        dialog.alignment_check.setChecked(True)
        dialog.accept()
        assert dialog.result() == QDialog.Accepted
        return dialog.result()

    monkeypatch.setattr(ImportAlignedCsvDialog, "exec", review)
    window._inspection_import_csv()
    assert window.inspection_table.rowCount() == 1
    assert not window.warnings
    return source, contents


def test_import_save_recovery_and_export_retain_original_measurement_and_loaded_cad_evidence(
        window, monkeypatch, tmp_path):
    csv_path, original_csv = import_measurement(window, tmp_path, monkeypatch)
    cad_path = tmp_path / "plate.step"
    cad_path.write_bytes(b"CAD used to create geometry")
    cad_digest = hashlib.sha256(cad_path.read_bytes()).hexdigest()
    part = window.project.add_part(PartDefinition("Plate", str(cad_path), cad_digest))
    window._active_part_id = part.id
    window._project_on_step_loaded(str(cad_path), source_sha256=cad_digest, source_hash_status="verified")
    window.inspection_drawing_input.setText("TF-17 Rev C")
    window.inspection_source_input.setText("Part 001 / CMM run 17")
    window.inspection_scope_check.setChecked(True)
    metadata = window._inspection_row_metadata()
    descriptors = deepcopy(window._inspection_source_files)
    assert metadata[0]["source_feature_id"] == "CMM-H01"
    assert metadata[0]["import_sha256"] == hashlib.sha256(original_csv).hexdigest()

    project_path = tmp_path / "study.json"
    assert window._project_save_to(str(project_path))
    saved = json.loads(project_path.read_text(encoding="utf-8"))
    assert saved["study"]["inspection"]["row_metadata"] == metadata
    assert saved["study"]["inspection"]["source_files"] == descriptors

    window._evaluate_inspection()
    report = deepcopy(window._last_inspection_report)
    assert report is not None
    snapshot = report["evidence"]["input_snapshot"]
    assert snapshot["context"]["study"]["metadata"]["measurement_row_metadata"] == metadata
    sources = {entry["kind"]: entry for entry in snapshot["source_evidence"]}
    assert sources["cad"]["loaded_geometry_revision_status"] == "matches_loaded_geometry"
    assert sources["inspection_csv"]["matches_recorded_hash"] is True
    csv_path.write_bytes(b"changed CSV after evaluation")
    cad_path.write_bytes(b"changed CAD after evaluation")
    report_path = tmp_path / "inspection-report.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(report_path), ""))
    window._export_inspection()
    assert json.loads(report_path.read_text(encoding="utf-8")) == report

    # Recovery preserves raw edits and row identities independently of the
    # last valid engineering save, without re-reading changed source files.
    window.inspection_table.item(0, 3).setText("unfinished measurement")
    recovery_path = tmp_path / "study.recovery.json"
    drafts.save_draft(recovery_path, window._project_draft_payload())
    assert window._project_open_draft_from(recovery_path)
    assert window._inspection_row_metadata() == metadata
    assert window.inspection_table.item(0, 3).text() == "unfinished measurement"
    assert window._last_inspection_report is None
    monkeypatch.setattr(window, "_start_step_load", lambda path: None)
    assert window._project_open_from(project_path)
    assert window._inspection_row_metadata() == metadata
    assert window._inspection_source_files == descriptors
    assert window.inspection_table.item(0, 3).text() == "10.03"
    assert window._last_inspection_report is None


def test_legacy_raw_draft_gains_stable_manual_measurement_id_without_import_ancestry(window, tmp_path):
    window._inspection_add_row(values={"name": "Manual hole", "measured_x": "unfinished"})
    payload = window._project_draft_payload()
    payload["ui"]["tables"]["inspection"][0][0].pop("roles", None)
    path = tmp_path / "legacy.recovery.json"
    drafts.save_draft(path, payload)
    assert window._project_open_draft_from(path)
    metadata = window._inspection_row_metadata()
    assert set(metadata[0]) == {"id", "units"}
    assert metadata[0]["id"] and metadata[0]["units"] == "mm"
    assert window.inspection_table.item(0, 3).text() == "unfinished"
    next_path = tmp_path / "next.recovery.json"
    drafts.save_draft(next_path, window._project_draft_payload())
    assert window._project_open_draft_from(next_path)
    assert window._inspection_row_metadata() == metadata


def test_measurement_ancestry_edits_invalidate_all_contexts_but_display_results_do_not(window):
    window._inspection_add_row(values={"name": "Manual hole"})
    reports = ({"marker": "inspection"}, {"marker": "CAD"}, {"marker": "stack"})
    window._last_inspection_report, window._last_gdt_report, window._last_analysis_report = reports
    window.inspection_table.setItem(0, len(INSPECTION_FIELDS), QTableWidgetItem("Display result"))
    assert (window._last_inspection_report, window._last_gdt_report, window._last_analysis_report) == reports
    metadata = window._inspection_row_metadata()[0]
    metadata["fitting_method"] = "Reviewed manual measurement"
    window.inspection_table.item(0, 0).setData(window.INSPECTION_MEASUREMENT_ROLE, metadata)
    assert window._last_inspection_report is None
    assert window._last_gdt_report is None
    assert window._last_analysis_report is None
