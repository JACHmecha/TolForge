from types import SimpleNamespace
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

import numpy as np
from compas.colors import Color
from compas.datastructures import Mesh
from tolstack import PartDefinition, Project

from gui.datum_inspection import DATUM_STYLES, frame_axes
from gui.step_renderer import StepPreviewRenderer, _BaseRenderer
from test_offset_preview import window  # shared headless Qt + fake scene fixture


def assign_datums(window):
    part = window.project.add_part(PartDefinition("Inspection block"))
    window._active_part_id = part.id
    faces = [
        [[2, 3, 4], [12, 3, 4], [12, 13, 4], [2, 13, 4]],
        [[2, 3, 4], [2, 13, 4], [2, 13, 14], [2, 3, 14]],
        [[2, 3, 4], [12, 3, 4], [12, 3, 14], [2, 3, 14]],
    ]
    sources = []
    for index, (slot, points) in enumerate(zip(DATUM_STYLES, faces)):
        mesh = Mesh.from_vertices_and_faces(points, [[0, 1, 2, 3]])
        info = {"type": "face", "index": index, "mesh": mesh, "points": np.array(points, dtype=float)}
        obj = window._step_preview_renderer.scene.add(mesh, name=f"Source {index}")
        obj.facecolor = Color.from_hex("#64788A")
        window._step_entity_info[id(obj)] = info
        sources.append((obj, info))
        assert window._set_datum_from_info(slot, info)
    return sources


def test_assignment_highlights_faces_and_reports_selected_datum(window):
    sources = assign_datums(window)
    assert len(window._datum_visual_objects) == 6  # label and leader for each datum
    for (obj, info), (slot, (letter, color)) in zip(sources, DATUM_STYLES.items()):
        assert obj.facecolor == Color.from_hex(color)
        window._update_selection_inspector(info)
        assert f"{letter} ({slot.lower()})" in window.selection_datum_label.text()
    window.build_datum_frame()
    np.testing.assert_allclose(window._current_drf.origin, [2, 3, 4])
    assert len(window._datum_visual_objects) == 17  # 6 datum + origin/label + 3 axes/arrows/labels
    for name, start, end, _color in frame_axes(window._current_drf, 5):
        np.testing.assert_allclose(start, [2, 3, 4])
        assert np.linalg.norm(end - start) == 5
    assert "model coordinates" in window.drf_status_label.text()


def test_visibility_toggles_restore_source_colors_and_keep_assignments(window):
    sources = assign_datums(window)
    window.build_datum_frame()
    window.show_datum_faces.setChecked(False)
    assert len(window._datum_visual_objects) == 11
    assert all(obj.facecolor == Color.from_hex("#64788A") for obj, _info in sources)
    window.show_datum_frame.setChecked(False)
    assert not window._datum_visual_objects
    assert window._current_drf is not None
    window.show_datum_faces.setChecked(True)
    assert len(window._datum_visual_objects) == 6
    window.datum_axis_scale.setValue(200)
    assert len(window._datum_visual_objects) == 6  # no accumulation on rescale


def test_reassignment_invalidates_old_frame_and_geometry_clear_removes_all_markers(window):
    sources = assign_datums(window)
    window.build_datum_frame()
    window._pattern_arm = True
    window._set_datum_from_info("Primary", sources[0][1])
    assert window._current_drf is None
    assert not window._pattern_arm
    assert len(window._datum_visual_objects) == 6
    window.build_datum_frame()
    window.datum_clear_secondary()
    assert window._current_drf is None
    assert len(window._datum_visual_objects) == 4
    assert sources[1][0].facecolor == Color.from_hex("#64788A")
    window.clear_step_preview()
    assert not window._datum_visual_objects
    assert all(entry is None for entry in window._datum_slot.values())
    assert not window._step_preview_renderer.scene.objects


def test_project_datum_restore_rebuilds_visuals_without_duplicates(window):
    assign_datums(window)
    window._project_sync_datums_from_ui()
    window.project = Project.from_dict(window.project.to_dict())
    window._project_restore_datums()
    assert window._current_drf is not None
    assert len(window._datum_visual_objects) == 17
    window._project_restore_datums()
    assert len(window._datum_visual_objects) == 17
    np.testing.assert_allclose(window._current_drf.origin, [2, 3, 4])


def test_inspection_objects_hidden_only_during_pick_even_when_pick_fails(monkeypatch):
    visible = SimpleNamespace(show=True)
    hidden = SimpleNamespace(show=False)
    def fake_read(self, box):
        assert not visible.show and not hidden.show
        raise RuntimeError("simulated picking failure")
    monkeypatch.setattr(_BaseRenderer, "read_instance_color", fake_read)
    # Avoid creating an OpenGL widget: exercise the override on an uninitialized
    # Python subclass wrapper; the patched base method touches no Qt state.
    renderer = StepPreviewRenderer.__new__(StepPreviewRenderer)
    renderer.datum_inspection_objects = [visible, hidden]
    from OpenGL import GL
    restored = []
    monkeypatch.setattr(renderer, "makeCurrent", lambda: None)
    monkeypatch.setattr(renderer, "doneCurrent", lambda: None)
    monkeypatch.setattr(GL, "glGetFloatv", lambda _name: [0.1, 0.2, 0.3, 1.0])
    monkeypatch.setattr(GL, "glClearColor", lambda *color: restored.append(color))
    import pytest
    with pytest.raises(RuntimeError, match="simulated picking failure"):
        renderer.read_instance_color((1, 1, 1, 1))
    assert visible.show and not hidden.show
    assert restored == [(0.1, 0.2, 0.3, 1.0)]
