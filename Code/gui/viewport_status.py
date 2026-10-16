"""Compact viewport status with a readable, copyable full-message view."""

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QTextOption
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPlainTextEdit,
    QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)


class ViewportStatus(QWidget):
    """Keep the QLabel text API while letting long status messages be inspected.

    ``text()`` returns the original message, including line breaks. Only the
    visible summary is elided; the details view never parses message markup.
    """

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._text = ""
        self._details_dialog = None
        self._details_text = None
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAccessibleName("Viewport status")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.summary_label = QLabel()
        self.summary_label.setTextFormat(Qt.PlainText)
        self.summary_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.summary_label.setProperty("role", "status")
        self.summary_label.setMinimumWidth(0)
        self.summary_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        layout.addWidget(self.summary_label, stretch=1)

        self.details_button = QToolButton()
        self.details_button.setText("&Details…")
        self.details_button.setAccessibleName("Show full viewport status")
        self.details_button.setToolTip("Read and copy the complete viewport status")
        self.details_button.setFocusPolicy(Qt.StrongFocus)
        self.details_button.clicked.connect(self.show_details)
        layout.addWidget(self.details_button)
        self.setText(text)

    def setText(self, text):
        """Replace the status without discarding the full engineering message."""
        self._text = text
        self.setAccessibleDescription(text)
        self.summary_label.setAccessibleName(text)
        if self._details_text is not None:
            self._details_text.setPlainText(text)
        self._refresh_summary()

    def text(self):
        return self._text

    def minimumSizeHint(self):
        # Filenames and backend diagnostics must never widen the 3D column.
        return QSize(0, self.sizeHint().height())

    def _refresh_summary(self):
        lines = self._text.splitlines()
        summary = next((line.strip() for line in lines if line.strip()), "")
        available = self.contentsRect().width()
        metrics = self.summary_label.fontMetrics()
        needs_details = len(lines) > 1 or metrics.horizontalAdvance(summary) > available
        # Keep the active trigger available while its window owns focus, even
        # if a worker replaces the message with a shorter one in the meantime.
        if self._details_dialog is not None and self._details_dialog.isVisible():
            needs_details = True
        self.details_button.setVisible(needs_details)
        if needs_details:
            available -= self.details_button.sizeHint().width() + self.layout().spacing()
        self.summary_label.setText(metrics.elidedText(summary, Qt.ElideRight, max(0, available)))

    def show_details(self):
        """Open a bounded nonmodal view without resizing or covering the layout."""
        if self._details_dialog is None:
            dialog = QDialog(self)
            dialog.setWindowTitle("Viewport status details")
            dialog.setWindowModality(Qt.NonModal)
            dialog.setAccessibleName("Viewport status details")
            layout = QVBoxLayout(dialog)
            self._details_text = QPlainTextEdit()
            self._details_text.setReadOnly(True)
            self._details_text.setLineWrapMode(QPlainTextEdit.WidgetWidth)
            self._details_text.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
            self._details_text.setAccessibleName("Complete viewport status")
            layout.addWidget(self._details_text)
            buttons = QDialogButtonBox(QDialogButtonBox.Close)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            dialog.finished.connect(self._details_closed)
            self._details_dialog = dialog

        self._details_text.setPlainText(self._text)
        screen = self.screen().availableGeometry()
        owner = self.window()
        width = min(680, max(280, int(owner.width() * 0.65)), max(1, screen.width() - 32))
        height = min(360, max(180, int(owner.height() * 0.45)), max(1, screen.height() - 32))
        self._details_dialog.resize(width, height)
        self._details_dialog.show()
        self._details_dialog.raise_()
        self._details_dialog.activateWindow()
        self._details_text.setFocus()
        self._refresh_summary()

    def _details_closed(self):
        # The trigger remains visible until the next message or resize, so
        # keyboard users return to a useful control after Escape or Close.
        self.window().activateWindow()
        self.details_button.setFocus(Qt.OtherFocusReason)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_summary()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.FontChange, QEvent.StyleChange) and hasattr(self, "summary_label"):
            self._refresh_summary()
