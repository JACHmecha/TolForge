"""Background worker for STEP parsing/tessellation.

Runs the OCCT/compas_occ work (which can take a while on a large assembly)
off the Qt main thread, so loading a big STEP file doesn't freeze the UI.

Deliberately does NOT touch anything OpenGL/Qt-widget related - GL context
calls (makeCurrent/rebuild_buffers/scene.add) only work on the thread that
owns the GL surface (the main thread here), so this worker only prepares
plain data (compas Mesh/Polyline/Point objects, no scene objects yet) and
hands it back via a Qt signal for the main thread to push into the scene.
"""

import hashlib
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, QThread, Signal


class StepLoadCancelled(Exception):
    """A cooperative checkpoint acknowledged a cancellation request."""


class StepLoadOutcome:
    """Terminal notification remains valid after the worker QObject is deleted."""

    __slots__ = ("generation", "kind", "path", "result", "message", "deflection_applied")

    def __init__(self, generation, kind, path, *, result=None, message="", deflection_applied=True):
        self.generation = generation
        self.kind = kind
        self.path = path
        self.result = result
        self.message = message
        self.deflection_applied = deflection_applied


class StepLoadResult:
    """Plain data container - no Qt/GL objects, safe to build off-thread
    and hand across the thread boundary via a signal."""

    __slots__ = ("face_meshes", "face_solid_indices", "edge_polylines", "vertex_points", "face_surfaces",
                 "source_path", "source_sha256", "source_hash_status")

    def __init__(self, face_meshes, face_solid_indices, edge_polylines, vertex_points, face_surfaces=None,
                 *, source_path=None, source_sha256=None, source_hash_status="unverified"):
        self.face_meshes = face_meshes
        self.face_solid_indices = face_solid_indices
        self.edge_polylines = edge_polylines
        self.vertex_points = vertex_points
        self.face_surfaces = face_surfaces or []
        self.source_path = source_path
        self.source_sha256 = source_sha256
        self.source_hash_status = source_hash_status


class StepLoadWorker(QObject):
    """Call .run() after moveToThread() (typically via thread.started).

    deflection controls tessellation resolution (LOD): smaller = finer
    mesh / more triangles / slower, larger = coarser mesh / fewer
    triangles / faster. Reasonable starting point for a medium-sized
    (tens of mm to a few hundred mm) part is around 0.1-0.5 model units;
    large assemblies benefit from pushing this up (1.0+) to keep the
    triangle count - and therefore both load time and render time -
    manageable.
    """

    finished = Signal(object)  # StepLoadResult on success
    failed = Signal(str)       # error message on failure
    cancelled = Signal()
    terminal = Signal(object)  # StepLoadOutcome on every normal exit
    stage_changed = Signal(int, str)
    progress_changed = Signal(int, int, int)  # generation, completed, total (0 = indeterminate)

    def __init__(self, path: str, deflection: float):
        super().__init__()
        self.path = path
        self.deflection = deflection
        # Set by the caller (right after construction, before thread.start())
        # so the finished/failed slots can tell a stale/superseded load
        # apart from the current one without needing a lambda to capture it.
        self.generation = None
        # Set True if the installed compas_occ's to_viewmesh() doesn't
        # accept deflection kwargs at all, so the caller can tell the user
        # their quality setting had no effect rather than silently
        # ignoring it.
        self.deflection_applied = True
        self._cancel_event = Event()

    def request_cancel(self):
        """Thread-safe; call directly while the worker's event loop is occupied."""
        self._cancel_event.set()

    def _checkpoint(self):
        if self._cancel_event.is_set() or QThread.currentThread().isInterruptionRequested():
            raise StepLoadCancelled()

    def _stage(self, description, total=0):
        self._checkpoint()
        self.stage_changed.emit(self.generation or 0, description)
        self.progress_changed.emit(self.generation or 0, 0, total)

    def _progress(self, completed, total):
        self._checkpoint()
        self.progress_changed.emit(self.generation or 0, completed, total)

    def run(self):
        kind, result, message = "cancelled", None, ""
        try:
            self._checkpoint()
            result = self._load()
            self._checkpoint()
            kind = "finished"
        except StepLoadCancelled:
            pass
        except Exception as exc:  # pragma: no cover - runtime environment specific
            if not self._cancel_event.is_set() and not QThread.currentThread().isInterruptionRequested():
                kind, message = "failed", str(exc)
        if kind == "finished":
            self.finished.emit(result)
        elif kind == "failed":
            self.failed.emit(message)
        else:
            self.cancelled.emit()
        self.terminal.emit(StepLoadOutcome(self.generation, kind, self.path, result=result,
                                          message=message, deflection_applied=self.deflection_applied))

    @staticmethod
    def _file_identity(stat):
        return stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino

    def _source_digest(self):
        """Check cancellation between chunks and reject a source changing mid-hash."""
        self._checkpoint()
        path = Path(self.path)
        before = self._file_identity(path.stat())
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while True:
                self._checkpoint()
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        self._checkpoint()
        after = self._file_identity(path.stat())
        if before != after:
            raise ValueError("The STEP source changed during loading. Load the file again after it is stable.")
        return digest.hexdigest(), after

    def _load(self) -> StepLoadResult:
        self._stage("Verifying STEP source")
        source_sha256, source_identity = self._source_digest()
        self._checkpoint()
        from compas_occ.brep import OCCBrep

        # heal=True fixes small gaps/discontinuities that are common in
        # STEP files exported from different CAD packages.
        self._stage("Reading STEP (native call)")
        brep = OCCBrep.from_step(self.path, heal=True)
        self._checkpoint()

        self._stage("Grouping solid faces")
        face_solid_pairs = self._group_faces_by_solid(brep, OCCBrep)
        self._checkpoint()

        # Each face gets tessellated on its own (via a single-face
        # sub-Brep) so it becomes its own pickable object later, rather
        # than part of one fused mesh with no face boundaries.
        face_meshes = []
        face_solid_indices = []
        face_surfaces = []
        self._stage("Tessellating faces", len(face_solid_pairs))
        for completed, (face, solid_index) in enumerate(face_solid_pairs, start=1):
            self._checkpoint()
            face_brep = OCCBrep.from_brepfaces([face], solid=False)
            self._checkpoint()
            face_mesh, _unused_edges = self._tessellate(face_brep)
            self._checkpoint()
            face_meshes.append(face_mesh)
            face_solid_indices.append(solid_index)
            face_surfaces.append(self._recognize_surface(face))
            self._progress(completed, len(face_solid_pairs))

        # The whole-Brep to_viewmesh() call also returns per-edge
        # polylines - reuse that instead of re-deriving edge geometry by
        # hand. NOTE: edges/vertices deliberately aren't grouped by solid
        # the way faces are above - matching a compas_occ wrapper object
        # obtained from brep.edges against one obtained via a per-solid
        # sub-Brep's own .edges would need to compare by underlying OCCT
        # shape identity (IsSame/IsEqual), which isn't exposed uniformly
        # enough across compas_occ versions to rely on here. Since a
        # solid's own faces already cover its whole surface, "Solids"
        # selection mode only needs to work when the user clicks a face -
        # see gui/step_viewer_mixin.py's pick-filter handling.
        self._stage("Tessellating edges (native call)")
        _unused_mesh, edge_polylines = self._tessellate(brep)
        self._checkpoint()

        self._stage("Collecting vertices")
        vertex_points = []
        for vertex in brep.vertices:
            self._checkpoint()
            vertex_points.append(vertex.to_point())
            self._checkpoint()

        self._stage("Verifying STEP source after load")
        final_sha256, final_identity = self._source_digest()
        if source_sha256 != final_sha256 or source_identity != final_identity:
            raise ValueError("The STEP source changed during loading. Load the file again after it is stable.")
        self._checkpoint()

        return StepLoadResult(
            face_meshes=face_meshes, face_solid_indices=face_solid_indices,
            edge_polylines=edge_polylines, vertex_points=vertex_points,
            face_surfaces=face_surfaces,
            source_path=str(Path(self.path).resolve()), source_sha256=source_sha256, source_hash_status="verified",
        )

    @staticmethod
    def _recognize_surface(face):
        """Extract located analytic geometry before discarding the OCCT face.

        Only plain Python values cross the worker boundary. A trimmed or
        partial cylindrical face retains the same underlying cylinder axis.
        """
        from OCC.Core.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder
        try:
            adaptor = face.occ_adaptor
            kind = adaptor.GetType()
            if kind == GeomAbs_Cylinder:
                cylinder = adaptor.Cylinder()
                axis = cylinder.Axis()
                return {"kind": "cylinder", "point": list(axis.Location().Coord()),
                        "direction": list(axis.Direction().Coord()), "radius": cylinder.Radius()}
            if kind == GeomAbs_Plane:
                plane = adaptor.Plane()
                return {"kind": "plane", "point": list(plane.Location().Coord()),
                        "direction": list(plane.Axis().Direction().Coord())}
            return {"kind": "other"}
        except (AttributeError, RuntimeError):
            return {"kind": "unknown"}

    def _group_faces_by_solid(self, brep, occ_brep_cls):
        """Returns a list of (face, solid_index) pairs. Falls back to
        solid_index=0 for every face (i.e. "one solid") if this
        compas_occ version's Brep doesn't expose .solids, or a solid
        doesn't expose its own .faces the way expected - this is a best-
        effort grouping, not something we can verify without the actual
        library installed, so it degrades gracefully rather than
        crashing the whole load over a coloring feature.
        """
        self._checkpoint()
        try:
            solids = list(brep.solids)
        except Exception:
            solids = []

        self._checkpoint()
        if not solids:
            return self._ungrouped_faces(brep)

        pairs = []
        for solid_index, solid in enumerate(solids):
            self._checkpoint()
            try:
                solid_faces = list(solid.faces)
            except AttributeError:
                # `solid` might be a raw OCCT shape rather than an object
                # that already wraps it with its own .faces - try
                # re-wrapping it as its own Brep.
                try:
                    solid_faces = list(occ_brep_cls.from_shape(solid).faces)
                except Exception:
                    continue
            for face in solid_faces:
                self._checkpoint()
                pairs.append((face, solid_index))

        if not pairs:
            # Something about the .solids path didn't pan out - fall back
            # rather than returning an empty part.
            return self._ungrouped_faces(brep)
        return pairs

    def _ungrouped_faces(self, brep):
        pairs = []
        for face in brep.faces:
            self._checkpoint()
            pairs.append((face, 0))
        return pairs

    def _tessellate(self, brep_like):
        """Wraps to_viewmesh() with the deflection (LOD) setting, falling
        back to the library's own default resolution if the installed
        compas_occ version doesn't expose deflection kwargs on
        to_viewmesh() - this varies across versions and isn't worth a
        hard version pin just for this.
        """
        self._checkpoint()
        try:
            result = brep_like.to_viewmesh(
                linear_deflection=self.deflection, angular_deflection=self.deflection
            )
        except TypeError:
            self._checkpoint()
            self.deflection_applied = False
            result = brep_like.to_viewmesh()
        self._checkpoint()
        return result
