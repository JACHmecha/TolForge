import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

from gui import app as gui_app


def test_detect_step_backend_reports_missing_backend(monkeypatch):
    import importlib.util

    def fake_find_spec(name):
        return None

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)

    backend, message = gui_app.detect_step_backend()

    assert backend is None
    assert "compas_occ" in message.lower()


def test_detect_step_backend_flags_unsupported_alternatives(monkeypatch):
    import importlib.util

    def fake_find_spec(name):
        return object() if name == "cadquery" else None

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)

    backend, message = gui_app.detect_step_backend()

    # cadquery being present isn't enough: only compas_occ gives us
    # COMPAS-native geometry the renderer can consume.
    assert backend is None
    assert "cadquery" in message
    assert "compas_occ" in message


def test_detect_step_backend_reports_compas_occ(monkeypatch):
    import importlib.util

    def fake_find_spec(name):
        return object() if name == "compas_occ" else None

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)

    backend, message = gui_app.detect_step_backend()

    assert backend == "compas_occ"
    assert "compas_occ" in message.lower()
