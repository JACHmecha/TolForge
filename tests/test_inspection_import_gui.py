"""Reviewed import is atomic, cancelable and retains measurement ancestry."""
from copy import deepcopy
import hashlib
import json

import pytest

from tolstack.inspection import INSPECTION_FIELDS
from tolstack.inspection_import import read_aligned_csv
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


def csv_file(tmp_path, name="Hole 1", x="10.03", *, external_id=True):
    path = tmp_path / "aligned.csv"
    suffix = ",source_id" if external_id else ""
    data = (",".join(INSPECTION_FIELDS) + suffix + "\n" +
            f"{name},10,20,{x},20.04,10.1,10,10.2,0.2,RFS,hole" +
            (",CMM-17" if external_id else "") + "\n").encode("utf-8-sig")
    path.write_bytes(data)
    return path, data


def configure(dialog, *, units="mm", frame="A | B | C"):
    dialog.units_combo.setCurrentText(units)
    dialog.datum_frame_input.setText(frame)
    dialog.alignment_method_input.setText("CMM datum program 17")
    dialog.fitting_method_input.setText("Least squares fitted cylinder")
    index = dialog.source_id_combo.findData("source_id")
    if index >= 0:
        dialog.source_id_combo.setCurrentIndex(index)
    dialog.alignment_check.setChecked(True)


def reviewed_import(window, monkeypatch, path, *, units="mm", frame="A | B | C", before_accept=None):
    from PySide6.QtWidgets import QFileDialog
    from gui.inspection_import_dialog import ImportAlignedCsvDialog

    def accept_review(dialog):
        configure(dialog, units=units, frame=frame)
        if before_accept:
            before_accept(dialog)
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(path), ""))
    monkeypatch.setattr(ImportAlignedCsvDialog, "exec", accept_review)
    window._inspection_import_csv()


def test_preview_shows_mapping_but_requires_explicit_alignment_confirmation(window, tmp_path):
    from PySide6.QtWidgets import QDialog, QDialogButtonBox
    from gui.inspection_import_dialog import ImportAlignedCsvDialog

    path, _ = csv_file(tmp_path)
    dialog = ImportAlignedCsvDialog(read_aligned_csv(path), window)
    assert dialog.mapped_preview.rowCount() == 1
    assert dialog.mapping()["measured_x"] == {"column": "measured_x"}
    assert not dialog.buttons.button(QDialogButtonBox.Ok).isEnabled()
    dialog.accept()
    assert dialog.result() == QDialog.Rejected
    assert dialog.accepted_import() is None
    configure(dialog)
    assert dialog.buttons.button(QDialogButtonBox.Ok).isEnabled()
    dialog.accept()
    accepted = dialog.accepted_import()
    assert accepted["source_descriptor"]["external_alignment"]["confirmed"] is True
    accepted["row_metadata"][0]["id"] = "changed"
    assert dialog.accepted_import()["row_metadata"][0]["id"] != "changed"
    dialog.close()


def test_preview_validates_beyond_displayed_rows(window, tmp_path):
    from PySide6.QtWidgets import QDialogButtonBox
    from gui.inspection_import_dialog import ImportAlignedCsvDialog

    path, data = csv_file(tmp_path, external_id=False)
    header, measurement = data.decode("utf-8-sig").splitlines()
    lines = [measurement.replace("Hole 1", f"Hole {index}") for index in range(1, 26)]
    lines[-1] = lines[-1].replace("10.03", "nan")
    path.write_text(header + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
    dialog = ImportAlignedCsvDialog(read_aligned_csv(path), window)
    configure(dialog)
    assert dialog.mapped_preview.rowCount() == 20
    assert "Row 26 · measured_x" in dialog.errors_label.text()
    assert not dialog.buttons.button(QDialogButtonBox.Ok).isEnabled()
    dialog.close()


def test_cancel_preserves_domain_ui_reports_and_file_metadata(window, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog, QDialog
    from gui.inspection_import_dialog import ImportAlignedCsvDialog

    path, _ = csv_file(tmp_path)
    window._last_inspection_report = {"kept": "inspection"}
    window._last_gdt_report = {"kept": "CAD"}
    window._last_analysis_report = {"kept": "scalar"}
    before = deepcopy(window._project_raw_ui())
    domain = window.project.to_dict()
    clean = window._project_is_dirty()

    def cancel(dialog):
        configure(dialog, units="in")
        assert dialog.preview.valid
        dialog.reject()
        return QDialog.Rejected

    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(path), ""))
    monkeypatch.setattr(ImportAlignedCsvDialog, "exec", cancel)
    window._inspection_import_csv()
    assert window._project_raw_ui() == before
    assert window.project.to_dict() == domain
    assert window._project_is_dirty() == clean
    assert window._last_inspection_report == {"kept": "inspection"}
    assert window._last_gdt_report == {"kept": "CAD"}
    assert window._last_analysis_report == {"kept": "scalar"}
    assert not window._test_warnings


def test_accepted_mapping_captures_original_revision_and_ids_through_report_save_reload(window, monkeypatch, tmp_path):
    path, original = csv_file(tmp_path)
    reviewed_import(window, monkeypatch, path, units="in", before_accept=lambda dialog: path.write_bytes(
        original.replace(b"10.03", b"10.30")))
    assert not window._test_warnings
    assert window.inspection_units_combo.currentText() == "in"
    assert window._inspection_rows()[0]["measured_x"] == "10.03"
    metadata = window._inspection_row_metadata()
    assert metadata[0]["source_feature_id"] == "CMM-17"
    assert metadata[0]["fitting_method"] == "Least squares fitted cylinder"
    assert metadata[0]["import_sha256"] == hashlib.sha256(original).hexdigest()
    assert window._last_inspection_report is None
    window.inspection_drawing_input.setText("TF-001 Rev B")
    window.inspection_source_input.setText("CMM17, serial 001")
    window.inspection_scope_check.setChecked(True)
    window._evaluate_inspection()
    report = deepcopy(window._last_inspection_report)
    assert report["evidence"]["input_snapshot"]["context"]["study"]["metadata"]["measurement_row_metadata"] == metadata
    descriptor = next(item for item in report["evidence"]["input_snapshot"]["source_evidence"]
                      if item["kind"] == "inspection_csv")
    assert descriptor["mapping"]["measured_x"] == {"column": "measured_x"}
    assert descriptor["matches_recorded_hash"] is False
    saved_path = tmp_path / "imported.tolforge.json"
    assert window._project_save_to(str(saved_path))
    assert Project.load(saved_path).study["inspection"]["row_metadata"] == metadata
    window._project_open_from(str(saved_path))
    assert window._inspection_row_metadata() == metadata
    assert window._last_inspection_report is None
    window._evaluate_inspection()
    assert window._last_inspection_report["evidence"]["input_snapshot"]["context"]["study"]["metadata"]["measurement_row_metadata"] == metadata
    export = tmp_path / "report.json"
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(export), ""))
    window._export_inspection()
    assert json.loads(export.read_text())["evidence"]["input_snapshot"]["context"]["study"]["metadata"]["measurement_row_metadata"] == metadata


def test_manual_identity_and_imported_identity_remain_stable_after_name_edit(window, monkeypatch, tmp_path):
    path, _ = csv_file(tmp_path)
    reviewed_import(window, monkeypatch, path)
    identity = window._inspection_row_metadata()[0]["id"]
    window.inspection_table.item(0, 0).setText("Renamed hole")
    assert window._inspection_row_metadata()[0]["id"] == identity
    window._inspection_add_row()
    assert window._inspection_row_metadata()[1]["id"] != identity
    assert window._inspection_row_metadata()[1]["units"] == "mm"


def test_relabeling_units_cannot_admit_mixed_import_or_evaluate_existing_numbers(window, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QDialog
    from gui.inspection_import_dialog import ImportAlignedCsvDialog

    path, _ = csv_file(tmp_path)
    reviewed_import(window, monkeypatch, path)
    original = deepcopy(window._inspection_row_metadata())
    window.inspection_units_combo.setCurrentText("in")
    path, _ = csv_file(tmp_path, name="Hole 2")

    def reject_mixed(dialog):
        configure(dialog, units="in")
        assert not dialog.preview.valid
        assert "changing the label does not convert" in dialog.errors_label.text()
        return QDialog.Rejected

    monkeypatch.setattr(ImportAlignedCsvDialog, "exec", reject_mixed)
    window._inspection_import_csv()
    assert window.inspection_table.rowCount() == 1
    assert window._inspection_row_metadata() == original
    window._evaluate_inspection()
    assert window._last_inspection_report is None
    assert "changing the label does not convert" in window._test_warnings[-1][1]


def test_datum_relabeling_does_not_transform_imported_measurements(window, monkeypatch, tmp_path):
    path, _ = csv_file(tmp_path)
    reviewed_import(window, monkeypatch, path)
    window.inspection_datum_input.setText("A | B | D")
    window._evaluate_inspection()
    assert window._last_inspection_report is None
    assert "no coordinate transformation" in window._test_warnings[-1][1]


def test_invalid_batch_and_duplicate_names_do_not_append_any_rows(window, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QDialog
    from gui.inspection_import_dialog import ImportAlignedCsvDialog

    path, _ = csv_file(tmp_path)
    reviewed_import(window, monkeypatch, path)
    before = deepcopy(window._project_raw_ui())

    def reject_duplicate(dialog):
        configure(dialog)
        assert not dialog.preview.valid
        assert "duplicates" in dialog.errors_label.text()
        return QDialog.Rejected

    monkeypatch.setattr(ImportAlignedCsvDialog, "exec", reject_duplicate)
    window._inspection_import_csv()
    assert window._project_raw_ui() == before
    assert not window._test_warnings


def test_append_failure_rolls_back_rows_without_publishing_import_metadata(window, monkeypatch, tmp_path):
    path, data = csv_file(tmp_path, external_id=False)
    text = data.decode("utf-8-sig")
    path.write_text(text + text.splitlines()[1].replace("Hole 1", "Hole 2") + "\n", encoding="utf-8")
    window._last_inspection_report = {"previous": True}
    before = deepcopy(window._project_raw_ui())
    dirty = window._project_is_dirty()
    add_row = window._inspection_add_row
    attempts = []

    def fail_second(*args, **kwargs):
        attempts.append(kwargs["values"]["name"])
        if len(attempts) == 2:
            raise ValueError("Injected row append failure")
        return add_row(*args, **kwargs)

    monkeypatch.setattr(window, "_inspection_add_row", fail_second)
    reviewed_import(window, monkeypatch, path)
    assert attempts == ["Hole 1", "Hole 2"]
    assert window._project_raw_ui() == before
    assert window._project_is_dirty() == dirty
    assert window._last_inspection_report == {"previous": True}
    assert window._test_warnings[-1] == ("Could not import measurements", "Injected row append failure")


def test_metadata_edits_invalidate_all_context_reports_while_output_remains_read_only(window, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QTableWidgetItem

    path, _ = csv_file(tmp_path)
    reviewed_import(window, monkeypatch, path)
    window._last_inspection_report = {"old": True}
    window._last_gdt_report = {"old": True}
    window._last_analysis_report = {"old": True}
    window.inspection_table.setItem(0, len(INSPECTION_FIELDS), QTableWidgetItem("Displayed result"))
    assert window._last_inspection_report == {"old": True}
    assert window._last_gdt_report == {"old": True}
    assert window._last_analysis_report == {"old": True}
    metadata = window._inspection_row_metadata()[0]
    metadata["fitting_method"] = "Minimum circumscribed cylinder"
    window.inspection_table.item(0, 0).setData(window.INSPECTION_MEASUREMENT_ROLE, metadata)
    assert window._last_inspection_report is None
    assert window._last_gdt_report is None
    assert window._last_analysis_report is None


def test_malformed_or_reused_measurement_ids_fail_readiness_without_crashing(window, monkeypatch, tmp_path):
    path, _ = csv_file(tmp_path)
    reviewed_import(window, monkeypatch, path)
    window.inspection_table.item(0, 0).setData(window.INSPECTION_MEASUREMENT_ROLE, {"id": ""})
    window._evaluate_inspection()
    assert window._last_inspection_report is None
    assert "stable id" in window._test_warnings[-1][1]
    window.inspection_table.item(0, 0).setData(window.INSPECTION_MEASUREMENT_ROLE, {"id": "same", "units": "mm"})
    window._inspection_add_row(metadata={"id": "same", "units": "mm"})
    window._evaluate_inspection()
    assert "ids must be unique" in window._test_warnings[-1][1]
