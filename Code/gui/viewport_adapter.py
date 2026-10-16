"""Small boundary between application scene operations and COMPAS/Qt.

All calls belong on the renderer's Qt thread. Geometry preparation stays in
StepLoadWorker; this adapter only owns scene mutation, selection and the GL
context needed to commit prepared data to the renderer.
"""

from contextlib import contextmanager


class CompasViewportAdapter:
    def __init__(self, renderer):
        self.renderer = renderer

    @property
    def objects(self) -> tuple:
        """Snapshot so callers can safely remove objects while iterating."""
        return tuple(self.renderer.scene.objects)

    def add(self, geometry, **style):
        return self.renderer.scene.add(geometry, **style)

    def remove(self, obj) -> None:
        self.renderer.scene.remove(obj)

    def clear(self) -> None:
        for obj in self.objects:
            self.remove(obj)

    def select(self, selected) -> None:
        """Apply a single selection to the currently registered scene objects."""
        self.select_many(() if selected is None else (selected,))

    def select_many(self, selected) -> None:
        """Highlight an accepted entity, including all faces of a solid."""
        selected_ids = {id(obj) for obj in selected}
        for obj in self.objects:
            obj.is_selected = id(obj) in selected_ids
        self.refresh()

    @contextmanager
    def gl_context(self):
        """Always release the context, including failed buffer construction."""
        self.renderer.makeCurrent()
        try:
            yield
        finally:
            self.renderer.doneCurrent()

    def refresh(self, *, rebuild: bool = False) -> None:
        if rebuild:
            with self.gl_context():
                self.renderer.rebuild_buffers()
        self.renderer.update()
