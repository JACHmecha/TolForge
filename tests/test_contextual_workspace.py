import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

from PySide6.QtWidgets import QApplication

from gui.app import TolstackWindow


def _window():
    app = QApplication.instance() or QApplication([])
    window = TolstackWindow()
    app.processEvents()
    return app, window


def test_contextual_workspace_starts_in_inspector_with_hidden_tab_bar():
    app, window = _window()
    try:
        assert window.sidebar.tabBar().isHidden()
        assert window.sidebar.currentWidget() is window.inspector_tab
        assert window.workspace_buttons["inspect"].isChecked()
        assert "measure" in window.workspace_pages
        assert "measure" in window.workspace_buttons
    finally:
        window.close()
        app.processEvents()


def test_analysis_action_switches_to_results(monkeypatch):
    app, window = _window()
    called = []
    try:
        monkeypatch.setattr(window, "run_analysis", lambda: called.append(True))
        window._run_analysis_and_show_results()
        assert called == [True]
        assert window.sidebar.currentWidget() is window.results_tab
        assert window.workspace_buttons["results"].isChecked()
    finally:
        window.close()
        app.processEvents()


def test_selection_inspector_reports_persistent_feature_state():
    app, window = _window()
    try:
        info = {"type": "edge", "index": 4, "points": [[0, 0, 0], [1, 0, 0]]}
        window._update_selection_inspector(info)
        assert window.selection_name_label.text() == "Edge 5"
        assert "not registered" in window.selection_link_label.text()
    finally:
        window.close()
        app.processEvents()


def test_workspace_can_expand_for_table_and_navigate_to_measure():
    app, window = _window()
    try:
        window.show()
        window.workspace_splitter.setSizes([480, 700])
        app.processEvents()
        assert window.sidebar.width() > 460
        window.workspace_buttons["measure"].click()
        assert window.sidebar.currentWidget() is window.measure_tab
        assert window.workspace_buttons["measure"].isChecked()
        assert not window.workspace_buttons["inspect"].isChecked()
        assert window.workspace_title.text() == "Measure geometry"
    finally:
        window.close()
        app.processEvents()
