"""Shared nominal-relative surface preview geometry and controls.

Faces are translated along a fitted plane normal, not inflated along local
vertex normals. This is a visualization of a linear tolerance, not a CAD
surface-offset operation or a collision test.
"""

import numpy as np
from compas.colors import Color
from compas.geometry import Polyline
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QDoubleSpinBox,
    QCheckBox, QPushButton,
)

SLIDER_STEPS = 1000


def tolerance_limits(plus, minus):
    plus, minus = float(plus), float(minus)
    if not np.isfinite([plus, minus]).all() or min(plus, minus) < 0:
        raise ValueError("Tolerances must be finite, non-negative numbers.")
    return -minus, plus


def surface_normal(info):
    """Return a stable fitted axis; reject data with no usable plane."""
    circle = info.get("circle")
    if info.get("type") == "edge" and circle is not None:
        normal = np.asarray(circle["normal"], dtype=float)
    else:
        points = np.asarray(info["points"], dtype=float)
        if len(points) < 3 or not np.isfinite(points).all():
            raise ValueError("Select a surface with at least three finite points.")
        _, singular, axes = np.linalg.svd(points - points.mean(axis=0), full_matrices=False)
        if singular[1] <= max(singular[0], 1.0) * 1e-12:
            raise ValueError("A surface normal cannot be determined from collinear points.")
        normal = axes[-1]
    length = np.linalg.norm(normal)
    if not np.isfinite(length) or length <= 1e-12:
        raise ValueError("The selected feature has no usable normal.")
    normal = normal / length
    # SVD signs are arbitrary. Choose a reproducible hemisphere; users can flip it.
    if normal[np.argmax(np.abs(normal))] < 0:
        normal = -normal
    return normal


def translated_points(info, distance, normal=None):
    normal = surface_normal(info) if normal is None else np.asarray(normal, dtype=float)
    length = np.linalg.norm(normal)
    if not np.isfinite(distance) or not np.isfinite(length) or length <= 1e-12:
        raise ValueError("Offset and surface direction must be finite.")
    return np.asarray(info["points"], dtype=float) + normal / length * distance


def refresh_renderer(renderer):
    renderer.makeCurrent()
    try:
        renderer.rebuild_buffers()
    finally:
        renderer.doneCurrent()
    renderer.update()


def replace_preview(renderer, old_objects, info, layers, opacity=0.4):
    """Build all layers before replacing the previous preview.

    Each layer is (name, point array, color, is_limit). Never modify the
    source mesh, or leave a partial set of objects after a failed addition.
    """
    objects = []
    try:
        for name, points, color, is_limit in layers:
            color = Color.from_hex(color)
            if info["type"] == "face" and info.get("mesh") is not None:
                mesh = info["mesh"].copy()
                keys = list(mesh.vertices())
                if len(keys) != len(points):
                    raise ValueError("Surface mesh and preview points do not match.")
                for key, xyz in zip(keys, points):
                    mesh.vertex_attributes(key, "xyz", list(xyz))
                obj = renderer.scene.add(
                    mesh, name=name, show_faces=True, show_lines=True,
                    facecolor=color, linecolor=color,
                    opacity=opacity * (0.5 if is_limit else 1.0),
                )
            else:
                obj = renderer.scene.add(
                    Polyline(np.asarray(points).tolist()), name=name,
                    linecolor=color, linewidth=2 if is_limit else 3,
                    opacity=opacity,
                )
            objects.append(obj)
    except Exception:
        for obj in objects:
            renderer.scene.remove(obj)
        raise
    for obj in old_objects:
        renderer.scene.remove(obj)
    old_objects.clear()
    try:
        refresh_renderer(renderer)
    except Exception:
        for obj in objects:
            renderer.scene.remove(obj)
        raise
    return objects


def offset_layers(info, value, lower, upper, normal=None, show_limits=True):
    layers = []
    if show_limits:
        if not np.isclose(lower, value, rtol=0, atol=1e-12):
            layers.append(("Lower tolerance", translated_points(info, lower, normal), "#71B6DF", True))
        if upper != lower and not np.isclose(upper, value, rtol=0, atol=1e-12):
            layers.append(("Upper tolerance", translated_points(info, upper, normal), "#B59BFF", True))
    layers.append(("Current offset", translated_points(info, value, normal), "#FFAE5C", False))
    return layers


class OffsetControls(QFrame):
    """Same nominal-relative interaction for measurement and linked rows."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("surface", "card")
        self._syncing = False
        self._lower, self._upper = 0.0, 0.0
        layout = QVBoxLayout(self)
        self.title = QLabel("Surface offset")
        layout.addWidget(self.title)
        row = QHBoxLayout()
        row.addWidget(QLabel("From nominal"))
        self.distance = QDoubleSpinBox()
        self.distance.setDecimals(6)
        self.distance.setSingleStep(0.01)
        row.addWidget(self.distance, 1)
        reset = QPushButton("Reset")
        reset.clicked.connect(lambda: self.distance.setValue(0.0))
        row.addWidget(reset)
        layout.addLayout(row)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, SLIDER_STEPS)
        layout.addWidget(self.slider)
        self.range_label = QLabel()
        self.range_label.setProperty("role", "muted")
        layout.addWidget(self.range_label)
        options = QHBoxLayout()
        self.reverse = QCheckBox("Reverse direction")
        self.limits = QCheckBox("Show limits")
        self.limits.setChecked(True)
        options.addWidget(self.reverse)
        options.addWidget(self.limits)
        layout.addLayout(options)
        legend = QLabel("Orange: current · Blue: lower · Violet: upper")
        legend.setWordWrap(True)
        legend.setProperty("role", "muted")
        layout.addWidget(legend)
        self.slider.valueChanged.connect(self._slide)
        self.distance.valueChanged.connect(self._spin)
        self.reverse.toggled.connect(self.changed)
        self.limits.toggled.connect(self.changed)
        self.configure(0, 0)

    def configure(self, plus, minus, value=None, units="mm"):
        lower, upper = tolerance_limits(plus, minus)
        self._syncing = True
        try:
            self._lower, self._upper = lower, upper
            self.distance.setSuffix(f" {units}")
            self.distance.setRange(lower, upper)
            if value is not None:
                self.distance.setValue(value)
            span = upper - lower
            self.slider.setEnabled(span > 0)
            self.slider.setValue(round((self.distance.value() - lower) / span * SLIDER_STEPS) if span else 0)
            self.range_label.setText(f"Lower {lower:+.4f} · Nominal 0 · Upper {upper:+.4f} {units}")
        finally:
            self._syncing = False

    def _slide(self, position):
        if not self._syncing:
            self.distance.setValue(self._lower + position / SLIDER_STEPS * (self._upper - self._lower))

    def _spin(self, value):
        if self._syncing:
            return
        self.configure(self._upper, -self._lower, value, self.distance.suffix().strip())
        self.changed.emit()

    @property
    def direction(self):
        return -1 if self.reverse.isChecked() else 1
