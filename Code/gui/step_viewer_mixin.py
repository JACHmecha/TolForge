"""Mixin providing STEP file loading, 3D preview, and face/edge/vertex
selection for TolstackWindow.

Split out of app.py because this is the single most intricate part of the
whole GUI - full of hard-won fixes for compas_viewer quirks (the shared
Viewer singleton, initializeGL only ever running once, the QApplication
creation race, etc.) - and keeping it in its own file makes it possible to
work on the STEP preview without wading through unrelated dimension-table
and analysis code.
"""

from pathlib import Path

from PySide6.QtWidgets import QApplication, QFileDialog, QLabel
from PySide6.QtCore import Qt

from compas.colors import Color

from .step_renderer import Renderer, detect_step_backend


class StepViewerMixin:
    """Expects the host class (TolstackWindow) to provide, from its own
    __init__: self.step_status_label, self.step_preview_layout,
    self._step_preview_renderer, self._step_entity_info.
    """

    def load_step_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load STEP file", "", "STEP files (*.step *.stp)"
        )
        if not path:
            return

        backend_name, backend_message = detect_step_backend()
        self.step_status_label.setText(
            f"Selected: {Path(path).name}\n{backend_message}"
        )

        if backend_name is None:
            self._show_step_preview_placeholder(
                "The STEP file was selected, but a compatible CAD backend is not available in this environment."
            )
            return

        self._render_step_geometry(path)

    def clear_step_preview(self):
        """Clear the loaded geometry but keep the 3D viewport itself visible
        and ready - it's initialized once at startup, not recreated here."""
        self.step_status_label.setText("No STEP file loaded yet.")
        if self._step_preview_renderer is not None:
            scene = self._step_preview_renderer.scene
            for obj in list(scene.objects):
                scene.remove(obj)
            self._step_entity_info = {}
            self._step_preview_renderer.update()
            QApplication.processEvents()
        else:
            self._show_step_preview_placeholder()

    def _init_step_preview_renderer(self):
        """Create and fully initialize the 3D viewport once, at app startup,
        rather than only when the first STEP file is loaded.

        This also happens to fix a real timing bug: creating the Renderer
        widget for the first time immediately after a modal QFileDialog
        closes (which is when the first STEP load used to happen) raced
        against Qt/Windows still finishing that dialog's focus transition,
        and the widget's native GL surface sometimes wouldn't be ready in
        time - only the very first load ever hit this, since by the second
        load the container already had a native window handle from before.
        Creating it once here, well before any file dialog ever opens,
        sidesteps that race entirely.
        """
        if Renderer is None:
            self._show_step_preview_placeholder(
                "The COMPAS viewer renderer is not available in this environment."
            )
            return

        try:
            self._step_preview_renderer = Renderer()
            self._step_preview_renderer.setMinimumHeight(220)
            self._step_preview_renderer.setMinimumWidth(220)
            self._step_preview_renderer.on_pick = self._on_step_entity_picked
            self.step_preview_layout.addWidget(self._step_preview_renderer)
            self._step_preview_renderer.show()
            QApplication.processEvents()
        except Exception as exc:  # pragma: no cover - runtime environment specific
            self._step_preview_renderer = None
            self._show_step_preview_placeholder(f"Could not initialize the 3D viewport: {exc}")

    def _show_step_preview_placeholder(self, message: str | None = None):
        self._clear_step_preview_widget()
        placeholder = QLabel(message or "Use the button above to preview a STEP file.")
        placeholder.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        placeholder.setWordWrap(True)
        placeholder.setStyleSheet("color: #666666;")
        self.step_preview_layout.addWidget(placeholder)

    def _clear_step_preview_widget(self):
        layout = self.step_preview_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _zoom_to_fit(self, renderer):
        """Frame the camera around everything currently in the scene.

        The standalone compas_viewer app binds this behavior to the 'F' key
        via its zoom_selected command, but our embedded Renderer widget
        doesn't inherit that app-level keybinding wiring - the camera stays
        at whatever default position/scale was set for the very first
        object ever added (the old placeholder box), which is far too
        zoomed-in for a real, larger STEP part. This mirrors compas_viewer's
        own zoom_selected implementation (compas_viewer.commands) directly,
        since that's the library's own proven bounding-box-fit logic.
        """
        import numpy as np

        objects = list(renderer.scene.objects)
        extents = []
        for obj in objects:
            try:
                if getattr(obj, "bounding_box", None) is not None:
                    obj._update_bounding_box()
                    if obj.bounding_box is not None:
                        extents.append(obj.bounding_box)
            except AttributeError:
                # Object hasn't been GL-initialized yet (init() populates
                # the internal data _update_bounding_box needs) - skip it,
                # rather than crash the whole zoom-to-fit for one race.
                continue

        if not extents:
            return

        extents = np.array(extents).reshape(-1, 3)
        max_corner = extents.max(axis=0)
        min_corner = extents.min(axis=0)
        center = (max_corner + min_corner) / 2
        diagonal = max(float(np.linalg.norm(max_corner - min_corner)), 1.0)

        camera = renderer.camera
        camera.scale = diagonal / 10  # matches compas_viewer's own tuned constant
        camera.target = center

        direction = np.array(camera.target) - np.array(camera.position)
        direction_norm = np.linalg.norm(direction)
        if direction_norm == 0:
            direction = np.array([1.0, 1.0, 1.0])
            direction_norm = np.linalg.norm(direction)
        unit_vector = direction / direction_norm
        camera.position = np.array(camera.target) - unit_vector * diagonal

        renderer.update()

    def _render_step_geometry(self, path: str):
        """Load a STEP file via compas_occ and render it with individually
        selectable faces, edges, and vertices.

        Rather than adding one merged Mesh (which has no per-face boundaries
        once tessellated), each topological face/edge/vertex is added as its
        own scene object. compas_viewer's object-level click-selection can
        then distinguish which specific face/edge/vertex was clicked, since
        selection works by picking a whole SceneObject, not a sub-region of
        one big mesh.

        Reuses the Renderer widget created once at app startup
        (_init_step_preview_renderer) rather than destroying and recreating
        it here - both to avoid the GL-surface-creation race that used to
        break the very first load, and because a per-file failure (bad
        STEP data) shouldn't tear down an otherwise-working 3D viewport.
        """
        if self._step_preview_renderer is None:
            self._show_step_preview_placeholder(
                "The COMPAS viewer renderer is not available in this environment."
            )
            return

        try:
            from compas_occ.brep import OCCBrep
        except ImportError as exc:
            self.step_status_label.setText(f"compas_occ could not be imported: {exc}")
            return

        try:
            # heal=True fixes small gaps/discontinuities that are common in
            # STEP files exported from different CAD packages.
            brep = OCCBrep.from_step(path, heal=True)

            # Each face gets tessellated on its own (via a single-face
            # sub-Brep) so it becomes its own pickable object, rather than
            # part of one fused mesh with no face boundaries.
            face_meshes = []
            for face in brep.faces:
                face_brep = OCCBrep.from_brepfaces([face], solid=False)
                face_mesh, _unused_edges = face_brep.to_viewmesh()
                face_meshes.append(face_mesh)

            # The whole-Brep to_viewmesh() call also returns per-edge
            # polylines - reuse that instead of re-deriving edge geometry
            # by hand.
            _unused_mesh, edge_polylines = brep.to_viewmesh()

            vertex_points = [vertex.to_point() for vertex in brep.vertices]
        except Exception as exc:
            # Don't tear down the 3D viewport over one bad file - just
            # report it and leave whatever was already shown in place.
            self.step_status_label.setText(f"Failed to read/tessellate the STEP file: {exc}")
            return

        try:
            scene = self._step_preview_renderer.scene

            # IMPORTANT: `scene` here is actually a property that resolves
            # to the single Viewer-singleton-wide scene, shared across every
            # Renderer() we've ever constructed - not a fresh scene per
            # widget. Without explicitly clearing it, geometry from a
            # previously-loaded STEP file would keep accumulating invisibly
            # underneath whatever the current widget shows.
            for stale_obj in list(scene.objects):
                scene.remove(stale_obj)

            self._step_entity_info = {}

            face_color = Color.from_hex("#4c78a8")
            edge_color = Color.from_hex("#1f2d3d")
            vertex_color = Color.from_hex("#e45756")

            for i, face_mesh in enumerate(face_meshes):
                try:
                    obj = scene.add(
                        face_mesh, show_faces=True, show_lines=False, facecolor=face_color
                    )
                except TypeError:
                    obj = scene.add(face_mesh)
                if obj is not None:
                    self._step_entity_info[id(obj)] = {"type": "face", "index": i}

            for i, polyline in enumerate(edge_polylines):
                try:
                    obj = scene.add(polyline, linecolor=edge_color, linewidth=2)
                except TypeError:
                    obj = scene.add(polyline)
                if obj is not None:
                    self._step_entity_info[id(obj)] = {"type": "edge", "index": i}

            for i, point in enumerate(vertex_points):
                try:
                    obj = scene.add(point, pointcolor=vertex_color, pointsize=8)
                except TypeError:
                    obj = scene.add(point)
                if obj is not None:
                    self._step_entity_info[id(obj)] = {"type": "vertex", "index": i}

            # CRITICAL: initializeGL() already ran once, at app startup, when
            # _init_step_preview_renderer() first showed this widget with an
            # EMPTY scene - that's the only place obj.init() (which sets up
            # each object's GL buffers and bounding box) normally gets
            # called, and Qt never calls initializeGL() a second time. Since
            # we're adding geometry well after that point, nothing would
            # otherwise ever call .init() on these new objects - paint()
            # only draws from self.buffer_manager, which was built once
            # from whatever existed at initializeGL() time. rebuild_buffers()
            # is the method that checks for any object with obj._inited
            # still False and initializes it, then rebuilds the buffer data.
            self._step_preview_renderer.makeCurrent()
            self._step_preview_renderer.rebuild_buffers()
            self._step_preview_renderer.doneCurrent()

            # Force a real paint pass now that the geometry is in the scene.
            self._step_preview_renderer.update()
            QApplication.processEvents()

            self._zoom_to_fit(self._step_preview_renderer)
            self._step_preview_renderer.update()
            QApplication.processEvents()

            self.step_status_label.setText(
                f"Loaded: {Path(path).name}\n"
                f"Faces: {len(face_meshes)}  Edges: {len(edge_polylines)}  "
                f"Vertices: {len(vertex_points)}\n"
                "Left-click a face/edge/vertex to select it."
            )
        except Exception as exc:  # pragma: no cover - runtime environment specific
            self.step_status_label.setText(f"Could not display the STEP geometry: {exc}")

    def _on_step_entity_picked(self, obj):
        """Show info about whichever face/edge/vertex was just clicked."""
        info = self._step_entity_info.get(id(obj)) if obj is not None else None
        if info is None:
            self.step_status_label.setText("Selection cleared.")
            return

        kind = info["type"]
        idx = info["index"]
        if kind == "face":
            self.step_status_label.setText(f"Selected: Face #{idx}")
        elif kind == "edge":
            self.step_status_label.setText(f"Selected: Edge #{idx}")
        elif kind == "vertex":
            self.step_status_label.setText(f"Selected: Vertex #{idx}")
