import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

from PySide6.QtWidgets import QApplication

from gui import app as gui_app
from gui.measurement_mixin import MeasurementMixin
from gui.step_renderer import VIEWPORT_THEME
from gui.step_viewer_mixin import StepViewerMixin


def test_detect_step_backend_reports_missing_optional_dependencies(monkeypatch):
    import importlib.util

    def fake_find_spec(name):
        return None

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)

    backend, message = gui_app.detect_step_backend()

    assert backend is None
    assert "compas_occ backend" in message.lower()


def test_viewport_theme_matches_application_and_grid_scales_cleanly():
    assert VIEWPORT_THEME == {
        "background": "#1C2228",
        "grid": "#343E47",
        "selection": "#FFAE5C",
    }
    assert StepViewerMixin._nice_grid_extent(0.7) == 1.0
    assert StepViewerMixin._nice_grid_extent(18.0) == 20.0
    assert StepViewerMixin._nice_grid_extent(126.0) == 200.0


def test_measure_context_menu_exposes_slot_and_bank_actions():
    app = QApplication.instance() or QApplication([])

    class DummyWindow(MeasurementMixin):
        def __init__(self):
            self._measure_slot = {
                "A": {"type": "face", "index": 1},
                "B": {"type": "edge", "index": 2},
            }
            self._measure_last = {"normal_distance": 1.23}
            self._measure_arm = None
            self.measure_tol_plus_input = type("TolInput", (), {"text": lambda self: "0.0"})()
            self.measure_tol_minus_input = type("TolInput", (), {"text": lambda self: "0.0"})()
            self.bank = type("Bank", (), {
                "names": lambda self: [],
                "add": lambda *args, **kwargs: None,
            })()
            self._refresh_bank_combo = lambda: None

    window = DummyWindow()
    menu = window._build_measure_context_menu({"type": "face", "index": 4})

    texts = [action.text() for action in menu.actions()]
    assert "Set as Measure A" in texts
    assert "Set as Measure B" in texts
    assert "Add measurement to Dimension Bank" in texts
    assert "Inspect properties" in texts
    assert "Set as datum" in texts
    assert "Link selected stack term" in texts

    app.quit()


def test_context_menu_exposes_size_actions_only_for_circular_edges():
    app = QApplication.instance() or QApplication([])

    class DummyWindow(MeasurementMixin):
        def __init__(self):
            self._measure_slot = {"A": None, "B": None}
            self._measure_last = None

    angles = np.linspace(0.0, 2.0 * np.pi, 32, endpoint=False)
    circular_edge = {
        "type": "edge",
        "index": 1,
        "points": np.column_stack([2.0 * np.cos(angles), 2.0 * np.sin(angles), angles * 0.0]),
    }
    planar_face = {
        "type": "face",
        "index": 2,
        "points": circular_edge["points"],
    }

    window = DummyWindow()
    edge_menu = window._build_measure_context_menu(circular_edge)
    face_menu = window._build_measure_context_menu(planar_face)
    edge_texts = [action.text() for action in edge_menu.actions()]
    face_texts = [action.text() for action in face_menu.actions()]

    assert "Add size tolerance…" in edge_texts
    assert "Add to position pattern…" in edge_texts
    assert "Add size tolerance…" not in face_texts
    assert "Add to position pattern…" not in face_texts

    app.quit()
