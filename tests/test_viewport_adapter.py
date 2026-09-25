from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

from gui.viewport_adapter import CompasViewportAdapter


class FakeScene:
    def __init__(self):
        self.objects = []

    def add(self, geometry, **style):
        obj = SimpleNamespace(geometry=geometry, style=style, is_selected=False)
        self.objects.append(obj)
        return obj

    def remove(self, obj):
        self.objects.remove(obj)


class FakeRenderer:
    def __init__(self):
        self.scene = FakeScene()
        self.events = []
        self.fail_rebuild = False

    def makeCurrent(self):
        self.events.append("acquire")

    def doneCurrent(self):
        self.events.append("release")

    def rebuild_buffers(self):
        self.events.append("rebuild")
        if self.fail_rebuild:
            raise RuntimeError("Buffer failure")

    def update(self):
        self.events.append("update")


def test_scene_mutation_and_selection_leave_no_stale_objects():
    renderer = FakeRenderer()
    adapter = CompasViewportAdapter(renderer)
    face = adapter.add("face", facecolor="blue")
    edge = adapter.add("edge", linewidth=2)
    adapter.select(edge)
    assert not face.is_selected and edge.is_selected
    assert face.style == {"facecolor": "blue"}
    snapshot = adapter.objects
    adapter.clear()
    assert len(snapshot) == 2
    assert adapter.objects == ()


def test_buffer_rebuild_releases_context_before_scheduling_repaint():
    renderer = FakeRenderer()
    CompasViewportAdapter(renderer).refresh(rebuild=True)
    assert renderer.events == ["acquire", "rebuild", "release", "update"]


def test_failed_buffer_rebuild_releases_gl_context():
    renderer = FakeRenderer()
    renderer.fail_rebuild = True
    with pytest.raises(RuntimeError, match="Buffer failure"):
        CompasViewportAdapter(renderer).refresh(rebuild=True)
    assert renderer.events == ["acquire", "rebuild", "release"]
