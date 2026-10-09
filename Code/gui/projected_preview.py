"""Interactive nominal cross-section for circular projected interference."""

import math

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import (
    QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)

from tolstack.eclipse import eclipse_fraction
from tolstack.models import finite_number
from tolstack.projected_interference import pin_outside_fraction, radial_clearance
from gui.theme import COLORS


class CrossSectionView(QGraphicsView):
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setMinimumHeight(280)
        self.setBackgroundBrush(QColor(COLORS["panel"]))
        self.setObjectName("crossSectionView")
        self._zoom_steps = 0

    def zoom(self, steps):
        target = max(-8, min(12, self._zoom_steps + steps))
        self.scale(1.2 ** (target - self._zoom_steps), 1.2 ** (target - self._zoom_steps))
        self._zoom_steps = target

    def wheelEvent(self, event):
        self.zoom(1 if event.angleDelta().y() > 0 else -1)
        event.accept()

    def fit_geometry(self):
        self._zoom_steps = 0
        self.resetTransform()
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._zoom_steps == 0:
            self.fit_geometry()


class ProjectedPreview(QWidget):
    """Draw circles to scale, with pan, zoom and an explicit nominal summary."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        toolbar = QHBoxLayout()
        title = QLabel("Nominal cross-section")
        title.setStyleSheet("font-weight: bold;")
        toolbar.addWidget(title, stretch=1)
        self.scene = QGraphicsScene(self)
        self.view = CrossSectionView(self.scene, self)
        for label, action in (("−", lambda: self.view.zoom(-1)), ("+", lambda: self.view.zoom(1)),
                              ("Fit", self.view.fit_geometry)):
            button = QPushButton(label)
            button.setMaximumWidth(55)
            button.clicked.connect(action)
            toolbar.addWidget(button)
        layout.addLayout(toolbar)
        layout.addWidget(self.view)
        self.legend = QLabel()
        self.legend.setWordWrap(True)
        layout.addWidget(self.legend)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setProperty("role", "muted")
        layout.addWidget(self.summary)
        self.valid = False
        self.overlap_path = QPainterPath()
        self.outside_path = QPainterPath()
        self.clear()

    def clear(self, message="Enter positive diameters and finite offsets to preview."):
        self.scene.clear()
        self.valid = False
        self.overlap_path = QPainterPath()
        self.outside_path = QPainterPath()
        self.legend.setText("Drag to pan · Scroll or use +/− to zoom · Fit to reset")
        self.summary.setText(message)

    @staticmethod
    def _pen(color, dashed=False):
        pen = QPen(QColor(color))
        pen.setCosmetic(True)
        pen.setWidthF(1.5)
        if dashed:
            pen.setStyle(Qt.DashLine)
        return pen

    def set_geometry(self, diameter_a, diameter_b, offset_x, offset_y, mode, units):
        try:
            da, db, dx, dy = [finite_number(value, "Preview length")
                              for value in (diameter_a, diameter_b, offset_x, offset_y)]
            if da <= 0 or db <= 0:
                raise ValueError("Enter positive diameters to preview.")
            distance = finite_number(math.hypot(dx, dy), "Preview offset")
            clearance = radial_clearance(da, db, distance)
            loss = pin_outside_fraction(da / 2, db / 2, distance) if mode == "hole-pin" else eclipse_fraction(da / 2, db / 2, distance)
        except ValueError as exc:
            self.clear(str(exc))
            return
        self.scene.clear()
        self.valid = True
        # Normalize Qt coordinates before drawing very large/small input units.
        scale = max(da, db, abs(dx), abs(dy))
        ra, rb, bx, by = da / scale / 2, db / scale / 2, dx / scale, -dy / scale
        first = QPainterPath()
        second = QPainterPath()
        first.addEllipse(QRectF(-ra, -ra, 2 * ra, 2 * ra))
        second.addEllipse(QRectF(bx - rb, by - rb, 2 * rb, 2 * rb))
        # Qt's path boolean flattening has an absolute curve tolerance. Work
        # at a larger bounded scale, then map back to the normalized scene.
        path_scale = QTransform.fromScale(1000, 1000)
        path_unscale = QTransform.fromScale(.001, .001)
        large_first, large_second = path_scale.map(first), path_scale.map(second)
        self.overlap_path = path_unscale.map(large_first.intersected(large_second))
        self.outside_path = path_unscale.map(large_second.subtracted(large_first))
        no_pen = QPen(Qt.NoPen)
        self.scene.addPath(first, no_pen, QBrush(QColor("#3071B6DF")))
        self.scene.addPath(second, no_pen, QBrush(QColor("#30FFAE5C")))
        shaded = self.outside_path if mode == "hole-pin" else self.overlap_path
        self.scene.addPath(shaded, no_pen, QBrush(QColor("#D56868") if mode == "hole-pin" else QColor("#67B58A")))
        self.scene.addPath(first, self._pen(COLORS["accent"]))
        self.scene.addPath(second, self._pen(COLORS["selection"]))
        self.scene.addLine(0, 0, bx, by, self._pen(COLORS["muted"], dashed=True))
        tick = .025
        for x, y in ((0, 0), (bx, by)):
            self.scene.addLine(x - tick, y, x + tick, y, self._pen(COLORS["text"]))
            self.scene.addLine(x, y - tick, x, y + tick, self._pen(COLORS["text"]))
        bounds = first.boundingRect().united(second.boundingRect())
        margin = .12 * max(bounds.width(), bounds.height()) + tick
        self.scene.setSceneRect(bounds.adjusted(-margin, -margin, margin, margin))
        self.view.fit_geometry()
        if mode == "hole-pin":
            self.legend.setText("Blue: hole · Orange: pin · Red: pin area outside hole · Dashed: center offset")
            state = "gap" if clearance > 0 else "contact" if clearance == 0 else "interference"
            self.summary.setText(f"Nominal: {loss * 100:.3g}% pin area outside · Radial clearance {clearance:+.6g} {units} ({state}) · X {dx:+.6g}, Y {dy:+.6g} {units}. Positive Y is up. Drag to pan; scroll to zoom.")
        else:
            self.legend.setText("Blue: hole A · Orange: hole B · Green: common opening · Dashed: center offset")
            self.summary.setText(f"Nominal: {loss * 100:.3g}% aperture loss · Center offset {distance:.6g} {units} · X {dx:+.6g}, Y {dy:+.6g} {units}. Positive Y is up. Drag to pan; scroll to zoom.")
