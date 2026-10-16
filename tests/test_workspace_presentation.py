"""Layout changes must preserve engineering state and manual workspace sizing."""

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QScrollArea

from gui.app import TolstackWindow
from gui.layout_presentation import WrappedCheckBox
from tolstack.domain import Units


@pytest.fixture
def desktop(monkeypatch):
    import gui.step_viewer_mixin as viewport

    monkeypatch.setattr(viewport, "Renderer", None)
    app = QApplication.instance() or QApplication([])
    # Some sandboxed Windows processes start with an empty Qt font database.
    # Load the same font used by the desktop theme for meaningful fit checks.
    font_ids = []
    if not QFontDatabase.families():
        for name in ("segoeui.ttf", "segoeuib.ttf"):
            path = Path("C:/Windows/Fonts") / name
            if path.exists():
                font_ids.append(QFontDatabase.addApplicationFont(str(path)))
    window = TolstackWindow()
    window._project_change_timer.stop()
    window._project_draft_timer.stop()
    window.show()
    for _ in range(4):
        app.processEvents()
    yield app, window
    window.close()
    app.processEvents()
    for font_id in font_ids:
        QFontDatabase.removeApplicationFont(font_id)


def settle(app):
    for _ in range(6):
        app.processEvents()


@pytest.mark.parametrize("size", [(1024, 768), (1300, 800)])
def test_forms_fit_and_navigation_does_not_modify_engineering_state(desktop, size):
    app, window = desktop
    before = window._project_fingerprint()
    window.resize(*size)
    for name in ("study", "stack", "results", "gdt", "eclipse", "measure"):
        window._show_workspace(name)
        settle(app)
        page = window.workspace_pages[name]
        areas = page.findChildren(QScrollArea)
        if isinstance(page, QScrollArea):
            areas.append(page)
        assert areas
        assert all(area.horizontalScrollBar().maximum() == 0 for area in areas)
    assert window._project_fingerprint() == before
    assert not window._project_dirty


def test_narrow_projected_pane_keeps_all_tolerance_fields_and_titles(desktop):
    app, window = desktop
    window._show_workspace("eclipse")
    settle(app)
    window.workspace_splitter.setSizes([800, 340])
    settle(app)
    page = window.workspace_pages["eclipse"]
    assert page.horizontalScrollBar().maximum() == 0
    for prefix in ("handle", "sticker", "offset_x", "offset_y"):
        caption = getattr(window, f"eclipse_{prefix}_caption")
        assert caption.width() > 0 and caption.height() >= caption.fontMetrics().height()
        for field in ("nominal", "tol_plus", "tol_minus", "cpk"):
            editor = getattr(window, f"eclipse_{prefix}_{field}_input")
            assert editor.width() >= 80
            assert editor.geometry().right() < editor.parentWidget().width()


def test_manual_divider_choice_survives_page_changes_and_window_resize(desktop):
    app, window = desktop
    window._show_workspace("stack")
    settle(app)
    original_width = window.sidebar.width()
    handle = window.workspace_splitter.handle(1)
    center = handle.rect().center()
    QTest.mousePress(handle, Qt.LeftButton, pos=center)
    QTest.mouseMove(handle, center + QPoint(90, 0))
    QTest.mouseRelease(handle, Qt.LeftButton, pos=center + QPoint(90, 0))
    settle(app)
    assert window.sidebar.width() < original_width - 50
    chosen_ratio = window.sidebar.width() / sum(window.workspace_splitter.sizes())
    window._show_workspace("inspect")
    settle(app)
    window._show_workspace("stack")
    settle(app)
    restored_ratio = window.sidebar.width() / sum(window.workspace_splitter.sizes())
    assert restored_ratio == pytest.approx(chosen_ratio, abs=0.01)
    window.resize(1450, 900)
    settle(app)
    resized_ratio = window.sidebar.width() / sum(window.workspace_splitter.sizes())
    assert resized_ratio == pytest.approx(chosen_ratio, abs=0.01)


def test_wrapping_checkbox_keeps_text_click_and_keyboard_behavior(desktop):
    app, window = desktop
    checkbox = window.inspection_alignment_check
    assert isinstance(checkbox, WrappedCheckBox)
    window._show_workspace("study")
    settle(app)
    original_text = checkbox.text()
    signals = []
    checkbox.toggled.connect(signals.append)
    # Click the far end of the wrapping caption, beyond the native indicator.
    QTest.mouseClick(checkbox, Qt.LeftButton, pos=QPoint(checkbox.width() - 5, 8))
    assert checkbox.isChecked() and signals == [True]
    checkbox.setFocus()
    QTest.keyClick(checkbox, Qt.Key_Space)
    assert not checkbox.isChecked() and signals == [True, False]
    checkbox.setText(original_text + " — reviewed")
    assert checkbox.text().endswith(" — reviewed")
    assert checkbox._caption.text() == checkbox.text()


def test_project_units_refresh_headers_without_editing_engineering_values(desktop):
    app, window = desktop
    window._add_table_row("Small offset", 0.000000123456789, 0.00000001, 0.00000002, "+", None)
    cell = window.table.item(0, 0)
    cell.setData(Qt.UserRole, "stable-dimension")
    before = window.table.model().rows_snapshot()
    changed = QSignalSpy(window.table.model().dataChanged)
    window.project.units = Units(length="in")
    window._project_update_title()
    settle(app)
    assert "length: in" in window.project_units_label.text()
    for column in (1, 2, 3, 6):
        assert "[in]" in window.table.model().headerData(column, Qt.Horizontal)
    assert "[in]" in window.acceptance_min_label.text()
    assert "[in]" in window.acceptance_max_label.text()
    assert window.table.model().rows_snapshot() == before
    assert window.table.item(0, 0).data(Qt.UserRole) == "stable-dimension"
    assert changed.count() == 0
    window.new_project()
    assert "length: mm" in window.project_units_label.text()
    assert "[mm]" in window.table.model().headerData(1, Qt.Horizontal)


def test_stack_analysis_actions_have_explicit_scope_and_preserve_other_workspaces(desktop, monkeypatch):
    app, window = desktop
    calls = []
    monkeypatch.setattr(window, "run_analysis", lambda: calls.append(window.method_combo.currentText()))
    window.method_combo.setCurrentText("monte_carlo")
    for name in ("inspect", "gdt", "study", "eclipse", "measure", "library"):
        window._show_workspace(name)
        settle(app)
        assert not window.stack_analyze_button.isVisible()
        assert not window.results_analyze_button.isVisible()
    window._show_workspace("stack")
    settle(app)
    assert window.stack_analyze_button.isVisible()
    assert "Monte Carlo" in window.stack_analyze_button.accessibleName()
    QTest.mouseClick(window.stack_analyze_button, Qt.LeftButton)
    settle(app)
    assert calls == ["monte_carlo"]
    assert window.sidebar.currentWidget() is window.results_tab
    assert window.results_analyze_button.isVisible()
    QTest.mouseClick(window.results_analyze_button, Qt.LeftButton)
    assert calls == ["monte_carlo", "monte_carlo"]


def test_viewport_status_details_stay_reachable_in_the_actual_window(desktop):
    app, window = desktop
    window.resize(1024, 768)
    window._show_workspace("stack")
    message = "Loaded: part.step\nSolids: 2  Faces: 18\nReview saved CAD links before evaluation."
    window.step_status_label.setText(message)
    window.step_load_progress.setVisible(True)
    settle(app)
    assert window.step_status_label.details_button.isVisible()
    assert window.step_status_label.summary_label.text()
    assert window.step_load_progress.geometry().right() < window.step_load_progress.parentWidget().width()
    QTest.mouseClick(window.step_status_label.details_button, Qt.LeftButton)
    settle(app)
    assert window.step_status_label._details_text.toPlainText() == message
    assert window.step_status_label.text() == message
    window.step_status_label._details_dialog.close()
