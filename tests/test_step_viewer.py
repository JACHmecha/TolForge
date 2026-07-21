import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

from gui import app as gui_app


def test_detect_step_backend_reports_missing_optional_dependencies(monkeypatch):
    import importlib.util

    def fake_find_spec(name):
        return None

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)

    backend, message = gui_app.detect_step_backend()

    assert backend is None
    assert "optional CAD backend" in message.lower()
