"""The embedded 3D viewport widget used for STEP preview, and backend
detection for the optional compas_occ/compas_viewer dependency.

Isolated in its own module because it has real, hard-won subtleties baked
into it - see the docstrings below - that have nothing to do with the rest
of the application and are easiest to reason about on their own.
"""

import importlib.util

try:
    from compas_viewer.renderer import Renderer as _BaseRenderer
    from PySide6.QtCore import Qt as _Qt

    class StepPreviewRenderer(_BaseRenderer):
        """A Renderer that handles its own mouse-drag camera control directly.

        compas_viewer's built-in mouse-drag commands (rotate_view, pan_view,
        zoom_view in compas_viewer.commands) all operate on
        `viewer.renderer.camera` - the ONE canonical Renderer that
        compas_viewer's own Viewport UI component creates for the standalone
        app (compas_viewer/components/viewport.py). They do not use `self`
        (whichever Renderer widget actually received the mouse event), so
        when we embed our own separate Renderer instances, dragging on them
        correctly triggers the command but it silently updates a different,
        never-shown camera - never ours. Confirmed by reading
        compas_viewer/commands.py directly rather than assuming.

        This subclass bypasses that system entirely for drag/zoom
        interaction and calls self.camera.rotate/pan/zoom directly, so the
        widget you're actually looking at responds to input on itself.

        Bindings: left-drag = rotate, right-drag (or shift+left-drag) = pan,
        scroll wheel = zoom. (compas_viewer's own defaults are right-drag =
        rotate and right+shift = pan; left-drag here intentionally matches
        the more common convention across CAD/3D tools instead.)
        """

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._drag_button = None
            self._last_pos = None
            self._dragged_distance = 0.0
            # Set by TolstackWindow after construction. Called with the
            # picked SceneObject (or None if empty space was clicked) when
            # a left-click (not a left-drag/rotate) is released.
            self.on_pick = None

        def mousePressEvent(self, event):
            self._drag_button = event.button()
            self._last_pos = event.position() if hasattr(event, "position") else event.pos()
            self._dragged_distance = 0.0

        def mouseMoveEvent(self, event):
            if self._last_pos is None or self._drag_button is None:
                return
            pos = event.position() if hasattr(event, "position") else event.pos()
            dx = pos.x() - self._last_pos.x()
            dy = pos.y() - self._last_pos.y()
            self._dragged_distance += (dx * dx + dy * dy) ** 0.5
            self._last_pos = pos

            shift_held = bool(event.modifiers() & _Qt.KeyboardModifier.ShiftModifier)
            if self._drag_button == _Qt.MouseButton.RightButton or (
                self._drag_button == _Qt.MouseButton.LeftButton and shift_held
            ):
                self.camera.pan(dx, dy)
            elif self._drag_button == _Qt.MouseButton.LeftButton:
                self.camera.rotate(dx, dy)
            self.update()

        def mouseReleaseEvent(self, event):
            # A left click with almost no movement is treated as a pick
            # (select face/edge/vertex) rather than the start of a rotate -
            # otherwise every rotate-drag would also fire a selection at
            # the release point, which isn't what a user expects.
            if self._drag_button == _Qt.MouseButton.LeftButton and self._dragged_distance < 4:
                pos = event.position() if hasattr(event, "position") else event.pos()
                self._handle_click_select(int(pos.x()), int(pos.y()))
            self._drag_button = None
            self._last_pos = None
            self._dragged_distance = 0.0

        def _handle_click_select(self, x, y):
            """Pick whichever scene object is under (x, y) using compas_viewer's
            own instance-color framebuffer technique - but calling
            self.read_instance_color(...) directly (this widget's own
            method, operating on its own framebuffer) rather than going
            through compas_viewer.commands.select_object, which hardcodes
            viewer.renderer and would read the wrong (invisible) widget's
            framebuffer instead of this one's, same issue as rotate/pan.
            """
            import numpy as np

            try:
                for obj in list(self.scene.instance_colors.values()):
                    obj.is_selected = False

                colors = self.read_instance_color((x, y, x, y))
                colors = np.array(colors).reshape(-1, np.array(colors).shape[-1])
                unique_colors = np.unique(colors, axis=0)

                selected = None
                for c in unique_colors:
                    key = tuple(int(v) for v in c)
                    candidate = self.scene.instance_colors.get(key)
                    if candidate is not None:
                        selected = candidate
                        break

                if selected is not None:
                    selected.is_selected = True
                self.update()

                if self.on_pick is not None:
                    self.on_pick(selected)
            except Exception:
                # Picking is a nice-to-have on top of viewing; a failure
                # here (e.g. an API detail that differs from what's
                # documented) shouldn't crash the whole preview.
                pass

        def wheelEvent(self, event):
            degrees = event.angleDelta().y() / 8
            steps = degrees / 15
            self.camera.zoom(steps)
            self.update()

    Renderer = StepPreviewRenderer
except Exception:  # pragma: no cover - optional dependency guard
    Renderer = None


def detect_step_backend() -> tuple[str | None, str]:
    """Return the optional CAD backend name and a user-facing status message.

    Only compas_occ is treated as "ready" here: it is the only one of these
    that returns COMPAS-native geometry (OCCBrep), which is what the embedded
    compas_viewer Renderer can add to its scene. The others may exist in the
    environment but would need a separate conversion path that isn't
    implemented, so we report them as detected-but-unsupported rather than
    silently pretending the preview will work.
    """
    if importlib.util.find_spec("compas_occ"):
        return "compas_occ", "Detected compas_occ (OpenCascade) backend for STEP preview."

    other_found = [m for m in ("OCP", "occ", "cadquery", "ifcopenshell") if importlib.util.find_spec(m)]
    if other_found:
        return None, (
            f"Found {', '.join(other_found)}, but STEP preview currently requires compas_occ "
            "specifically. Install it with: conda install -c conda-forge compas_occ"
        )

    return None, (
        "STEP preview requires the compas_occ backend (COMPAS's OpenCascade wrapper), which is "
        "not installed. Install it with: conda install -c conda-forge compas_occ"
    )
