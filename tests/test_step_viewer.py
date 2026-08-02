import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

from PySide6.QtWidgets import QApplication

from gui import app as gui_app
from gui.measurement_mixin import MeasurementMixin


def test_detect_step_backend_reports_missing_optional_dependencies(monkeypatch):
    import importlib.util

    def fake_find_spec(name):
        return None

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)

    backend, message = gui_app.detect_step_backend()

    assert backend is None
    assert "compas_occ backend" in message.lower()


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

    app.quit()
