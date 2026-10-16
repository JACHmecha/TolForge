"""Long CAD diagnostics stay readable without expanding the viewport strip."""

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QHBoxLayout, QProgressBar, QWidget

from gui.theme import apply_window_theme
from gui.viewport_status import ViewportStatus


@pytest.fixture
def status_bar():
    app = QApplication.instance() or QApplication([])
    font_ids = []
    if not QFontDatabase.families():
        for name in ("segoeui.ttf", "segoeuib.ttf"):
            path = Path("C:/Windows/Fonts") / name
            if path.exists():
                font_ids.append(QFontDatabase.addApplicationFont(str(path)))
    host = QWidget()
    layout = QHBoxLayout(host)
    layout.setContentsMargins(4, 2, 4, 2)
    status = ViewportStatus("Ready")
    progress = QProgressBar()
    progress.setFixedWidth(145)
    layout.addWidget(status, stretch=1)
    layout.addWidget(progress)
    apply_window_theme(host)
    host.resize(320, 32)
    host.show()
    settle(app)
    yield app, host, status
    host.close()
    app.processEvents()
    for font_id in font_ids:
        QFontDatabase.removeApplicationFont(font_id)


def settle(app):
    for _ in range(4):
        app.processEvents()


def test_multiline_status_preserves_plain_text_and_keyboard_details(status_bar):
    app, host, status = status_bar
    message = "Warning: saved CAD links need review.\n<b>Part</b> at C:/CAD/project.step\nMissing Face #12"
    status.setText(message)
    settle(app)
    assert status.text() == message
    assert status.details_button.isVisible()
    assert status.summary_label.textFormat() == Qt.PlainText
    assert "\n" not in status.summary_label.text()
    status.details_button.setFocus()
    QTest.keyClick(status.details_button, Qt.Key_Space)
    settle(app)
    dialog = status._details_dialog
    assert dialog.isVisible() and not dialog.isModal()
    assert status._details_text.toPlainText() == message
    assert status._details_text.isReadOnly()
    assert dialog.height() <= 360
    QTest.keyClick(status._details_text, Qt.Key_A, Qt.ControlModifier)
    assert status._details_text.textCursor().selectedText().replace("\u2029", "\n") == message
    QTest.keyClick(status._details_text, Qt.Key_Escape)
    settle(app)
    assert not dialog.isVisible()
    assert status.details_button.hasFocus()


def test_single_line_overflow_is_accessible_at_narrow_width_with_progress(status_bar):
    app, host, status = status_bar
    message = "Failed to load " + "a-long-engineering-project-name-" * 12 + ".step"
    status.setText(message)
    settle(app)
    assert host.width() == 320
    assert status.minimumSizeHint().width() == 0
    assert status.details_button.isVisible()
    assert status.details_button.width() >= status.details_button.sizeHint().width()
    status.details_button.click()
    settle(app)
    assert status._details_text.toPlainText() == message
    assert status._details_text.horizontalScrollBar().maximum() == 0
    assert status._details_text.verticalScrollBar().maximum() > 0
    status._details_dialog.close()


def test_open_details_follow_new_status_without_reopening(status_bar):
    app, host, status = status_bar
    status.setText("CAD source unavailable.\nLocate the project source to reconnect saved dimensions.")
    status.details_button.click()
    settle(app)
    dialog = status._details_dialog
    status.setText("Loading selected source…")
    settle(app)
    assert status._details_dialog is dialog and dialog.isVisible()
    assert status._details_text.toPlainText() == "Loading selected source…"
    assert status.text() == "Loading selected source…"
    assert status.details_button.isVisible()
    dialog.close()


def test_summary_reflows_on_resize_and_hides_details_when_full_message_fits(status_bar):
    app, host, status = status_bar
    message = "Geometry loaded; review the saved feature links."
    status.setText(message)
    settle(app)
    assert status.details_button.isVisible()
    host.resize(1000, 32)
    settle(app)
    assert not status.details_button.isVisible()
    assert status.summary_label.text() == message
