"""Relinking preserves engineering identities and raw work across CAD changes."""

from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from gui.app import TolstackWindow
from gui.feature_relinking import FeatureRelinkingDialog
from gui.gdt_mixin import pattern_cell_value
from tolstack import drafts
from tolstack.domain import DatumReference, DatumSystem, FeatureDefinition, PartDefinition, PartOccurrence
from tolstack.features import signature_from_points
from tolstack.project import Project


@pytest.fixture
def window(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(drafts, "draft_directory", lambda: tmp_path / "drafts")
    monkeypatch.setattr(TolstackWindow, "_init_step_preview_renderer", lambda self: None)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[1:]))
    gui = TolstackWindow()
    gui._project_change_timer.stop()
    gui.warnings = warnings
    yield gui
    gui.close()
    app.processEvents()


def plane_info(index=1, x=0):
    points = np.array([[x, 0., 0.], [x + 1, 0., 0.], [x, 1., 0.], [x + 1, 1., 0.]])
    return {"type": "face", "index": index, "points": points,
            "surface": {"kind": "plane", "point": [x, 0., 0.], "direction": [0., 0., 1.]}}


def prepare(window, tmp_path, digest=None):
    source = tmp_path / "original.step"
    source.write_bytes(b"cad source")
    part = window.project.add_part(PartDefinition("Plate", str(source), digest, id="part"))
    window.project.add_occurrence(PartOccurrence(part.id, "Plate:1", id="occurrence"))
    info = plane_info()
    saved = window.project.add_feature(FeatureDefinition(part.id, "A plane", "plane", id="feature-A",
        signature=signature_from_points("face", info["points"], surface=info["surface"]).to_dict()))
    window._active_part_id, window._active_occurrence_id = part.id, "occurrence"
    window._project_path = str(tmp_path / "study.json")
    return part, saved, info, source


def test_changed_revision_stays_unattached_until_explicit_acceptance(window, tmp_path):
    part, saved, info, source = prepare(window, tmp_path, "a" * 64)
    before = deepcopy(saved.signature)
    moved = tmp_path / "revised.step"
    window._step_entity_info = {1: info}
    window._project_on_step_loaded(str(moved), source_sha256="b" * 64, source_hash_status="verified")
    assert window._project_source_status == "changed"
    assert window._project_revision_pending
    assert window._entity_by_feature_id == {}
    assert part.source_sha256 == "a" * 64 and part.source_file == str(source)
    assert saved.signature == before
    with pytest.raises(ValueError, match="Accept"):
        window._project_register_feature(info)
    with pytest.raises(ValueError, match="Accept"):
        window._project_manual_relink(saved.id, 0)
    with pytest.raises(ValueError, match="Accept"):
        window._project_build_pattern_control()
    assert not window._project_save_to(str(tmp_path / "blocked.json"))
    assert not (tmp_path / "blocked.json").exists()
    assert window._project_accept_loaded_revision()
    part = window.project.parts["part"]  # Failed save restores a domain copy.
    assert part.source_sha256 == "b" * 64
    assert part.source_file == str(moved)
    assert window._entity_by_feature_id[saved.id] is info
    assert set(window.project.features) == {saved.id}
    assert window._project_report_sources()[0]["revision_accepted"] is True
    assert window._project_report_sources()[0]["revision_status"] == "changed"
    assert window._project_report_sources()[0]["comparison_sha256"] == "a" * 64
    dialog = FeatureRelinkingDialog(window)
    assert "Saved SHA-256 at load: " + "a" * 64 in dialog.source_label.text()
    assert "Loaded SHA-256: " + "b" * 64 in dialog.source_label.text()
    dialog.close()


def test_legacy_unverified_loader_cannot_claim_saved_hash_as_loaded_geometry(window, tmp_path):
    part, saved, info, source = prepare(window, tmp_path, "a" * 64)
    window._step_entity_info = {1: info}
    window._project_on_step_loaded(str(source))
    assert window._project_revision_pending and not window._entity_by_feature_id
    evidence = window._project_report_sources()[0]
    assert evidence["loaded_sha256"] is None
    assert evidence["loaded_hash_status"] == "unverified"
    window._project_accept_loaded_revision()
    assert part.source_sha256 is None
    assert window._entity_by_feature_id[saved.id] is info


def test_unchanged_moved_source_retains_part_feature_and_occurrence_ids(window, tmp_path):
    part, saved, info, source = prepare(window, tmp_path, "a" * 64)
    moved = tmp_path / "folder" / "same.step"
    window._step_entity_info = {1: info}
    window._project_on_step_loaded(str(moved), source_sha256="a" * 64, source_hash_status="verified")
    assert window._project_source_status == "unchanged"
    assert not window._project_revision_pending
    assert list(window.project.parts) == [part.id]
    assert list(window.project.occurrences) == ["occurrence"]
    assert window._entity_by_feature_id[saved.id] is info
    assert part.source_file == str(moved)


def test_manual_relink_preserves_raw_rows_and_all_stable_definition_ids(window, tmp_path):
    part, saved, info, source = prepare(window, tmp_path)
    datum = window.project.add_datum_reference(DatumReference(saved.id, "A", id="datum-A"))
    system = window.project.add_datum_system(DatumSystem("DRF", [datum.id], id="drf"))
    window._active_datum_system_id = system.id
    window._datum_slot["Primary"] = {"feature_id": saved.id, "datum_ref_id": datum.id,
        "point": [0., 0., 0.], "direction": [0., 0., 1.], "description": "Recovered A", "kind": "plane"}
    window._project_preserve_raw_geometry = True
    window._pattern_add_row("Partial pattern", 1, 2, 1, 2, 10, feature_id=saved.id)
    window.pattern_table.item(0, 1).setText("unfinished basic")
    window.pattern_table.item(0, 0).setData(window.PATTERN_MEMBER_ID_ROLE, "member")
    window.pattern_table.item(0, 0).setData(window.PATTERN_SIZE_TOLERANCE_ID_ROLE, "size")
    window.table.item(0, 0).setData(window.TOLERANCE_ID_ROLE, "scalar-tolerance")
    rows = window._project_raw_ui()["tables"]
    displaced = plane_info(index=44, x=100)
    window._step_entity_info = {1: displaced, 2: {"type": "vertex", "index": 2, "points": np.array([[1., 2., 3.]])}}
    window._project_reattach_features()
    assert window._project_relink_diagnostics[0].status == "unresolved"
    with pytest.raises(ValueError, match="not a plane"):
        window._project_manual_relink(saved.id, 1)
    window._project_manual_relink(saved.id, 0)
    assert window._project_raw_ui()["tables"] == rows
    assert saved.id == "feature-A" and datum.id == "datum-A" and system.id == "drf"
    assert window._datum_slot["Primary"]["datum_ref_id"] == datum.id
    np.testing.assert_allclose(window._datum_slot["Primary"]["point"], [100.5, .5, 0])
    assert window._current_drf is None
    other = window.project.add_feature(FeatureDefinition(part.id, "Other", "plane", id="other"))
    with pytest.raises(ValueError, match="already assigned"):
        window._project_manual_relink(other.id, 0)
    assert window._last_gdt_report is None and window._last_analysis_report is None


def test_dialog_displays_ambiguous_features_numeric_scores_and_reasons(window, tmp_path):
    part, saved, info, source = prepare(window, tmp_path)
    window._step_entity_info = {1: plane_info(1), 2: plane_info(2, x=.001)}
    window._project_reattach_features()
    dialog = FeatureRelinkingDialog(window)
    assert dialog.features.item(0, 3).text() == "ambiguous"
    assert float(dialog.features.item(0, 4).text()) == 0
    dialog.features.selectRow(0)
    assert dialog.candidates.rowCount() == 2
    assert "Center distance" in dialog.candidates.item(0, 3).text()
    dialog.candidates.selectRow(0)
    dialog._assign()
    assert window._entity_by_feature_id[saved.id] is info or window._entity_by_feature_id[saved.id]["index"] == 1
    dialog.close()


def test_dialog_refuses_candidate_catalog_from_replaced_scene(window, tmp_path):
    part, saved, info, source = prepare(window, tmp_path)
    window._step_entity_info = {1: info}
    window._project_reattach_features()
    dialog = FeatureRelinkingDialog(window)
    dialog.features.selectRow(0)
    dialog.candidates.selectRow(0)
    window._step_entity_info = {1: plane_info(index=99, x=100)}
    window._project_reattach_features()
    dialog._assign()
    assert saved.id not in window._entity_by_feature_id
    assert any("CAD scene changed" in warning for warning in window.warnings)
    dialog.close()


def test_project_relative_source_open_save_as_and_failed_save_preserve_physical_target(window, tmp_path, monkeypatch):
    project_dir = tmp_path / "study"
    project_dir.mkdir()
    source = project_dir / "cad" / "plate.step"
    source.parent.mkdir()
    source.write_bytes(b"cad")
    project = Project("Portable")
    part = project.add_part(PartDefinition("Plate", "cad/plate.step", id="part"))
    project_path = project_dir / "project.json"
    project.save(project_path)
    loads = []
    monkeypatch.setattr(window, "_start_step_load", lambda path: loads.append(path))
    assert window._project_open_from(str(project_path))
    assert loads == [str(source)]
    target = tmp_path / "moved" / "project.json"
    target.parent.mkdir()
    assert window._project_save_to(str(target))
    assert window.project.parts[part.id].source_file == "../study/cad/plate.step"
    assert window._project_resolve_source(window.project.parts[part.id]) == source
    previous = window.project.to_dict()
    monkeypatch.setattr(Project, "save", lambda *args: (_ for _ in ()).throw(OSError("locked")))
    assert not window._project_save_to(str(tmp_path / "failure.json"))
    assert window.project.to_dict() == previous
    assert window._project_resolve_source(window.project.parts[part.id]) == source


def test_source_chooser_cancel_does_not_mutate_and_selected_path_requests_reload(window, tmp_path, monkeypatch):
    part, saved, info, source = prepare(window, tmp_path)
    before = window.project.to_dict()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: ("", ""))
    assert not window.locate_project_source()
    assert window.project.to_dict() == before
    selected = tmp_path / "moved.step"
    loads = []
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(selected), ""))
    monkeypatch.setattr(window, "_start_step_load", lambda path: loads.append(path))
    assert window.locate_project_source()
    assert loads == [str(selected)]
    assert part.source_file == str(source)
    assert window._project_preserve_raw_geometry


def _assign_complete_geometry(window, tmp_path):
    part, saved, _info, source = prepare(window, tmp_path, "a" * 64)
    infos = []
    for index, (slot, points, direction) in enumerate((
        ("Primary", [[0., 0., 0.], [2., 0., 0.], [0., 2., 0.], [2., 2., 0.]], [0., 0., 1.]),
        ("Secondary", [[0., 0., 0.], [2., 0., 0.], [0., 0., 2.], [2., 0., 2.]], [0., 1., 0.]),
        ("Tertiary", [[0., 0., 0.], [0., 2., 0.], [0., 0., 2.], [0., 2., 2.]], [1., 0., 0.]),
    )):
        info = {"type": "face", "index": index, "points": np.array(points),
                "surface": {"kind": "plane", "point": [0., 0., 0.], "direction": direction}}
        assert window._set_datum_from_info(slot, info)
        infos.append(info)
    window.build_datum_frame()
    circle = {"center": np.array([1., 2., 0.]), "normal": np.array([0., 0., 1.]), "radius": 5.}
    points = np.array([[6., 2., 0.], [1., 7., 0.], [-4., 2., 0.], [1., -3., 0.]])
    circle_info = {"type": "edge", "index": 4, "points": points, "circle": circle}
    feature_id = window._project_register_feature(circle_info, "Hole")
    window._pattern_add_row("Hole", 1, 2, 1, 2, 10, feature_id=feature_id)
    window._project_sync_datums_from_ui()
    window._project_sync_position_from_ui()
    return part, infos, circle_info, source


def test_saved_unresolved_member_rows_remain_visible_with_their_original_ids(window, tmp_path):
    _assign_complete_geometry(window, tmp_path)
    control = window.project.position_controls[window._active_position_control_id]
    member = control.members[0]
    window._current_drf = None
    window._entity_by_feature_id = {}
    window._project_restore_position_control()
    assert window.pattern_table.rowCount() == 1
    name = window.pattern_table.item(0, 0)
    assert name.data(window.PATTERN_FEATURE_ID_ROLE) == member.feature_id
    assert name.data(window.PATTERN_MEMBER_ID_ROLE) == member.id
    assert name.data(window.PATTERN_SIZE_TOLERANCE_ID_ROLE) == member.size_tolerance_id
    assert name.data(window.PATTERN_X_TOLERANCE_ID_ROLE) == member.position_x_tolerance_id
    assert name.data(window.PATTERN_Y_TOLERANCE_ID_ROLE) == member.position_y_tolerance_id
    assert window.pattern_table.item(0, 3).text() == "Unresolved"
    assert member.feature_id in window.project.features


def test_rebuild_refreshes_only_actual_coordinates_after_recovered_geometry_relinks(window, tmp_path):
    part, planes, circle, source = _assign_complete_geometry(window, tmp_path)
    window.pattern_table.item(0, 1).setText("unfinished basic X")
    window.pattern_table.item(0, 6).setText("0.0123456789012345")
    before = window._project_table_snapshot("pattern")
    window._project_preserve_raw_geometry = True
    window._project_capture_raw_geometry_before_load()
    replacement = deepcopy(circle)
    replacement["circle"]["center"] = np.array([1.000000012345, 2.000000098765, 0.])
    replacement["points"] += replacement["circle"]["center"] - circle["circle"]["center"]
    window._step_entity_info = {index: deepcopy(info) for index, info in enumerate([*planes, replacement])}
    window._project_on_step_loaded(str(source), source_sha256="a" * 64, source_hash_status="verified")
    assert window._current_drf is None
    assert window._project_table_snapshot("pattern") == before
    window.build_datum_frame()
    assert window._current_drf is not None
    # B points along model Y, so local X is model Y and local Y is -model X.
    assert pattern_cell_value(window.pattern_table, 0, 3) == pytest.approx(2.000000098765, abs=1e-14)
    assert pattern_cell_value(window.pattern_table, 0, 4) == pytest.approx(-1.000000012345, abs=1e-14)
    after = window._project_table_snapshot("pattern")
    for column in (0, 1, 2, 5, 6, 7, 8):
        assert after[0][column] == before[0][column]


def test_hash_first_established_on_disk_open_remains_unsaved_change(window, tmp_path):
    part, saved, info, source = prepare(window, tmp_path)
    window._project_mark_clean()
    window._project_loading_clean_from_disk = True
    window._step_entity_info = {1: info}
    window._project_on_step_loaded(str(source), source_sha256="a" * 64, source_hash_status="verified")
    assert window.project.parts[part.id].source_sha256 == "a" * 64
    assert window._project_is_dirty()


def test_missing_source_open_displays_unresolved_saved_members_without_dirtying_project(window, tmp_path):
    part, _planes, _circle, _source = _assign_complete_geometry(window, tmp_path)
    control = window.project.position_controls[window._active_position_control_id]
    member = deepcopy(control.members[0])
    part.source_file = "cad/missing.step"
    path = tmp_path / "missing-source.json"
    window.project.save(path)
    assert window._project_open_from(str(path))
    assert window._current_drf is None
    assert not window._project_is_dirty()
    assert window.pattern_table.rowCount() == 1
    name = window.pattern_table.item(0, 0)
    assert name.text() == member.name
    assert name.data(window.PATTERN_FEATURE_ID_ROLE) == member.feature_id
    assert name.data(window.PATTERN_MEMBER_ID_ROLE) == member.id
    assert name.data(window.PATTERN_SIZE_TOLERANCE_ID_ROLE) == member.size_tolerance_id
    assert window.pattern_table.item(0, 3).text() == "Unresolved"
    assert "unavailable" in window.step_status_label.text()
