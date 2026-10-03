"""Protect live editing across project transitions and recover incomplete work."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QThread, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QTableWidgetItem

from gui.app import TolstackWindow
from gui.gdt_mixin import PatternNumericItem, pattern_cell_value
from tolstack import drafts, persistence
from tolstack.domain import FeatureDefinition, PartDefinition, PartOccurrence
from tolstack.features import signature_from_points
from tolstack.project import Project


@pytest.fixture
def window(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(drafts, "draft_directory", lambda: tmp_path / "auto-drafts")
    monkeypatch.setattr(TolstackWindow, "_init_step_preview_renderer", lambda self: None)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[1:]))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Discard)
    instance = TolstackWindow()
    instance._project_change_timer.stop()
    instance._test_warnings = warnings
    yield instance
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Discard)
    thread = instance._step_load_thread
    if thread is not None and thread.isRunning():
        thread.quit()
        thread.wait(2000)
    instance.close()
    app.processEvents()


def _change(window):
    window.study_objective_input.setText("Pending drawing revision")
    assert window._project_is_dirty()


@pytest.mark.parametrize("target", ["new", "open", "previous", "close", "draft"])
def test_cancel_keeps_all_current_inputs_and_vetoes_transition(window, monkeypatch, tmp_path, target):
    project_path = tmp_path / "other.json"
    Project("Previous project").save(project_path)
    Project("Other project").save(project_path)
    draft_path = tmp_path / "other.recovery.json"
    drafts.save_draft(draft_path, window._project_draft_payload())
    _change(window)
    project_id = window.project.id
    raw_before = window._project_raw_ui()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Cancel)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(project_path), ""))

    if target == "new":
        assert window.new_project() is False
    elif target == "open":
        assert window.open_project() is False
    elif target == "previous":
        assert window.open_previous_project() is False
    elif target == "draft":
        assert window._project_open_draft_from(draft_path) is False
    else:
        event = QCloseEvent()
        window.closeEvent(event)
        assert not event.isAccepted()
        assert not window._project_closing
    assert window.project.id == project_id
    assert window._project_raw_ui() == raw_before
    assert window._project_is_dirty()


@pytest.mark.parametrize("failure", ["cancel_dialog", "invalid_input", "disk_error"])
@pytest.mark.parametrize("target", ["new", "open", "close"])
def test_save_choice_cannot_discard_work_when_save_fails(window, monkeypatch, tmp_path, failure, target):
    destination = tmp_path / "saved.json"
    other = tmp_path / "other.json"
    Project("Other project").save(other)
    _change(window)
    original_id = window.project.id
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Save)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: ("", "") if failure == "cancel_dialog" else (str(destination), ""))
    if failure == "invalid_input":
        window.table.item(0, 1).setText("unfinished")
    elif failure == "disk_error":
        monkeypatch.setattr(Project, "save", lambda *args: (_ for _ in ()).throw(OSError("disk locked")))
    if target == "new":
        assert window.new_project() is False
    elif target == "open":
        assert window._project_open_from(other) is False
    else:
        event = QCloseEvent()
        window.closeEvent(event)
        assert not event.isAccepted()
    assert window.project.id == original_id
    assert window.study_objective_input.text() == "Pending drawing revision"
    assert window._project_is_dirty()
    assert not destination.exists()


def test_successful_save_choice_commits_inputs_before_new_project(window, monkeypatch, tmp_path):
    destination = tmp_path / "saved.json"
    _change(window)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Save)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(destination), ""))
    assert window.new_project() is True
    assert Project.load(destination).study["objective"] == "Pending drawing revision"
    assert window.study_objective_input.text() == ""
    assert not window._project_is_dirty()


@pytest.mark.parametrize("invalid_target", ["project", "draft"])
def test_invalid_target_is_rejected_before_guard_or_workspace_change(window, monkeypatch, tmp_path, invalid_target):
    destination = tmp_path / "malformed.json"
    destination.write_text('{"unfinished":', encoding="utf-8")
    _change(window)
    before = window._project_raw_ui()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: pytest.fail("Invalid target must not ask to discard current work"))
    result = window._project_open_from(destination) if invalid_target == "project" else window._project_open_draft_from(destination)
    assert result is False
    assert window._project_raw_ui() == before
    assert window._test_warnings


def test_dirty_tracking_covers_metadata_rows_and_stable_ids_but_ignores_results(window):
    assert not window._project_is_dirty()
    window.table.item(0, 0).setData(window.TOLERANCE_ID_ROLE, "stable-tolerance")
    assert window._project_is_dirty()
    window._project_mark_clean()
    window._inspection_add_row(values={"name": "Hole"})
    assert window._project_is_dirty()
    window._drawing_control_add_row(values={"id": "control-id", "characteristic": "profile"})
    window._project_mark_clean()
    window.inspection_table.setItem(0, 11, QTableWidgetItem("Output result"))
    window.characteristic_table.setItem(0, 8, QTableWidgetItem("Output coverage"))
    window.table.item(0, 6).setText("3D preview only")
    window._last_analysis_report = object()
    assert not window._project_is_dirty()
    window.characteristic_table.item(0, 5).setText("unfinished callout")
    assert window._project_is_dirty()
    window._project_mark_clean()
    window._inspection_source_files.append({"kind": "inspection_csv", "path": "measurements.csv", "import_sha256": "a" * 64})
    assert window._project_is_dirty()
    window._project_mark_clean()
    window.project.name = "Changed domain header"
    assert window._project_is_dirty()


def _partial_editor_state(window):
    part = window.project.add_part(PartDefinition("Plate", source_file="missing.step", id="plate"))
    window.project.add_occurrence(PartOccurrence(part.id, "Plate:1", id="occurrence"))
    points = np.array([[0, 0, 0], [2, 0, 0], [0, 2, 0], [2, 2, 0]], dtype=float)
    feature = window.project.add_feature(FeatureDefinition(
        part.id, "Datum plane", "plane", id="plane", signature=signature_from_points("face", points).to_dict(),
    ))
    window._active_part_id, window._active_occurrence_id = part.id, "occurrence"
    window._datum_slot["Primary"] = {"point": np.array([1.0, 1.0, 0.0]), "direction": np.array([0.0, 0.0, 1.0]),
                                     "description": "Datum plane", "kind": "plane", "feature_id": feature.id}
    window.table.item(0, 1).setText("unfinished nominal")
    window.table.item(0, 0).setData(window.LINK_ROLE, {"feature_id": "unresolved-feature", "mode": "normal_offset"})
    window.table.item(0, 0).setData(window.TOLERANCE_ID_ROLE, "stable-tolerance")
    window.pattern_table.setRowCount(1)
    for column in range(9):
        window.pattern_table.setItem(0, column, QTableWidgetItem(""))
    window.pattern_table.item(0, 0).setText("Partial pattern")
    window.pattern_table.item(0, 0).setData(window.PATTERN_FEATURE_ID_ROLE, "unresolved-pattern")
    window.pattern_table.setItem(0, 3, PatternNumericItem(0.1234567890123456))
    window.pattern_table.item(0, 6).setText("nan")
    window._inspection_add_row(values={"name": "Hole", "actual_x": "unfinished measurement"})
    window._drawing_control_add_row(values={"id": "profile-control", "characteristic": "profile", "specification": "unfinished FCF"})
    window.seed_input.setText("unfinished seed")
    window._inspection_source_files = [{"kind": "inspection_csv", "path": "measurements.csv", "import_sha256": "a" * 64}]


def test_recovery_draft_preserves_incomplete_inputs_links_ids_precision_and_partial_datums(window, tmp_path):
    _partial_editor_state(window)
    payload = window._project_draft_payload()
    path = tmp_path / "partial.recovery.json"
    drafts.save_draft(path, payload)
    domain_before = Project.from_dict(payload["project_snapshot"]).to_dict()
    assert window._project_open_draft_from(path)
    assert window.project.to_dict() == domain_before
    assert window.table.item(0, 1).text() == "unfinished nominal"
    assert window.table.item(0, 0).data(window.TOLERANCE_ID_ROLE) == "stable-tolerance"
    assert window.table.item(0, 0).data(window.LINK_ROLE)["feature_id"] == "unresolved-feature"
    assert pattern_cell_value(window.pattern_table, 0, 3) == 0.1234567890123456
    assert window.pattern_table.item(0, 6).text() == "nan"
    assert window.seed_input.text() == "unfinished seed"
    assert window.characteristic_table.item(0, 0).text() == "profile-control"
    assert window.characteristic_table.item(0, 5).text() == "unfinished FCF"
    assert window._inspection_source_files == payload["ui"]["inspection_source_files"]
    assert window._datum_slot["Primary"]["feature_id"] == "plane"
    assert window._datum_slot["Secondary"] is None
    assert window._current_drf is None
    assert window._entity_by_feature_id == {}
    assert window._project_path is None
    assert window._last_inspection_report is None
    assert window._last_analysis_report is None
    assert window._last_gdt_report is None
    assert window._project_is_dirty()
    with pytest.raises(ValueError):
        window._project_build_pattern_control()
    assert window._project_save_to(str(tmp_path / "engineering.json")) is False
    assert not (tmp_path / "engineering.json").exists()


def test_draft_geometry_reattachment_does_not_replace_raw_partial_pattern_or_datum_edits(window, tmp_path):
    _partial_editor_state(window)
    path = tmp_path / "partial.recovery.json"
    drafts.save_draft(path, window._project_draft_payload())
    assert window._project_open_draft_from(path)
    window.pattern_table.item(0, 1).setText("edited after recovery")
    before = window._project_table_snapshot("pattern")
    window._project_capture_raw_geometry_before_load()
    window._datum_slot = dict.fromkeys(("Primary", "Secondary", "Tertiary"))
    points = np.array([[0, 0, 0], [2, 0, 0], [0, 2, 0], [2, 2, 0]], dtype=float)
    window._step_entity_info = {1: {"type": "face", "index": 0, "points": points}}
    window._project_on_step_loaded(str(tmp_path / "moved.step"))
    assert len(window.project.parts) == 1
    assert window._entity_by_feature_id["plane"]["feature_id"] == "plane"
    assert window._project_table_snapshot("pattern") == before
    assert window._datum_slot["Primary"]["feature_id"] == "plane"
    assert window._current_drf is None


def test_unresolved_recovered_datums_cannot_build_or_evaluate_a_stale_frame(window, tmp_path):
    _partial_editor_state(window)
    for slot, normal in (("Secondary", [0.0, 1.0, 0.0]), ("Tertiary", [1.0, 0.0, 0.0])):
        window._datum_slot[slot] = {"point": [0.0, 0.0, 0.0], "direction": normal,
                                   "description": f"Missing {slot}", "feature_id": f"missing-{slot}", "kind": "plane"}
    path = tmp_path / "unresolved.recovery.json"
    drafts.save_draft(path, window._project_draft_payload())
    assert window._project_open_draft_from(path)
    window.build_datum_frame()
    assert window._current_drf is None
    assert window._test_warnings
    # A leftover frame from another operation must not bypass matching.
    window._current_drf = SimpleNamespace(origin=np.zeros(3))
    with pytest.raises(ValueError, match="Reattach valid geometry for datum"):
        window._project_build_pattern_control()


def test_autosave_and_discard_cleanup_do_not_touch_manual_drafts(window, tmp_path):
    _change(window)
    window.table.item(0, 1).setText("unfinished")
    window._project_write_auto_draft()
    auto = window._project_auto_draft_path
    assert drafts.load_draft(auto)["ui"]["tables"]["stack"][0][1]["text"] == "unfinished"
    manual = tmp_path / "manual.recovery.json"
    drafts.save_draft(manual, window._project_draft_payload())
    assert window.new_project()
    assert not auto.exists()
    assert manual.exists()
    assert not window._project_is_dirty()


def test_successful_save_clears_autosave_and_marks_clean(window, tmp_path):
    _change(window)
    window._project_write_auto_draft()
    auto = window._project_auto_draft_path
    assert auto.exists()
    assert window._project_save_to(str(tmp_path / "engineering.json"))
    assert not auto.exists()
    assert not persistence.backup_path(auto).exists()
    assert not window._project_is_dirty()


def test_failed_autosave_keeps_prior_draft_and_does_not_clear_dirty_state(window, monkeypatch):
    _change(window)
    window._project_write_auto_draft()
    auto = window._project_auto_draft_path
    previous = auto.read_bytes()
    window.study_objective_input.setText("Later edit")
    original = persistence.os.replace
    def fail_destination(source, destination):
        if Path(destination) == auto:
            raise OSError("draft locked")
        return original(source, destination)
    monkeypatch.setattr(persistence.os, "replace", fail_destination)
    window._project_write_auto_draft()
    assert auto.read_bytes() == previous
    assert window._project_is_dirty()
    assert "draft locked" in window.statusBar().currentMessage()


def test_close_keeps_running_step_thread_owned_and_defers_without_destroying_window(window):
    class SlowReader(QThread):
        def run(self):
            self.msleep(180)
    thread = SlowReader(window)
    window._step_load_thread = thread
    thread.finished.connect(window._cleanup_step_load_thread)
    thread.start()
    window._measure_offset_timer.start(1000)
    window._stack_preview_timer.start(1000)
    window.show()
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted()
    assert window._project_closing
    assert window._step_load_thread is thread
    assert thread.isRunning()
    assert not window.isEnabled()
    assert not window._measure_offset_timer.isActive()
    assert not window._stack_preview_timer.isActive()
    before = window.study_objective_input.text()
    QTest.keyClicks(window.study_objective_input, "edit while closing")
    assert window.study_objective_input.text() == before
    assert thread.wait(1500)
    QApplication.processEvents()
    QTest.qWait(20)
    assert window._step_load_thread is None
    assert not window.isVisible()


def test_cancel_close_leaves_preview_and_draft_timers_active(window, monkeypatch):
    _change(window)
    window._measure_offset_timer.start(1000)
    window._stack_preview_timer.start(1000)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Cancel)
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted()
    assert window._measure_offset_timer.isActive()
    assert window._stack_preview_timer.isActive()
    assert window._project_draft_timer.isActive()


def test_startup_recovery_decline_is_nondestructive(window, monkeypatch):
    _change(window)
    window._project_write_auto_draft()
    path = window._project_auto_draft_path
    payload = path.read_bytes()
    original_id = window.project.id
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.No)
    window._project_offer_startup_recovery()
    assert path.read_bytes() == payload
    assert window.project.id == original_id


def test_save_then_reopen_same_project_loads_committed_values(window, monkeypatch, tmp_path):
    destination = tmp_path / "engineering.json"
    assert window._project_save_to(str(destination))
    window.study_objective_input.setText("Committed before reopen")
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Save)
    assert window._project_open_from(destination)
    assert window.study_objective_input.text() == "Committed before reopen"
    assert window.project.study["objective"] == "Committed before reopen"
    assert not window._project_is_dirty()


def test_draft_uses_last_valid_domain_snapshot_when_mutable_domain_is_incomplete(window, tmp_path):
    destination = tmp_path / "engineering.json"
    assert window._project_save_to(str(destination))
    previous = window.project.to_dict()
    tolerance = next(iter(window.project.tolerances.values()))
    tolerance.nominal = float("nan")
    window.table.item(0, 1).setText("unfinished edit")
    payload = window._project_draft_payload()
    assert payload["project_snapshot"] == previous
    assert payload["context"]["domain_validation_error"]
    assert payload["ui"]["tables"]["stack"][0][1]["text"] == "unfinished edit"
    draft_path = tmp_path / "incomplete.recovery.json"
    drafts.save_draft(draft_path, payload)
    assert Project.from_dict(drafts.load_draft(draft_path)["project_snapshot"]).to_dict() == previous


@pytest.mark.parametrize("mutate", [
    lambda data: data.update(kind="project"),
    lambda data: data.update(draft_schema_version=99),
    lambda data: data["project_snapshot"].update(name=""),
    lambda data: data["ui"]["tables"]["stack"].append([{"text": "incomplete structural row", "roles": {}}]),
    lambda data: data["ui"]["datums"].update(Primary={"point": [0, 0], "direction": [0, 0, 1], "kind": "plane", "description": "bad"}),
    lambda data: data["ui"]["widgets"].update(unknown_widget={"kind": "text", "text": "bad"}),
])
def test_corrupt_draft_never_clears_existing_work(window, tmp_path, mutate):
    payload = deepcopy(window._project_draft_payload())
    mutate(payload)
    destination = tmp_path / "corrupt.recovery.json"
    destination.write_text(json.dumps(payload), encoding="utf-8")
    _change(window)
    before = window._project_raw_ui()
    assert window._project_open_draft_from(destination) is False
    assert window._project_raw_ui() == before
    assert window._project_is_dirty()
