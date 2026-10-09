"""Small layout helpers that keep engineering controls readable in narrow panes."""

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtWidgets import (
    QCheckBox, QGridLayout, QLabel, QSizePolicy, QStyle, QStyleOptionButton,
    QStylePainter, QVBoxLayout, QWidget,
)


def wrap_label(label):
    """Let a label wrap at the available width instead of widening its page."""
    label.setWordWrap(True)
    label.setMinimumWidth(0)
    policy = QSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    policy.setHeightForWidth(True)
    label.setSizePolicy(policy)
    return label


class WrappedCheckBox(QCheckBox):
    """A normal checkbox with wrapping text and an unchanged text/signal API."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._caption = QLabel(text, self)
        self._caption.setWordWrap(True)
        self._caption.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._caption.setAttribute(Qt.WA_TransparentForMouseEvents)
        policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def setText(self, text):
        super().setText(text)
        if hasattr(self, "_caption"):
            self._caption.setText(text)
            self.updateGeometry()
            self._place_caption()

    def _caption_offset(self):
        return self.style().pixelMetric(QStyle.PM_IndicatorWidth, None, self) + 9

    def heightForWidth(self, width):
        caption_width = max(1, width - self._caption_offset())
        return max(
            self.style().pixelMetric(QStyle.PM_IndicatorHeight, None, self),
            self._caption.heightForWidth(caption_width), self.fontMetrics().height(),
        ) + 4

    def sizeHint(self):
        return QSize(280, self.heightForWidth(280))

    def minimumSizeHint(self):
        return QSize(100, self.fontMetrics().height() + 4)

    def _place_caption(self):
        offset = self._caption_offset()
        self._caption.setGeometry(offset, 2, max(0, self.width() - offset), max(0, self.height() - 2))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_caption()

    def hitButton(self, position):
        return self.rect().contains(position)

    def paintEvent(self, event):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.text = ""
        option.rect = QRect(0, 0, self.width(), self.fontMetrics().height() + 4)
        painter = QStylePainter(self)
        painter.drawControl(QStyle.CE_CheckBox, option)


class ResponsiveFieldGrid(QWidget):
    """Put labels above their existing editors, reflowing only their layout."""

    def __init__(self, parent=None, *, max_columns=2):
        super().__init__(parent)
        self._fields = []
        self._columns = 0
        self._max_columns = max_columns
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(12)
        self._grid.setVerticalSpacing(10)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def add_field(self, caption, editor):
        field = QWidget()
        layout = QVBoxLayout(field)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        label = wrap_label(QLabel(caption))
        label.setProperty("role", "muted")
        label.setBuddy(editor)
        editor.setMinimumWidth(0)
        editor.setMaximumWidth(16777215)
        editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(label)
        layout.addWidget(editor)
        self._fields.append(field)
        self._reflow(force=True)
        return label

    def _reflow(self, *, force=False):
        # Keep four related values in balanced pairs until all four fit.
        # An intermediate three-column layout would strand Cpk on its own row.
        if self._max_columns >= 4 and self.width() >= 636:
            columns = 4
        else:
            columns = min(self._max_columns, 2 if self.width() >= 280 else 1)
        if columns == self._columns and not force:
            return
        old_columns = self._columns
        self._columns = columns
        for field in self._fields:
            self._grid.removeWidget(field)
        for column in range(max(old_columns, columns)):
            self._grid.setColumnStretch(column, 1 if column < columns else 0)
        for index, field in enumerate(self._fields):
            self._grid.addWidget(field, index // columns, index % columns)
        self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()
