"""Engineering saves and raw recovery retain Projected interference studies."""

from copy import deepcopy
import json

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from gui.app import TolstackWindow
from tolstack import drafts
from tolstack.project import Project
from tolstack.projected_geometry import projection_from_circles


def _settings():
    return {
        "mode": "hole-pin", "units": "in", "seed": 451, "iterations": 300,
        "threshold": 8.5,
        "inputs": {
            "handle": {"nominal": 1.0, "tol_plus": .01, "tol_minus": .02, "cpk": 1.33},
            "sticker": {"nominal": .8, "tol_plus": .02, "tol_minus": .01, "cpk": None},
            "offset_x": {"nominal": -.03, "tol_plus": .01, "tol_minus": .005, "cpk": None},
            "offset_y": {"nominal": .02, "tol_plus": .015, "tol_minus": .005, "cpk": .9},
        },
        "projection": {"reference_axis": "Y", "source_units": "mm", "frame": None},
    }


@pytest.mark.parametrize("mode", ["hole-hole", "hole-pin"])
def test_optional_block_roundtrip_preserves_legacy_schema_and_other_studies(tmp_path, mode):
    settings = _settings()
    settings["mode"] = mode
    project = Project("Saved interference", study={"projected_interference": settings, "custom": {"owner": "test"}})
    destination = tmp_path / "study.tolforge.json"
    project.save(destination)
    restored = Project.load(destination)
    assert restored.schema_version == 1
    assert restored.study == project.study
    assert "samples" not in restored.study["projected_interference"]
    assert Project.from_dict(Project("Legacy").to_dict()).study == {}


@pytest.mark.parametrize("mutate", [
    lambda value: value.update(mode="pin-pin"),
    lambda value: value.update(units="cm"),
    lambda value: value.update(seed=-1),
    lambda value: value.update(seed=True),
    lambda value: value.update(seed=2**32),
    lambda value: value.update(iterations=99),
    lambda value: value.update(iterations=1000001),
    lambda value: value.update(iterations=100.0),
    lambda value: value.update(threshold=101),
    lambda value: value["inputs"]["handle"].update(nominal=float("nan")),
    lambda value: value["inputs"]["sticker"].update(nominal=.005),
    lambda value: value["inputs"]["offset_x"].update(tol_plus=-.1),
    lambda value: value["inputs"]["offset_y"].update(cpk=0),
    lambda value: value["inputs"]["handle"].update(nominal=1e308, tol_plus=1e308),
    lambda value: value["projection"].update(reference_axis="Q"),
])
def test_corrupt_saved_engineering_block_rejected_on_load_and_mutable_resave(mutate, tmp_path):
    project = Project("Mutable", study={"projected_interference": _settings()})
    mutate(project.study["projected_interference"])
    with pytest.raises(ValueError):
        project.save(tmp_path / "invalid.json")
    raw = Project("Legacy").to_dict()
    raw["study"]["projected_interference"] = deepcopy(project.study["projected_interference"])
    with pytest.raises(ValueError):
        Project.from_dict(raw)


def _frame():
    return projection_from_circles(
        {"center": [0, 0, 1], "normal": [0, 0, 1], "radius": 2},
        {"center": [.2, -.3, 2], "normal": [0, 0, -1], "radius": 1},
        "Y",
    ).to_dict()


def test_projected_frame_provenance_roundtrip_stays_in_cad_units(tmp_path):
    settings = _settings()
    settings["projection"]["frame"] = _frame()
    project = Project("With CAD plane", study={"projected_interference": settings})
    destination = tmp_path / "frame.json"
    project.save(destination)
    restored = Project.load(destination)
    assert restored.study["projected_interference"] == settings
    assert restored.study["projected_interference"]["projection"]["frame"]["diameter_a"] == 4


@pytest.mark.parametrize("mutate", [
    lambda value: value.update(source_units="in"),
    lambda value: value["frame"].update(normal=[0, 0, 0]),
    lambda value: value["frame"].update(y_axis=[1, 0, 0]),
    lambda value: value["frame"].update(axis_angle_deg=10),
])
def test_invalid_cad_projection_provenance_rejected_before_load(mutate):
    settings = _settings()
    settings["projection"]["frame"] = _frame()
    mutate(settings["projection"])
    raw = Project("Broken frame").to_dict()
    raw["study"]["projected_interference"] = settings
    with pytest.raises(ValueError):
        Project.from_dict(raw)


@pytest.fixture
def window(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(drafts, "draft_directory", lambda: tmp_path / "auto-drafts")
    monkeypatch.setattr(TolstackWindow, "_init_step_preview_renderer", lambda self: None)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[1:]))
    instance = TolstackWindow()
    instance._project_change_timer.stop()
    instance._test_warnings = warnings
    yield instance
    instance.close()
    app.processEvents()


@pytest.mark.parametrize("mode", ["hole-hole", "hole-pin"])
def test_gui_save_reopen_restores_inputs_and_invalidates_results(window, tmp_path, mode):
    settings = _settings()
    settings["mode"] = mode
    window._eclipse_restore_settings(settings)
    window.project.study["custom"] = {"owner": "keep"}
    window.run_eclipse_analysis()
    assert window.eclipse_result_labels["mean"].text() != "—"
    destination = tmp_path / "interference.json"
    assert window._project_save_to(str(destination))
    saved = Project.load(destination)
    assert saved.study["projected_interference"] == settings
    assert saved.study["custom"] == {"owner": "keep"}
    window.eclipse_handle_nominal_input.setText("99")
    window.eclipse_seed_input.setText("7")
    assert window._project_open_from(destination)
    assert window._eclipse_save_settings() == settings
    assert window.eclipse_canvas.isHidden()
    assert all(label.text() == "—" for label in window.eclipse_result_labels.values())
    assert not window._project_is_dirty()


def test_gui_cad_frame_saved_and_recovered_without_reloading_cad(window, tmp_path):
    settings = _settings()
    settings["projection"]["frame"] = _frame()
    window._eclipse_restore_settings(settings)
    destination = tmp_path / "with-plane.json"
    assert window._project_save_to(str(destination))
    assert window.new_project()
    assert window._project_open_from(destination)
    assert window._eclipse_projection_snapshot() == settings["projection"]
    window.eclipse_handle_tol_plus_input.setText("unfinished")
    draft_path = tmp_path / "with-plane.recovery.json"
    drafts.save_draft(draft_path, window._project_draft_payload())
    assert window.new_project()
    assert window._project_open_draft_from(draft_path)
    assert window._eclipse_projection_snapshot() == settings["projection"]
    assert window.eclipse_handle_tol_plus_input.text() == "unfinished"


def test_untouched_module_save_and_new_or_legacy_open_reset_defaults(window, tmp_path):
    destination = tmp_path / "default.json"
    assert window._project_save_to(str(destination))
    assert "projected_interference" not in Project.load(destination).study
    window._eclipse_restore_settings(_settings())
    assert window.new_project()
    assert window._eclipse_save_settings() is None
    window._eclipse_restore_settings(_settings())
    assert window._project_open_from(destination)
    assert window._eclipse_save_settings() is None
    assert not window._project_is_dirty()


@pytest.mark.parametrize("name,value", [
    ("eclipse_handle_nominal_input", "not complete"),
    ("eclipse_offset_y_tol_plus_input", "-."),
    ("eclipse_seed_input", "123 unfinished"),
    ("eclipse_threshold_input", "unfinished"),
])
def test_incomplete_inputs_dirty_recover_without_valid_engineering_save(window, tmp_path, name, value):
    window._eclipse_restore_settings(_settings())
    saved_path = tmp_path / "engineering.json"
    assert window._project_save_to(str(saved_path))
    saved_bytes = saved_path.read_bytes()
    getattr(window, name).setText(value)
    assert window._project_is_dirty()
    assert window._project_save_to(str(saved_path)) is False
    assert saved_path.read_bytes() == saved_bytes
    draft_path = tmp_path / "unfinished.recovery.json"
    payload = window._project_draft_payload()
    assert payload["ui"]["widgets"][name]["text"] == value
    drafts.save_draft(draft_path, payload)
    assert window.new_project()
    assert window._project_open_draft_from(draft_path)
    assert getattr(window, name).text() == value
    assert window.eclipse_units_combo.currentText() == "in"
    assert float(window.eclipse_sticker_nominal_input.text()) == .8
    assert window.eclipse_reference_axis_combo.currentText() == "Y"
    assert window._eclipse_projection_snapshot() == _settings()["projection"]
    assert window._project_is_dirty()
    assert all(label.text() == "—" for label in window.eclipse_result_labels.values())


@pytest.mark.parametrize("name,value", [
    ("eclipse_handle_tol_minus_input", ".01"),
    ("eclipse_sticker_cpk_input", "1.1"),
    ("eclipse_offset_x_nominal_input", "-.3"),
    ("eclipse_seed_input", "456"),
    ("eclipse_threshold_input", "25"),
    ("eclipse_units_combo", "in"),
    ("eclipse_mode_combo", "Hole–pin"),
    ("eclipse_reference_axis_combo", "Y"),
    ("eclipse_iterations_input", 200),
])
def test_each_module_setting_participates_in_unsaved_change_guard(window, name, value):
    assert not window._project_is_dirty()
    widget = getattr(window, name)
    if name.endswith("combo"):
        widget.setCurrentText(value)
    elif name.endswith("iterations_input"):
        widget.setValue(value)
    else:
        widget.setText(value)
    assert window._project_is_dirty()
    payload = window._project_draft_payload()
    assert name in payload["ui"]["widgets"]


def test_incomplete_iteration_text_recovers_and_cannot_silently_save_last_value(window, tmp_path):
    window._eclipse_restore_settings(_settings())
    window.eclipse_iterations_input.lineEdit().setText("unfinished")
    assert window._project_is_dirty()
    destination = tmp_path / "unfinished-iterations.json"
    assert window._project_save_to(str(destination)) is False
    assert not destination.exists()
    draft_path = tmp_path / "unfinished-iterations.recovery.json"
    drafts.save_draft(draft_path, window._project_draft_payload())
    assert window.new_project()
    assert window._project_open_draft_from(draft_path)
    assert window.eclipse_iterations_input.lineEdit().text() == "unfinished"
    assert window.eclipse_iterations_input.value() == 300


def test_invalid_module_saved_file_keeps_existing_work(window, tmp_path):
    window._eclipse_restore_settings(_settings())
    before = window._project_raw_ui()
    raw = Project("Bad module").to_dict()
    raw["study"]["projected_interference"] = _settings()
    raw["study"]["projected_interference"]["units"] = "cm"
    destination = tmp_path / "corrupt.json"
    destination.write_text(json.dumps(raw), encoding="utf-8")
    assert window._project_open_from(destination) is False
    assert window._project_raw_ui() == before
    assert window._test_warnings


def test_corrupt_raw_projection_frame_draft_keeps_existing_inputs(window, tmp_path):
    window._eclipse_restore_settings(_settings())
    payload = window._project_draft_payload()
    payload["ui"]["projected_interference_projection"]["frame"] = _frame()
    payload["ui"]["projected_interference_projection"]["frame"]["x_axis"] = [0, 0, 0]
    path = tmp_path / "corrupt-frame.recovery.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    before = window._project_raw_ui()
    assert window._project_open_draft_from(path) is False
    assert window._project_raw_ui() == before
