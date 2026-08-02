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

import numpy as np

from PySide6.QtWidgets import QApplication, QFileDialog, QLabel
from PySide6.QtCore import Qt, QThread

from compas.colors import Color

from .step_renderer import Renderer, detect_step_backend
from .step_load_worker import StepLoadWorker

# Qualitative palette for coloring faces by which solid they belong to -
# cycles if there are more solids than colors. Chosen for mutual
# distinguishability (not a sequential/gradient palette) rather than for
# any particular aesthetic theme.
SOLID_COLOR_PALETTE = [
    "#4c78a8", "#f58518", "#54a24b", "#e45756", "#72b7b2",
    "#eeca3b", "#b279a2", "#ff9da6", "#9d755d", "#bab0ac",
]

_PICK_REJECTED = object()  # sentinel: this pick didn't match the active filter


class _SolidPickMarker:
    """Lightweight placeholder so a synthesized 'whole solid' selection
    (aggregating every face that shares one solid_index) can flow through
    the same id(obj)-keyed _step_entity_info lookup every pick-consumer
    (_measure_on_pick, _datum_on_pick, _on_step_entity_picked itself)
    already uses for individual face/edge/vertex picks - no separate code
    path needed in any of them for 'solid' selections.
    """

    __slots__ = ()


class StepViewerMixin:
    """Expects the host class (TolstackWindow) to provide, from its own
    __init__: self.step_status_label, self.step_preview_layout,
    self._step_preview_renderer, self._step_entity_info,
    self._step_load_thread (None), self._step_load_worker (None),
    self._step_load_generation (0), plus self.step_deflection_input (a
    QDoubleSpinBox for the tessellation quality/LOD setting) built in
    app.py.
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

        self._start_step_load(path)

    def clear_step_preview(self):
        """Clear the loaded geometry but keep the 3D viewport itself visible
        and ready - it's initialized once at startup, not recreated here."""
        self._step_load_generation += 1  # invalidate any in-flight background load
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
            self._step_preview_renderer.on_measure_context_menu = self._show_measure_context_menu
            self._step_preview_renderer.resolve_entity_info = self._resolve_entity_info_for_renderer
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

    def _start_step_load(self, path: str):
        """Kick off STEP parsing/tessellation on a background QThread.

        Only the OCCT/compas_occ work happens there (see
        StepLoadWorker) - it does no Qt/GL calls. Everything GL-related
        (scene.add, rebuild_buffers) still has to happen back on this,
        the main thread, once the worker hands its result back via a
        signal - that's _on_step_load_finished below.
        """
        if self._step_preview_renderer is None:
            self._show_step_preview_placeholder(
                "The COMPAS viewer renderer is not available in this environment."
            )
            return

        if self._step_load_thread is not None:
            self.step_status_label.setText(
                "A STEP file is already loading - please wait for it to finish."
            )
            return

        self._step_load_generation += 1
        generation = self._step_load_generation
        deflection = self.step_deflection_input.value()

        self.step_status_label.setText(f"Loading {Path(path).name} ...")
        QApplication.processEvents()

        thread = QThread(self)
        worker = StepLoadWorker(path, deflection)
        worker.moveToThread(thread)
        # Stash on the worker itself rather than capturing in a lambda -
        # see the note on connect() below for why.
        worker.generation = generation

        thread.started.connect(worker.run)
        # IMPORTANT: connect directly to bound methods of `self` (a
        # QObject living on the main thread), not to lambdas/partials.
        # Qt's AutoConnection only queues a cross-thread call onto the
        # receiver's thread when it can detect the receiver's thread
        # affinity - which it can for a QObject's bound method, but NOT
        # for a plain Python lambda/partial (no thread affiliation to
        # detect). With a lambda, AutoConnection silently falls back to
        # DirectConnection, so the slot - including our GL calls in
        # _on_step_load_finished - would run on the emitting (worker)
        # thread instead of the main thread, which is exactly what
        # produced "Cannot make QOpenGLContext current in a different
        # thread". Passing QueuedConnection explicitly here removes any
        # dependency on that auto-detection working correctly.
        worker.finished.connect(self._on_step_load_finished, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(self._on_step_load_failed, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._cleanup_step_load_thread)

        self._step_load_thread = thread
        self._step_load_worker = worker
        thread.start()

    def _on_step_load_failed(self, message: str):
        worker = self._step_load_worker
        if worker is None or worker.generation != self._step_load_generation:
            return  # superseded by a newer load or a clear_step_preview()
        self.step_status_label.setText(f"Failed to read/tessellate the STEP file: {message}")

    def _on_step_load_finished(self, result):
        """Runs on the main thread, now that the connect() above forces
        QueuedConnection - safe to touch the GL context here.
        """
        worker = self._step_load_worker
        if worker is None or worker.generation != self._step_load_generation:
            return  # superseded by a newer load or a clear_step_preview() in the meantime
        path = worker.path

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

            # Faces are colored per-solid (cycling through this palette) so
            # separate bodies in an assembly are easy to tell apart at a
            # glance. Edges/vertices stay a fixed neutral color regardless
            # of which solid they belong to - they aren't grouped by solid
            # the way faces are (see step_load_worker.py's
            # _group_faces_by_solid docstring for why), and keeping them
            # neutral also reads better visually as wireframe/point accents
            # against the colored, shaded faces.
            edge_color = Color.from_hex("#1f2d3d")
            vertex_color = Color.from_hex("#e45756")

            solid_palette = [
                Color.from_hex(hex_code) for hex_code in SOLID_COLOR_PALETTE
            ]

            for i, face_mesh in enumerate(result.face_meshes):
                solid_index = result.face_solid_indices[i] if i < len(result.face_solid_indices) else 0
                face_color = solid_palette[solid_index % len(solid_palette)]
                try:
                    obj = scene.add(
                        face_mesh, show_faces=True, show_lines=False, facecolor=face_color
                    )
                except TypeError:
                    obj = scene.add(face_mesh)
                if obj is not None:
                    points = np.array(
                        [face_mesh.vertex_attributes(vkey, "xyz") for vkey in face_mesh.vertices()],
                        dtype=float,
                    )
                    self._step_entity_info[id(obj)] = {
                        "type": "face", "index": i, "points": points, "mesh": face_mesh,
                        "solid_index": solid_index,
                    }

            for i, polyline in enumerate(result.edge_polylines):
                try:
                    obj = scene.add(polyline, linecolor=edge_color, linewidth=2)
                except TypeError:
                    obj = scene.add(polyline)
                if obj is not None:
                    points = np.array([[p.x, p.y, p.z] for p in polyline.points], dtype=float)
                    self._step_entity_info[id(obj)] = {"type": "edge", "index": i, "points": points}

            for i, point in enumerate(result.vertex_points):
                try:
                    obj = scene.add(point, pointcolor=vertex_color, pointsize=8)
                except TypeError:
                    obj = scene.add(point)
                if obj is not None:
                    points = np.array([[point.x, point.y, point.z]], dtype=float)
                    self._step_entity_info[id(obj)] = {"type": "vertex", "index": i, "points": points}

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

            lod_note = "" if worker.deflection_applied else " (quality setting not supported by this compas_occ version - used its default)"
            solid_count = len(set(result.face_solid_indices)) if result.face_solid_indices else 0
            self.step_status_label.setText(
                f"Loaded: {Path(path).name}\n"
                f"Solids: {solid_count}  Faces: {len(result.face_meshes)}  "
                f"Edges: {len(result.edge_polylines)}  Vertices: {len(result.vertex_points)}\n"
                f"Left-click a face/edge/vertex to select it.{lod_note}"
            )
        except Exception as exc:  # pragma: no cover - runtime environment specific
            self.step_status_label.setText(f"Could not display the STEP geometry: {exc}")

    def _cleanup_step_load_thread(self):
        if self._step_load_thread is not None:
            self._step_load_thread.deleteLater()
        if self._step_load_worker is not None:
            self._step_load_worker.deleteLater()
        self._step_load_thread = None
        self._step_load_worker = None

    def _cancel_step_load_for_shutdown(self):
        """Called from the main window's closeEvent so the app doesn't
        hang or print QThread warnings if a load is still running when
        the window is closed."""
        if self._step_load_thread is not None:
            self._step_load_thread.quit()
            self._step_load_thread.wait(3000)

    def set_pick_filter(self, display_text: str):
        """Connected to the toolbar's selection-filter combo. Maps its
        display text ("Any"/"Vertices"/"Edges"/"Faces"/"Solids") to the
        internal filter value _resolve_pick_for_filter checks."""
        mapping = {
            "Any": "any", "Vertices": "vertex", "Edges": "edge",
            "Faces": "face", "Solids": "solid",
        }
        self._pick_filter = mapping.get(display_text, "any")

    def _resolve_pick_for_filter(self, obj):
        """Applies the current selection filter (self._pick_filter, one of
        "any"/"vertex"/"edge"/"face"/"solid", set from the toolbar combo)
        to a raw pick.

        Returns the object to hand to downstream consumers (possibly a
        synthesized _SolidPickMarker standing in for a whole solid), or
        the _PICK_REJECTED sentinel if this pick doesn't match the active
        filter and should be dropped outright.
        """
        pick_filter = getattr(self, "_pick_filter", "any")
        if pick_filter == "any" or obj is None:
            return obj

        info = self._step_entity_info.get(id(obj))
        if info is None:
            return obj  # let the normal "Selection cleared" path handle it

        if pick_filter in ("vertex", "edge", "face"):
            if info["type"] != pick_filter:
                self.step_status_label.setText(
                    f"Selection filter is set to '{pick_filter}s' - clicked a "
                    f"{info['type']}, ignored. Change the filter or click a matching entity."
                )
                return _PICK_REJECTED
            return obj

        if pick_filter == "solid":
            if info["type"] != "face":
                self.step_status_label.setText(
                    "Selection filter is set to 'solids' - click a face belonging to the "
                    "solid you want (every solid's surface is covered by its own faces; "
                    "edges/vertices aren't individually grouped by solid)."
                )
                return _PICK_REJECTED

            solid_index = info.get("solid_index")
            if solid_index is None:
                self.step_status_label.setText(
                    "This part's solids couldn't be distinguished (this compas_occ "
                    "version didn't expose per-solid grouping) - selecting the individual face instead."
                )
                return obj

            aggregated_points = np.concatenate([
                entry["points"] for entry in self._step_entity_info.values()
                if entry.get("solid_index") == solid_index
            ], axis=0)
            marker = _SolidPickMarker()
            self._pick_markers.append(marker)
            self._step_entity_info[id(marker)] = {
                "type": "solid", "index": solid_index, "points": aggregated_points,
            }
            return marker

        return obj

    def _resolve_entity_info_for_renderer(self, obj):
        if obj is None:
            return None
        return self._step_entity_info.get(id(obj)) if getattr(self, "_step_entity_info", None) is not None else None

    def _on_step_entity_picked(self, obj):
        """Show info about whichever face/edge/vertex/solid was just
        clicked.

        The active selection filter (self._pick_filter) is applied first
        - see _resolve_pick_for_filter - before this pick is offered to
        any tool: a measurement slot (A or B) currently armed via the
        Measure tab, or a datum slot (Primary/Secondary/Tertiary) armed
        via the GD&T Position tab. See _measure_on_pick and _datum_on_pick.
        """
        obj = self._resolve_pick_for_filter(obj)
        if obj is _PICK_REJECTED:
            return

        if getattr(self, "_measure_on_pick", None) is not None and self._measure_on_pick(obj):
            return
        if getattr(self, "_datum_on_pick", None) is not None and self._datum_on_pick(obj):
            return

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
        elif kind == "solid":
            n_faces = sum(
                1 for entry in self._step_entity_info.values()
                if entry.get("solid_index") == idx and entry["type"] == "face"
            )
            self.step_status_label.setText(f"Selected: Solid #{idx} (whole body, {n_faces} faces)")
