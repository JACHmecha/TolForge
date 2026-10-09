"""Layout changes must preserve engineering state and manual workspace sizing."""

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea

from gui.app import TolstackWindow
from gui.layout_presentation import WrappedCheckBox


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
