"""Background worker for STEP parsing/tessellation.

Runs the OCCT/compas_occ work (which can take a while on a large assembly)
off the Qt main thread, so loading a big STEP file doesn't freeze the UI.

Deliberately does NOT touch anything OpenGL/Qt-widget related - GL context
calls (makeCurrent/rebuild_buffers/scene.add) only work on the thread that
owns the GL surface (the main thread here), so this worker only prepares
plain data (compas Mesh/Polyline/Point objects, no scene objects yet) and
hands it back via a Qt signal for the main thread to push into the scene.
"""

from PySide6.QtCore import QObject, Signal


class StepLoadResult:
    """Plain data container - no Qt/GL objects, safe to build off-thread
    and hand across the thread boundary via a signal."""

    __slots__ = ("face_meshes", "face_solid_indices", "edge_polylines", "vertex_points")

    def __init__(self, face_meshes, face_solid_indices, edge_polylines, vertex_points):
        self.face_meshes = face_meshes
        self.face_solid_indices = face_solid_indices
        self.edge_polylines = edge_polylines
        self.vertex_points = vertex_points


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

    def run(self):
        try:
            result = self._load()
        except Exception as exc:  # pragma: no cover - runtime environment specific
            self.failed.emit(str(exc))
            return
        self.finished.emit(result)

    def _load(self) -> StepLoadResult:
        from compas_occ.brep import OCCBrep

        # heal=True fixes small gaps/discontinuities that are common in
        # STEP files exported from different CAD packages.
        brep = OCCBrep.from_step(self.path, heal=True)

        face_solid_pairs = self._group_faces_by_solid(brep, OCCBrep)

        # Each face gets tessellated on its own (via a single-face
        # sub-Brep) so it becomes its own pickable object later, rather
        # than part of one fused mesh with no face boundaries.
        face_meshes = []
        face_solid_indices = []
        for face, solid_index in face_solid_pairs:
            face_brep = OCCBrep.from_brepfaces([face], solid=False)
            face_mesh, _unused_edges = self._tessellate(face_brep)
            face_meshes.append(face_mesh)
            face_solid_indices.append(solid_index)

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
        _unused_mesh, edge_polylines = self._tessellate(brep)

        vertex_points = [vertex.to_point() for vertex in brep.vertices]

        return StepLoadResult(
            face_meshes=face_meshes, face_solid_indices=face_solid_indices,
            edge_polylines=edge_polylines, vertex_points=vertex_points,
        )

    @staticmethod
    def _group_faces_by_solid(brep, occ_brep_cls):
        """Returns a list of (face, solid_index) pairs. Falls back to
        solid_index=0 for every face (i.e. "one solid") if this
        compas_occ version's Brep doesn't expose .solids, or a solid
        doesn't expose its own .faces the way expected - this is a best-
        effort grouping, not something we can verify without the actual
        library installed, so it degrades gracefully rather than
        crashing the whole load over a coloring feature.
        """
        try:
            solids = list(brep.solids)
        except Exception:
            solids = []

        if not solids:
            return [(face, 0) for face in brep.faces]

        pairs = []
        for solid_index, solid in enumerate(solids):
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
                pairs.append((face, solid_index))

        if not pairs:
            # Something about the .solids path didn't pan out - fall back
            # rather than returning an empty part.
            return [(face, 0) for face in brep.faces]
        return pairs

    def _tessellate(self, brep_like):
        """Wraps to_viewmesh() with the deflection (LOD) setting, falling
        back to the library's own default resolution if the installed
        compas_occ version doesn't expose deflection kwargs on
        to_viewmesh() - this varies across versions and isn't worth a
        hard version pin just for this.
        """
        try:
            return brep_like.to_viewmesh(
                linear_deflection=self.deflection, angular_deflection=self.deflection
            )
        except TypeError:
            self.deflection_applied = False
            return brep_like.to_viewmesh()
