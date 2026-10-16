"""Selection behavior without a Qt widget or native OpenGL context."""

from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

from gui.step_renderer import Renderer
from gui.step_viewer_mixin import StepViewerMixin


class Label:
    def __init__(self):
        self.value = ""

    def setText(self, value):
        self.value = value


class SelectionHarness(StepViewerMixin):
    def __init__(self):
        self._pick_filter = "any"
        self._pick_markers = []
        self._step_entity_info = {}
        self.step_status_label = Label()
        self.inspected = None
        self.inspector_updates = []
        self.repaint_count = 0
        self._step_preview_renderer = SimpleNamespace(
            scene=SimpleNamespace(objects=[], instance_colors={}),
            update=self._repaint,
        )

    def _repaint(self):
        self.repaint_count += 1

    def _update_selection_inspector(self, info):
        self.inspected = info
        self.inspector_updates.append(info)

    def add(self, kind, index, *, solid_index=None):
        obj = SimpleNamespace(is_selected=False)
        info = {"type": kind, "index": index, "points": np.array([[float(index), 0., 0.]])}
        if solid_index is not None:
            info["solid_index"] = solid_index
        self._step_entity_info[id(obj)] = info
        self._step_preview_renderer.scene.objects.append(obj)
        return obj


def click_renderer(window, obj, *, context=False):
    """Run the actual hit-routing method against a framebuffer double."""
    if Renderer is None:
        pytest.skip("Optional COMPAS renderer cannot be imported in this environment")
    renderer = window._step_preview_renderer
    color = (10, 20, 30)
    renderer.scene.instance_colors = {} if obj is None else {color: obj}
    renderer.read_instance_color = lambda _box: np.array([[[*color]]])
    if context:
        renderer.resolve_entity_info = window._resolve_entity_info_for_renderer
        renderer.context_result = None

        def show_menu(info, pos):
            renderer.context_result = (info, pos)

        renderer.on_measure_context_menu = show_menu
        Renderer._handle_right_click(renderer, 4, 5)
        return renderer.context_result
    renderer.on_pick = window._on_step_entity_picked
    Renderer._handle_click_select(renderer, 4, 5)


def test_rejected_hit_preserves_previous_logical_visual_and_inspector_selection():
    window = SelectionHarness()
    original = window.add("face", 0, solid_index=0)
    rejected = window.add("face", 1, solid_index=1)
    window._on_step_entity_picked(original)
    original_info = window.inspected
    updates = window.repaint_count, len(window.inspector_updates)
    consumed = []
    window._measure_on_pick = lambda obj: consumed.append(obj) or True
    window.set_pick_filter("Edges")

    click_renderer(window, rejected)

    assert original.is_selected and not rejected.is_selected
    assert window._selected_entity_info is original_info
    assert window.inspected is original_info
    assert (window.repaint_count, len(window.inspector_updates)) == updates
    assert not consumed
    assert "ignored" in window.step_status_label.value


def test_accepted_hit_and_empty_hit_commit_the_same_selection_everywhere():
    window = SelectionHarness()
    original = window.add("face", 0, solid_index=0)
    target = window.add("edge", 1)
    window._on_step_entity_picked(original)
    window.set_pick_filter("Edges")

    click_renderer(window, target)

    assert not original.is_selected and target.is_selected
    assert window.inspected is window._selected_entity_info is window._step_entity_info[id(target)]

    click_renderer(window, None)

    assert not any(obj.is_selected for obj in window._step_preview_renderer.scene.objects)
    assert window._selected_entity_info is None and window.inspected is None
    assert window.step_status_label.value == "Selection cleared."


def test_solid_selection_highlights_every_face_without_replacing_scene_ids():
    window = SelectionHarness()
    other = window.add("face", 0, solid_index=0)
    first = window.add("face", 1, solid_index=1)
    second = window.add("face", 2, solid_index=1)
    edge = window.add("edge", 3)
    original_ids = [id(obj) for obj in window._step_preview_renderer.scene.objects]
    window.set_pick_filter("Solids")

    click_renderer(window, first)

    assert first.is_selected and second.is_selected
    assert not other.is_selected and not edge.is_selected
    assert [id(obj) for obj in window._step_preview_renderer.scene.objects] == original_ids
    assert window.inspected is window._selected_entity_info
    assert window.inspected["type"] == "solid" and window.inspected["index"] == 1
    np.testing.assert_array_equal(window.inspected["points"], np.array([[1., 0., 0.], [2., 0., 0.]]))
    assert "2 faces" in window.step_status_label.value


@pytest.mark.parametrize("consumer", ["_measure_on_pick", "_datum_on_pick", "_stack_link_on_pick"])
def test_consumed_hit_already_has_coherent_selection_and_keeps_tool_status(consumer):
    window = SelectionHarness()
    target = window.add("face", 0, solid_index=0)
    consumed = []

    def consume(obj):
        info = window._step_entity_info[id(obj)]
        consumed.append(obj)
        assert window.inspected is window._selected_entity_info is info
        assert target.is_selected
        window.step_status_label.setText("Tool completed")
        return True

    setattr(window, consumer, consume)

    click_renderer(window, target)

    assert consumed == [target]
    assert window.step_status_label.value == "Tool completed"


def test_context_target_syncs_selection_without_consuming_armed_left_click_tool():
    window = SelectionHarness()
    previous = window.add("face", 0, solid_index=0)
    target = window.add("edge", 1)
    window._on_step_entity_picked(previous)
    window.set_pick_filter("Solids")
    consumed = []
    window._measure_on_pick = lambda obj: consumed.append(obj) or True

    info, pos = click_renderer(window, target, context=True)

    assert info is window.inspected is window._selected_entity_info is window._step_entity_info[id(target)]
    assert pos == (4, 5)
    assert target.is_selected and not previous.is_selected
    assert not consumed


def test_clear_discards_inspector_and_solid_markers_with_displayed_geometry(monkeypatch):
    window = SelectionHarness()
    target = window.add("face", 0, solid_index=0)
    window.set_pick_filter("Solids")
    window._on_step_entity_picked(target)
    assert window._pick_markers and window.inspected is not None
    window._step_load_generation = 0
    window._request_step_load_cancel = lambda: False
    window._reset_surface_previews = lambda: None
    scene = window._step_preview_renderer.scene
    scene.remove = scene.objects.remove
    monkeypatch.setattr("gui.step_viewer_mixin.QApplication.processEvents", lambda: None)

    window.clear_step_preview()

    assert window._selected_entity_info is None and window.inspected is None
    assert not window._pick_markers
    assert not scene.objects and not window._step_entity_info
    assert window.step_status_label.value == "No STEP file loaded yet."
