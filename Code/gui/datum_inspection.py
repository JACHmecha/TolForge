"""Inspection graphics for the active datum reference frame."""

from copy import deepcopy

import numpy as np
from compas.colors import Color
from compas.geometry import Line, Point, Polyline

from .offset_preview import refresh_renderer

DATUM_STYLES = {
    "Primary": ("A", "#71D5EF"),
    "Secondary": ("B", "#BC9BFF"),
    "Tertiary": ("C", "#FFD279"),
}
AXIS_COLORS = ("#FF7474", "#67D39A", "#71B6FF")


def frame_axes(frame, length):
    """Use the exact frame used by inspection calculations, in world space."""
    origin = np.asarray(frame.origin, dtype=float)
    return [(name, origin, origin + np.asarray(axis) * length, color)
            for name, axis, color in zip("XYZ", (frame.x_axis, frame.y_axis, frame.z_axis), AXIS_COLORS)]


class DatumInspectionMixin:
    def _update_inspected_datum_label(self):
        feature_id = getattr(self, "_inspected_feature_id", None)
        names = [f"{DATUM_STYLES[slot][0]} ({slot.lower()})"
                 for slot, entry in self._datum_slot.items()
                 if entry is not None and feature_id is not None and entry["feature_id"] == feature_id]
        self.selection_datum_label.setText("Datum: " + (", ".join(names) if names else "—"))

    def _clear_datum_inspection(self):
        renderer = self._step_preview_renderer
        if renderer is not None:
            text_objects = [obj for obj in self._datum_visual_objects if hasattr(obj, "_text_buffer")]
            if text_objects:
                from OpenGL import GL
                renderer.makeCurrent()
                try:
                    for obj in text_objects:
                        buffers = obj._text_buffer
                        GL.glDeleteBuffers(2, [buffers["positions"], buffers["elements"]])
                        GL.glDeleteTextures([buffers["text_texture"]])
                finally:
                    renderer.doneCurrent()
            for obj in self._datum_visual_objects:
                renderer.scene.remove(obj)
                if hasattr(obj, "instance_color"):
                    renderer.scene.instance_colors.pop(obj.instance_color.rgb255, None)
            for obj, attribute, color in reversed(self._datum_original_colors):
                if hasattr(color, "default"):
                    setattr(obj, attribute, color.default)
                    getattr(obj, attribute).update(color)
                else:
                    setattr(obj, attribute, color)
            renderer.datum_inspection_objects = []
        self._datum_visual_objects = []
        self._datum_original_colors = []

    def _reset_datum_inspection(self):
        self._current_drf = None
        self._datum_arm = None
        self._pattern_arm = False
        self._datum_slot = dict.fromkeys(DATUM_STYLES)
        self._update_datum_labels()
        self.drf_status_label.setText("Datum reference frame not built yet.")

    def _refresh_datum_inspection(self, *_args):
        renderer = self._step_preview_renderer
        if renderer is None:
            return
        self._clear_datum_inspection()
        try:
            # Imported only when a renderer exists; labels face the camera.
            from compas_viewer.scene import Tag

            entries = []
            for slot, entry in self._datum_slot.items():
                if entry is not None:
                    info = self._project_find_entity_info(entry["feature_id"])
                    if info is not None:
                        entries.append((slot, entry, info))
            if not entries:
                refresh_renderer(renderer)
                return
            points = np.concatenate([np.asarray(info["points"], dtype=float) for _, _, info in entries])
            span = max(float(np.linalg.norm(np.ptp(points, axis=0))), 1e-6)
            length = span * 0.2 * self.datum_axis_scale.value() / 100

            def add(geometry, **options):
                obj = renderer.scene.add(geometry, **options)
                self._datum_visual_objects.append(obj)
                return obj

            def tag(text, point, color):
                obj = add(Tag(text, point, color=Color.from_hex(color), height=32), name=text)
                # The embedded renderer rebuilds geometry buffers, but COMPAS
                # text sprites have separate GL textures initialized explicitly.
                if hasattr(obj, "init"):
                    renderer.makeCurrent()
                    try:
                        obj.init()
                    finally:
                        renderer.doneCurrent()

            if self.show_datum_faces.isChecked():
                for slot, entry, info in entries:
                    letter, hex_color = DATUM_STYLES[slot]
                    color = Color.from_hex(hex_color)
                    # Color the actual pickable geometry, avoiding coplanar
                    # overlays that would flicker or intercept face selection.
                    for obj in renderer.scene.objects:
                        if self._step_entity_info.get(id(obj)) is info:
                            attribute = "facecolor" if info["type"] == "face" else "linecolor"
                            self._datum_original_colors.append((obj, attribute, deepcopy(getattr(obj, attribute))))
                            setattr(obj, attribute, color)
                    anchor = np.asarray(entry["point"], dtype=float)
                    direction = np.asarray(entry["direction"], dtype=float)
                    direction = direction / np.linalg.norm(direction)
                    if entry.get("kind") == "axis":
                        stations = (np.asarray(info["points"]) - anchor) @ direction
                        start = anchor + direction * (stations.min() - length * 0.3)
                        tip = anchor + direction * (stations.max() + length * 0.3)
                        add(Line(start, tip), linecolor=color, linewidth=3, name=f"Datum {letter} axis")
                        tag(f"[{letter}] axis", tip, hex_color)
                    else:
                        tip = anchor + direction * length * 0.65
                        add(Line(anchor, tip), linecolor=color, linewidth=2, name=f"Datum {letter} leader")
                        tag(f"[{letter}]", tip, hex_color)

            if self.show_datum_frame.isChecked() and self._current_drf is not None:
                origin = np.asarray(self._current_drf.origin)
                add(Point(*origin), pointcolor=Color.white(), pointsize=10, name="DRF origin")
                tag("O (0, 0, 0)", origin, "#FFFFFF")
                for name, start, end, hex_color in frame_axes(self._current_drf, length):
                    color = Color.from_hex(hex_color)
                    add(Line(start, end), linecolor=color, linewidth=3, name=f"DRF {name}")
                    unit = (end - start) / length
                    side = np.cross(unit, np.eye(3)[np.argmin(np.abs(unit))])
                    side /= np.linalg.norm(side)
                    add(Polyline([end - unit * length * 0.16 + side * length * 0.06,
                                  end, end - unit * length * 0.16 - side * length * 0.06]),
                        linecolor=color, linewidth=3, name=f"DRF {name} arrow")
                    tag(name, end + unit * length * 0.08, hex_color)
            renderer.datum_inspection_objects = list(self._datum_visual_objects)
            refresh_renderer(renderer)
        except Exception as exc:
            self._clear_datum_inspection()
            self.step_status_label.setText(f"Could not display datum inspection markers: {exc}")
