import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from compas.datastructures import Mesh
from PySide6.QtWidgets import QApplication, QSlider, QLabel
from PySide6.QtTest import QTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))
from gui.app import TolstackWindow
from gui.offset_preview import OffsetControls, offset_layers, replace_preview, tolerance_limits


class Scene:
    def __init__(self):
        self.objects = []

    def add(self, mesh, **options):
        obj = SimpleNamespace(mesh=mesh, options=options)
        self.objects.append(obj)
        return obj

    def remove(self, obj):
        self.objects.remove(obj)


class Renderer:
    def __init__(self):
        self.scene = Scene()
        self.refreshes = 0

    def makeCurrent(self):
        pass

    def doneCurrent(self):
        pass

    def update(self):
        pass

    def rebuild_buffers(self):
        self.refreshes += 1


def face(z=0):
    points = np.array([[0, 0, z], [1, 0, z], [1, 1, z], [0, 1, z]], dtype=float)
    return {"type": "face", "index": 0, "points": points,
            "mesh": Mesh.from_vertices_and_faces(points.tolist(), [[0, 1, 2, 3]])}


@pytest.fixture
def window(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(TolstackWindow, "_init_step_preview_renderer", lambda self: None)
    w = TolstackWindow()
    w._stack_preview_timer.stop()
    w._step_preview_renderer = Renderer()
    yield w
    w._stack_preview_timer.stop()
    w._measure_offset_timer.stop()
    w.close()
    app.processEvents()


def wait_preview(window):
    for _ in range(100):
        QTest.qWait(10)
        if not window._measure_offset_timer.isActive() and not window._stack_preview_timer.isActive():
            return
    pytest.fail("Preview timers did not settle")


def current_z(renderer):
    obj = next(obj for obj in renderer.scene.objects if obj.options["name"] == "Current offset")
    return np.asarray([obj.mesh.vertex_coordinates(key) for key in obj.mesh.vertices()])[:, 2]


@pytest.mark.parametrize("slot, expected", [("A", -0.1), ("B", 10.1)])
def test_measure_uses_deviation_and_correct_source_direction(window, slot, expected):
    source = face(0 if slot == "A" else 10)
    other = {"type": "vertex", "index": 1, "points": [[0, 0, 10 if slot == "A" else 0]]}
    window._measure_slot = {slot: source, "B" if slot == "A" else "A": other}
    window._measure_last = {"reference_is_face": True, "reference_normal": np.array([0, 0, 1]), "normal_distance": 10.0}
    window.measure_tol_plus_input.setText("0.3")
    window.measure_tol_minus_input.setText("0.2")
    window.show_tolerance_offset()
    np.testing.assert_allclose(current_z(window._step_preview_renderer), 0 if slot == "A" else 10)
    window.measure_offset_controls.distance.setValue(0.1)
    wait_preview(window)
    np.testing.assert_allclose(current_z(window._step_preview_renderer), expected)
    assert len(window._step_preview_renderer.scene.objects) == 3
    window.measure_offset_controls.reverse.setChecked(True)
    wait_preview(window)
    np.testing.assert_allclose(current_z(window._step_preview_renderer), -expected if slot == "A" else 9.9)
    window.measure_tol_plus_input.setText("nan")
    wait_preview(window)
    assert not window._step_preview_renderer.scene.objects
    window.measure_tol_plus_input.setText("0.3")
    wait_preview(window)
    assert len(window._step_preview_renderer.scene.objects) == 3
    window.clear_tolerance_offset()
    assert not window._step_preview_renderer.scene.objects
    np.testing.assert_allclose(source["points"][:, 2], 0 if slot == "A" else 10)


def link_row(window, row, source):
    window._entity_by_feature_id["surface"] = source
    window._stack_link_set_row_link(row, {"feature_id": "surface", "mode": "normal_offset"})


def test_stack_slider_starts_at_nominal_and_updates_during_drag(window):
    source = face()
    link_row(window, 0, source)  # nominal 25, asymmetric +0.10 / -0.05
    window.table.setCurrentCell(0, 0)
    assert window._stack_link_row_current_value(0) == 25.0
    container = window.table.cellWidget(0, window.STACK_LINK_VALUE_COLUMN)
    slider = container.findChild(QSlider)
    slider.setValue(1000)  # no sliderReleased signal
    wait_preview(window)
    np.testing.assert_allclose(current_z(window._step_preview_renderer), 0.1)
    window.stack_offset_controls.distance.setValue(0.025)
    wait_preview(window)
    assert window._stack_link_row_current_value(0) == 25.025
    np.testing.assert_allclose(current_z(window._step_preview_renderer), 0.025)
    window.stack_offset_controls.reverse.setChecked(True)
    wait_preview(window)
    np.testing.assert_allclose(current_z(window._step_preview_renderer), -0.025)
    window.stack_offset_controls.limits.setChecked(False)
    wait_preview(window)
    assert len(window._step_preview_renderer.scene.objects) == 1


def test_combined_offsets_and_geometry_clear(window):
    source = face()
    link_row(window, 0, source)
    link_row(window, 1, source)
    window._stack_link_set_row_value(0, 25.02)
    window._stack_link_set_row_value(1, 12.51)
    window._stack_link_rebuild_preview()
    np.testing.assert_allclose(current_z(window._step_preview_renderer), 0.03)
    positions = {obj.options["name"]: obj.mesh.vertex_coordinates(0)[2] for obj in window._step_preview_renderer.scene.objects}
    assert positions["Lower tolerance"] == pytest.approx(-0.1)
    assert positions["Upper tolerance"] == pytest.approx(0.15)
    window.clear_step_preview()
    wait_preview(window)
    assert not window._step_preview_renderer.scene.objects
    assert not window._stack_link_preview_objs
    assert not window._entity_by_feature_id


def test_slider_still_targets_its_row_after_previous_row_deleted(window):
    link_row(window, 1, face())
    window.table.removeRow(0)
    window.table.setCurrentCell(0, 0)
    container = window.table.cellWidget(0, window.STACK_LINK_VALUE_COLUMN)
    container.findChild(QSlider).setValue(1000)
    wait_preview(window)
    assert container.findChild(QLabel).text() == "12.5500"
    np.testing.assert_allclose(current_z(window._step_preview_renderer), 0.05)


def test_degenerate_and_invalid_limits_do_not_generate_geometry():
    for plus, minus in [(float("nan"), 1), (1, -1), (float("inf"), 0)]:
        with pytest.raises(ValueError):
            tolerance_limits(plus, minus)
    with pytest.raises(ValueError):
        offset_layers({"type": "face", "points": [[0, 0, 0], [1, 0, 0], [2, 0, 0]]}, 0, -1, 1)
    assert len(offset_layers(face(), 0, 0, 0)) == 1


def test_invalid_shared_dimension_hides_entire_feature_until_corrected(window):
    source = face()
    link_row(window, 0, source)
    link_row(window, 1, source)
    window._stack_link_rebuild_preview()
    assert window._step_preview_renderer.scene.objects
    window.table.item(1, 2).setText("-1")
    wait_preview(window)
    assert not window._step_preview_renderer.scene.objects
    window.table.item(1, 2).setText("0.05")
    wait_preview(window)
    assert window._step_preview_renderer.scene.objects


def test_renderer_failure_cleans_new_layers_and_releases_context(monkeypatch):
    renderer = Renderer()
    released = []
    monkeypatch.setattr(renderer, "doneCurrent", lambda: released.append(True))
    def fail():
        raise RuntimeError("buffer allocation failed")
    monkeypatch.setattr(renderer, "rebuild_buffers", fail)
    with pytest.raises(RuntimeError):
        replace_preview(renderer, [], face(), offset_layers(face(), 0, -1, 1))
    assert not renderer.scene.objects
    assert released == [True]


def test_partial_scene_addition_rolls_back(monkeypatch):
    renderer = Renderer()
    source = face()
    original = source["mesh"].copy()
    add = renderer.scene.add
    def fail_second(mesh, **options):
        if renderer.scene.objects:
            raise RuntimeError("scene allocation failed")
        return add(mesh, **options)
    monkeypatch.setattr(renderer.scene, "add", fail_second)
    with pytest.raises(RuntimeError):
        replace_preview(renderer, [], source, offset_layers(source, 0, -1, 1))
    assert not renderer.scene.objects
    assert source["mesh"].to_vertices_and_faces() == original.to_vertices_and_faces()
