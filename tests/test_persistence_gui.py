"""Save and recovery failures preserve visible project and report state."""

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

from tolstack import persistence
from tolstack.bank import DimensionBank, DimensionTemplate
from tolstack.domain import Distribution, FeatureDefinition, PartDefinition, PartOccurrence, ToleranceDefinition
from tolstack.features import signature_from_points
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


def _deny_destination_replace(monkeypatch, destination):
    original = persistence.os.replace

    def denied_replace(source, output):
        if Path(output) == destination:
            raise OSError("Destination is locked")
        return original(source, output)

    monkeypatch.setattr(persistence.os, "replace", denied_replace)


@pytest.mark.parametrize("save_as", [False, True])
def test_failed_project_save_preserves_path_title_status_project_and_ui_edits(window, monkeypatch, tmp_path, save_as):
    source = tmp_path / "original.tolforge.json"
    window.project.name = "Original study"
    window.study_objective_input.setText("Original drawing")
    window._project_save_to(str(source))
    assert not window._test_warnings
    destination = tmp_path / "other.tolforge.json" if save_as else source
    if save_as:
        Project("Another saved study").save(destination)
    destination_before = destination.read_bytes()
    source_before = source.read_bytes()
    window.study_objective_input.setText("Pending drawing revision")
    window.seed_input.setText("123")
    snapshot = window.project.to_dict()
    title = window.windowTitle()
    status = window.step_status_label.text()
    _deny_destination_replace(monkeypatch, destination)

    window._project_save_to(str(destination))

    assert window._test_warnings == [("Could not save project", "Destination is locked")]
    assert window._project_path == str(source)
    assert window.windowTitle() == title
    assert window.step_status_label.text() == status
    assert window.project.to_dict() == snapshot
    assert window.study_objective_input.text() == "Pending drawing revision"
    assert window.seed_input.text() == "123"
    assert destination.read_bytes() == destination_before
    assert source.read_bytes() == source_before
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("failure", ["disk", "serialization"])
def test_report_export_failure_shows_error_and_preserves_existing_report(window, monkeypatch, tmp_path, failure):
    from PySide6.QtWidgets import QFileDialog

    destination = tmp_path / "inspection-report.json"
    saved = b'{"drawing": "original", "passes_supported_checks": true}'
    destination.write_bytes(saved)
    current = {"drawing": "new", "passes_supported_checks": False}
    if failure == "serialization":
        current["measurement"] = float("nan")
    else:
        _deny_destination_replace(monkeypatch, destination)
    window._last_inspection_report = current
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(destination), "JSON (*.json)"))

    window._export_inspection()

    assert len(window._test_warnings) == 1
    assert window._test_warnings[0][0] == "Could not export report"
    assert window._last_inspection_report is current
    assert destination.read_bytes() == saved
    assert not list(tmp_path.glob("*.tmp"))


def test_previous_project_opens_as_unsaved_without_altering_either_saved_version(window, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    destination = tmp_path / "drawing.tolforge.json"
    previous = Project("Earlier study", id="earlier")
    previous.study = {"objective": "Earlier drawing controls", "seed": "7"}
    previous.save(destination)
    Project("Latest study", id="latest").save(destination)
    recovery = persistence.backup_path(destination)
    disk_before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    window.study_objective_input.setText("Current unsaved drawing")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(destination), "JSON (*.json)"))

    window.open_previous_project()

    assert window.project.to_dict() == previous.to_dict()
    assert window._project_path is None
    assert "[Unsaved]" in window.windowTitle()
    assert window.study_objective_input.text() == "Earlier drawing controls"
    assert window.seed_input.text() == "7"
    assert "Recovered previous version" in window.step_status_label.text()
    assert not window._test_warnings
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == disk_before

    # Canceling the requested Save As must not overwrite the original study.
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: ("", ""))
    window.save_project()
    assert window._project_path is None
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == disk_before

    recovered_destination = tmp_path / "recovered.tolforge.json"
    window._project_save_to(str(recovered_destination))
    assert not window._test_warnings
    assert window._project_path == str(recovered_destination)
    assert Project.load(recovered_destination).name == "Earlier study"
    assert destination.read_bytes() == disk_before[destination.name]
    assert recovery.read_bytes() == disk_before[recovery.name]


@pytest.mark.parametrize("invalid_backup", ["malformed-json", "invalid-domain", "unsupported-workspace", "missing"])
def test_invalid_previous_project_is_rejected_before_clearing_current_workspace(window, monkeypatch, tmp_path, invalid_backup):
    from PySide6.QtWidgets import QFileDialog

    destination = tmp_path / "drawing.tolforge.json"
    Project("Saved study").save(destination)
    recovery = persistence.backup_path(destination)
    if invalid_backup == "malformed-json":
        recovery.write_text('{"unfinished":', encoding="utf-8")
    elif invalid_backup == "invalid-domain":
        payload = Project("Invalid project").to_dict()
        payload["name"] = ""
        recovery.write_text(json.dumps(payload), encoding="utf-8")
    elif invalid_backup == "unsupported-workspace":
        unsupported = Project("Unsupported study")
        unsupported.add_tolerance(ToleranceDefinition(
            "Gap", "size", 1, 0.1, 0.1, distribution=Distribution("triangular"),
        ))
        unsupported.save(recovery)
    window.project.name = "Current working project"
    window._project_path = str(tmp_path / "current-project.json")
    window._project_update_title()
    window.study_objective_input.setText("Pending study")
    snapshot = window.project.to_dict()
    title = window.windowTitle()
    status = window.step_status_label.text()
    path = window._project_path
    disk_before = {entry.name: entry.read_bytes() for entry in tmp_path.iterdir()}
    cleared = []
    monkeypatch.setattr(window, "clear_step_preview", lambda: cleared.append(True))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(destination), "JSON (*.json)"))

    window.open_previous_project()

    assert len(window._test_warnings) == 1
    assert window._test_warnings[0][0] == "Could not open project"
    assert cleared == []
    assert window.project.to_dict() == snapshot
    assert window._project_path == path
    assert window.windowTitle() == title
    assert window.step_status_label.text() == status
    assert window.study_objective_input.text() == "Pending study"
    assert {entry.name: entry.read_bytes() for entry in tmp_path.iterdir()} == disk_before


def test_bank_previous_version_can_be_loaded_without_replacing_saved_files(window, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    destination = tmp_path / "bank.json"
    previous = DimensionBank({"Spacer": DimensionTemplate("Spacer", 1.234567890123456, 0.1, 0.2)})
    previous.save(destination)
    DimensionBank({"New spacer": DimensionTemplate("New spacer", 2.0, 0.1, 0.2)}).save(destination)
    disk_before = {entry.name: entry.read_bytes() for entry in tmp_path.iterdir()}
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(persistence.backup_path(destination)), ""))

    window.load_bank_file()

    assert window.bank.entries == previous.entries
    assert window.bank_combo.currentText() == "Spacer"
    assert not window._test_warnings
    assert {entry.name: entry.read_bytes() for entry in tmp_path.iterdir()} == disk_before


def test_recovered_project_relinks_moved_step_without_changing_saved_entity_ids(window, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    destination = tmp_path / "drawing.tolforge.json"
    missing_source = tmp_path / "previous-location" / "plate.step"
    moved_source = tmp_path / "moved-plate.step"
    points = np.array([[0, 0, 0], [2, 0, 0], [0, 2, 0], [2, 2, 0]], dtype=float)
    previous = Project("Recovered plate", id="project-id")
    previous.add_part(PartDefinition("Plate", id="part-id", source_file=str(missing_source)))
    previous.add_occurrence(PartOccurrence("part-id", "Plate:1", id="occurrence-id"))
    previous.add_feature(FeatureDefinition(
        "part-id", "Mounting plane", "plane", id="feature-id",
        signature=signature_from_points("face", points).to_dict(),
    ))
    previous.save(destination)
    Project("Latest revision").save(destination)
    disk_before = {entry.name: entry.read_bytes() for entry in tmp_path.iterdir()}
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(destination), "JSON (*.json)"))

    window.open_previous_project()
    assert window._project_path is None
    assert window._project_recovered_from == str(destination)
    # Supply the STEP loader's completed geometry payload without requiring
    # the optional native backend. Topology indices can change after reload.
    moved_feature = {"type": "face", "index": 99, "points": points.copy()}
    window._step_entity_info = {123: moved_feature}
    window._project_on_step_loaded(str(moved_source))

    assert set(window.project.parts) == {"part-id"}
    assert set(window.project.occurrences) == {"occurrence-id"}
    assert set(window.project.features) == {"feature-id"}
    assert window._active_part_id == "part-id"
    assert window._active_occurrence_id == "occurrence-id"
    assert window.project.parts["part-id"].source_file == str(moved_source.resolve())
    assert moved_feature["feature_id"] == "feature-id"
    assert window._project_find_entity_info("feature-id") is moved_feature
    assert window._project_path is None
    assert {entry.name: entry.read_bytes() for entry in tmp_path.iterdir()} == disk_before

    recovered_destination = tmp_path / "recovered.tolforge.json"
    window._project_save_to(str(recovered_destination))
    assert not window._test_warnings
    assert window._project_path == str(recovered_destination)
    assert window._project_recovered_from is None
    saved = Project.load(recovered_destination)
    from tolstack.relinking import resolve_source_path
    assert saved.parts["part-id"].source_file == moved_source.name
    assert resolve_source_path(saved.parts["part-id"].source_file, recovered_destination) == moved_source.resolve()
    assert set(saved.features) == {"feature-id"}
    assert destination.read_bytes() == disk_before[destination.name]
    recovery = persistence.backup_path(destination)
    assert recovery.read_bytes() == disk_before[recovery.name]

    window.open_previous_project()
    assert window._project_recovered_from == str(destination)
    window.new_project()
    assert window._project_recovered_from is None
    assert window._project_path is None
    assert window.project.parts == {}
    window._project_on_step_loaded(str(tmp_path / "first.step"))
    first_part = window.project.parts[window._active_part_id]
    window._project_on_step_loaded(str(tmp_path / "second.step"))
    assert len(window.project.parts) == 2
    assert first_part.source_file == str((tmp_path / "first.step").resolve())
    assert window._active_part_id != first_part.id


def test_retry_after_failed_save_preserves_deletion_of_saved_position_pattern(window, monkeypatch, tmp_path):
    destination = tmp_path / "pattern.tolforge.json"
    window.project.add_part(PartDefinition("Plate", id="plate"))
    window.project.add_occurrence(PartOccurrence("plate", "Plate:1", id="plate-occurrence"))
    window._active_part_id = "plate"
    window._active_occurrence_id = "plate-occurrence"
    for slot, feature_id, direction in (
        ("Primary", "face-a", [0.0, 0.0, 1.0]),
        ("Secondary", "face-b", [1.0, 0.0, 0.0]),
        ("Tertiary", "face-c", [0.0, 1.0, 0.0]),
    ):
        window.project.add_feature(FeatureDefinition("plate", feature_id, "plane", id=feature_id))
        window._datum_slot[slot] = {
            "feature_id": feature_id, "point": np.zeros(3),
            "direction": np.array(direction), "kind": "plane", "description": feature_id,
        }
    window.project.add_feature(FeatureDefinition("plate", "Hole", "circle", id="hole"))
    window._entity_by_feature_id["hole"] = {
        "type": "edge", "index": 4,
        "circle": {"center": np.array([1.0, 2.0, 0.0]), "normal": np.array([0.0, 0.0, 1.0]), "radius": 5.0},
    }
    window._pattern_add_row("Hole", 1.0, 2.0, 1.0, 2.0, 10.0, feature_id="hole")
    window._project_save_to(str(destination))
    assert not window._test_warnings
    datum_system_id = window._active_datum_system_id
    control_id = window._active_position_control_id
    snapshot = window.project.to_dict()
    saved_before = destination.read_bytes()
    assert control_id in Project.load(destination).position_controls
    member = window.project.position_controls[control_id].members[0]
    pattern_tolerance_ids = {member.size_tolerance_id, member.position_x_tolerance_id, member.position_y_tolerance_id}

    window.pattern_table.setRowCount(0)
    with monkeypatch.context() as disk_failure:
        _deny_destination_replace(disk_failure, destination)
        window._project_save_to(str(destination))

    assert window._test_warnings == [("Could not save project", "Destination is locked")]
    assert window.project.to_dict() == snapshot
    assert window._active_datum_system_id == datum_system_id
    assert window._active_position_control_id == control_id
    assert window.pattern_table.rowCount() == 0
    assert destination.read_bytes() == saved_before

    window._test_warnings.clear()
    window._project_save_to(str(destination))

    assert not window._test_warnings
    assert window._active_position_control_id is None
    assert window._active_datum_system_id == datum_system_id
    assert window.project.position_controls == {}
    saved = Project.load(destination)
    assert saved.position_controls == {}
    assert pattern_tolerance_ids.isdisjoint(saved.tolerances)
    assert persistence.backup_path(destination).read_bytes() == saved_before
