"""Cancellation boundaries, queued ownership, and verified STEP source handoff."""

import hashlib
import sys
from threading import Event
from types import ModuleType, SimpleNamespace

import pytest
from PySide6.QtCore import QThread
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QLabel, QProgressBar, QPushButton, QTableWidget, QWidget

from gui.step_load_worker import StepLoadOutcome, StepLoadResult, StepLoadWorker
from gui.step_viewer_mixin import StepViewerMixin
from gui import step_viewer_mixin as viewer_module
from gui.app import TolstackWindow
from tolstack import drafts
from tolstack.domain import (
    DatumReference, DatumSystem, FeatureDefinition, PartDefinition, PartOccurrence,
    PositionControlDefinition, PositionPatternMember, ToleranceDefinition,
)
from tolstack.project import Project


def empty_result(path="source.step"):
    return StepLoadResult([], [], [], [], source_path=path, source_sha256="a" * 64, source_hash_status="verified")


@pytest.fixture
def fake_reader(monkeypatch, tmp_path):
    path = tmp_path / "part.step"
    path.write_bytes(b"Stable STEP bytes")
    worker = StepLoadWorker(str(path), 0.4)
    worker.generation = 7
    calls, hooks = [], {}

    def call(name):
        calls.append(name)
        hook = hooks.get(name)
        if hook is not None:
            hook()

    class Vertex:
        def to_point(self):
            call("vertex")
            return [0, 0, 0]

    class Brep:
        @property
        def solids(self):
            call("group")
            return []

        faces = [object(), object()]
        vertices = [Vertex(), Vertex()]

        def to_viewmesh(self, **kwargs):
            call("edge_tessellate")
            return object(), []

    class FaceBrep:
        def to_viewmesh(self, **kwargs):
            call("face_tessellate")
            return object(), []

    class Reader:
        @staticmethod
        def from_step(path, heal):
            call("read")
            return Brep()

        @staticmethod
        def from_brepfaces(faces, solid):
            call("face_construct")
            return FaceBrep()

    package = ModuleType("compas_occ")
    package.__path__ = []
    backend = ModuleType("compas_occ.brep")
    backend.OCCBrep = Reader
    monkeypatch.setitem(sys.modules, "compas_occ", package)
    monkeypatch.setitem(sys.modules, "compas_occ.brep", backend)

    def recognize(face):
        call("recognize")
        return {"kind": "plane"}

    monkeypatch.setattr(worker, "_recognize_surface", recognize)
    return worker, calls, hooks, path


def capture(worker):
    notifications = {name: [] for name in ("finished", "failed", "cancelled", "terminal", "stage", "progress")}
    worker.finished.connect(notifications["finished"].append)
    worker.failed.connect(notifications["failed"].append)
    worker.cancelled.connect(lambda: notifications["cancelled"].append(True))
    worker.terminal.connect(notifications["terminal"].append)
    worker.stage_changed.connect(lambda generation, stage: notifications["stage"].append((generation, stage)))
    worker.progress_changed.connect(lambda generation, completed, total: notifications["progress"].append((generation, completed, total)))
    return notifications


def test_cancel_before_run_never_reads_source_or_imports_backend(fake_reader):
    worker, calls, _hooks, _path = fake_reader
    notifications = capture(worker)
    worker.request_cancel()
    worker.run()
    assert calls == []
    assert notifications["cancelled"] == [True]
    assert [outcome.kind for outcome in notifications["terminal"]] == ["cancelled"]
    assert not notifications["finished"] and not notifications["failed"]


@pytest.mark.parametrize("boundary", ["read", "group", "face_construct", "face_tessellate", "recognize", "edge_tessellate", "vertex"])
def test_cancel_after_controllable_stage_stops_remaining_geometry_work(fake_reader, boundary):
    worker, calls, hooks, _path = fake_reader
    notifications = capture(worker)
    hooks[boundary] = worker.request_cancel
    worker.run()
    assert calls[-1] == boundary
    assert calls.count(boundary) == 1
    assert notifications["cancelled"] == [True]
    assert [outcome.kind for outcome in notifications["terminal"]] == ["cancelled"]
    assert not notifications["finished"] and not notifications["failed"]


def test_cancellation_during_final_source_verification_cannot_publish_result(fake_reader, monkeypatch):
    worker, _calls, _hooks, _path = fake_reader
    digest = worker._source_digest
    count = 0

    def cancel_final_hash():
        nonlocal count
        count += 1
        if count == 2:
            worker.request_cancel()
        return digest()

    monkeypatch.setattr(worker, "_source_digest", cancel_final_hash)
    notifications = capture(worker)
    worker.run()
    assert count == 2
    assert notifications["terminal"][0].kind == "cancelled"
    assert not notifications["finished"]


def test_stable_source_success_emits_verified_digest_and_generation_progress(fake_reader):
    worker, _calls, _hooks, path = fake_reader
    notifications = capture(worker)
    worker.run()
    result = notifications["finished"][0]
    assert result.source_path == str(path.resolve())
    assert result.source_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert result.source_hash_status == "verified"
    assert notifications["terminal"][0].kind == "finished"
    assert notifications["terminal"][0].generation == 7
    assert (7, 2, 2) in notifications["progress"]
    assert all(generation == 7 for generation, _stage in notifications["stage"])


def test_source_changed_during_native_work_fails_without_geometry_publication(fake_reader):
    worker, _calls, hooks, path = fake_reader
    hooks["face_tessellate"] = lambda: path.write_bytes(b"Changed STEP revision")
    notifications = capture(worker)
    worker.run()
    assert not notifications["finished"] and not notifications["cancelled"]
    assert "changed during loading" in notifications["failed"][0]
    assert notifications["terminal"][0].kind == "failed"


class ViewerHarness(QWidget, StepViewerMixin):
    def __init__(self):
        QWidget.__init__(self)
        self._step_load_thread = self._step_load_worker = None
        self._step_load_generation = 0
        self._step_preview_renderer = SimpleNamespace(update=lambda: None)
        self._step_entity_info = {"prior": "displayed geometry"}
        self._entity_by_feature_id = {}
        self._datum_slot = dict.fromkeys(("Primary", "Secondary", "Tertiary"))
        self.step_status_label = QLabel("Prior model")
        self.step_deflection_input = QDoubleSpinBox()
        self.step_cancel_button = QPushButton("Cancel")
        self.step_load_progress = QProgressBar()
        self.resets, self.commits, self.commit_threads = 0, [], []
        self.close_finishes = 0

    def _reset_surface_previews(self):
        self.resets += 1

    def _zoom_to_fit(self, renderer):
        pass

    def _project_on_step_loaded(self, path, **evidence):
        self.commits.append((path, evidence))
        self.commit_threads.append(QThread.currentThread())

    def _project_finish_deferred_close(self):
        self.close_finishes += 1


@pytest.fixture
def viewer(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = ViewerHarness()
    adapter = SimpleNamespace(clear=lambda: None, refresh=lambda **kwargs: None)
    monkeypatch.setattr(viewer_module, "CompasViewportAdapter", lambda renderer: adapter)
    yield window, adapter
    thread = window._step_load_thread
    if thread is not None and thread.isRunning():
        window._request_step_load_cancel()
        thread.quit()
        thread.wait(6000)
    app.processEvents()
    window.close()


def wait_for(predicate):
    for _ in range(100):
        QApplication.processEvents()
        if predicate():
            return
        QTest.qWait(5)
    assert predicate(), "Qt notification was not delivered"


def blocked_worker(monkeypatch):
    entered, release = Event(), Event()

    class Worker(StepLoadWorker):
        def _load(self):
            self._stage("Reading STEP (native call)")
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test release timed out")
            self._checkpoint()
            return empty_result(self.path)

    monkeypatch.setattr(viewer_module, "StepLoadWorker", Worker)
    return entered, release


def test_cancel_retains_previous_scene_and_running_thread_until_native_return(viewer, monkeypatch):
    window, _adapter = viewer
    entered, release = blocked_worker(monkeypatch)
    assert window._start_step_load("source.step")
    wait_for(entered.is_set)
    thread, worker = window._step_load_thread, window._step_load_worker
    window._cleanup_step_load_thread()
    assert window._step_load_thread is thread and window._step_load_worker is worker
    assert window.cancel_step_load()
    assert thread.isRunning()
    assert window._step_load_thread is thread and window._step_load_worker is worker
    assert window._step_entity_info == {"prior": "displayed geometry"}
    assert not window.step_cancel_button.isEnabled()
    assert "Waiting for the current native operation" in window.step_status_label.text()
    release.set()
    assert thread.wait(2000)
    wait_for(lambda: window._step_load_thread is None)
    assert window.resets == 0 and window.commits == []
    assert "canceled" in window.step_status_label.text()


def test_success_commit_is_queued_to_gui_thread_and_hands_verified_source_to_project(viewer, monkeypatch):
    window, _adapter = viewer
    entered, release = blocked_worker(monkeypatch)
    assert window._start_step_load("source.step")
    wait_for(entered.is_set)
    thread = window._step_load_thread
    release.set()
    assert thread.wait(2000)
    assert window.commits == []  # no GUI notification has been pumped
    wait_for(lambda: window._step_load_thread is None)
    assert window.resets == 1
    assert window.commit_threads == [QApplication.instance().thread()]
    assert window.commits == [("source.step", {"source_sha256": "a" * 64, "source_hash_status": "verified"})]


def test_cancel_after_actual_success_before_gui_delivery_cannot_replace_scene(viewer, monkeypatch):
    window, _adapter = viewer
    entered, release = blocked_worker(monkeypatch)
    assert window._start_step_load("source.step")
    wait_for(entered.is_set)
    thread = window._step_load_thread
    release.set()
    assert thread.wait(2000)
    assert window.cancel_step_load()
    wait_for(lambda: window._step_load_thread is None)
    assert window.resets == 0 and window.commits == []
    assert window._step_entity_info == {"prior": "displayed geometry"}


def test_replacement_load_waits_for_canceled_worker_ownership_release(viewer, monkeypatch):
    window, _adapter = viewer
    entered, release = blocked_worker(monkeypatch)
    assert window._start_step_load("first.step")
    wait_for(entered.is_set)
    first_thread = window._step_load_thread
    assert window.cancel_step_load()
    assert window._start_step_load("replacement.step") is False
    assert window._step_load_thread is first_thread
    release.set()
    assert first_thread.wait(2000)
    wait_for(lambda: bool(window.commits))
    wait_for(lambda: window._step_load_thread is None)
    assert [path for path, _evidence in window.commits] == ["replacement.step"]


def test_rapid_canceled_replacements_release_each_native_owner_before_reuse(viewer, monkeypatch):
    window, _adapter = viewer
    for cycle in range(12):
        entered, release = blocked_worker(monkeypatch)
        assert window._start_step_load(f"canceled-{cycle}.step")
        wait_for(entered.is_set)
        thread = window._step_load_thread
        assert window.cancel_step_load()
        assert window._start_step_load(f"accepted-{cycle}.step") is False
        release.set()
        assert thread.wait(2000)
        wait_for(lambda: len(window.commits) == cycle + 1)
        wait_for(lambda: window._step_load_thread is None)
    assert [path for path, _evidence in window.commits] == [f"accepted-{cycle}.step" for cycle in range(12)]


@pytest.mark.parametrize("clean_open, dirty", [(False, False), (True, False), (True, True)])
def test_ordinary_reload_preserves_raw_unresolved_pattern_except_pristine_saved_open(viewer, clean_open, dirty):
    window, _adapter = viewer
    window.pattern_table = QTableWidget(1, 10)
    window._project_loading_clean_from_disk = clean_open
    window._project_is_dirty = lambda: dirty
    captures = []
    window._project_capture_raw_geometry_before_load = lambda: captures.append(True)
    worker = StepLoadWorker("source.step", 0.4)
    worker.generation = window._step_load_generation = 19
    window._step_load_worker = worker
    window._on_step_load_terminal(StepLoadOutcome(19, "finished", "source.step", result=empty_result()))
    pristine_open = clean_open and not dirty
    assert captures == ([] if pristine_open else [True])
    assert getattr(window, "_project_preserve_raw_geometry", False) is not pristine_open


@pytest.mark.parametrize("edit_during_read", [False, True])
def test_initial_saved_load_preserves_editor_state_and_cleanliness_at_commit(monkeypatch, tmp_path, edit_during_read):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(drafts, "draft_directory", lambda: tmp_path / "drafts")
    monkeypatch.setattr(TolstackWindow, "_init_step_preview_renderer", lambda self: None)
    monkeypatch.setattr(TolstackWindow, "_zoom_to_fit", lambda self, renderer: None)
    adapter = SimpleNamespace(clear=lambda: None, refresh=lambda **kwargs: None)
    monkeypatch.setattr(viewer_module, "CompasViewportAdapter", lambda renderer: adapter)
    entered, release = blocked_worker(monkeypatch)
    window = TolstackWindow()
    window._project_change_timer.stop()
    window._step_preview_renderer = SimpleNamespace(update=lambda: None)
    try:
        source = tmp_path / "source.step"
        source.write_bytes(b"Captured source used by controlled slow reader")
        project = Project("Saved plate")
        part = project.add_part(PartDefinition("Plate", str(source), "a" * 64, id="part"))
        project.add_occurrence(PartOccurrence(part.id, "Plate:1", id="occurrence"))
        feature = project.add_feature(FeatureDefinition(part.id, "Saved hole", "circle", id="hole"))
        datum = project.add_datum_reference(DatumReference(feature.id, "A", id="datum"))
        frame = project.add_datum_system(DatumSystem("Saved frame", [datum.id], id="frame"))
        size = project.add_tolerance(ToleranceDefinition("Hole size", "size", 10, .1, .1, id="size"))
        x = project.add_tolerance(ToleranceDefinition("X variation", "position", 0, .05, .05, id="x"))
        y = project.add_tolerance(ToleranceDefinition("Y variation", "position", 0, .05, .05, id="y"))
        project.add_position_control(PositionControlDefinition("Position", frame.id, .2, members=[
            PositionPatternMember("Saved hole", feature.id, 1, 2, size.id, x.id, y.id, id="stable-member"),
        ], id="position"))
        saved = tmp_path / "saved-study.json"
        project.save(saved)
        assert window._project_open_from(str(saved))
        assert not window._project_is_dirty()
        assert window._project_loading_clean_from_disk
        wait_for(entered.is_set)
        if edit_during_read:
            window.pattern_table.item(0, 1).setText("unfinished coordinate typed during STEP read")
        raw = window._project_table_snapshot("pattern")
        assert window._project_is_dirty() is edit_during_read
        thread = window._step_load_thread
        release.set()
        assert thread.wait(2000)
        wait_for(lambda: window._step_load_thread is None)
        assert window._project_table_snapshot("pattern") == raw
        assert window.pattern_table.item(0, 0).data(window.PATTERN_MEMBER_ID_ROLE) == "stable-member"
        assert window._entity_by_feature_id == {}
        assert window._project_is_dirty() is edit_during_read
        assert window.project.position_controls["position"].members[0].basic_x == 1
    finally:
        release.set()
        thread = window._step_load_thread
        if thread is not None and thread.isRunning():
            window._request_step_load_cancel()
            thread.wait(2000)
        app.processEvents()
        window.close()


@pytest.mark.parametrize("order", ["thread_first", "outcome_first"])
def test_ownership_release_waits_for_both_terminal_application_and_actual_finish(viewer, order):
    window, _adapter = viewer
    thread = QThread(window)
    worker = StepLoadWorker("source.step", 0.4)
    worker.generation = window._step_load_generation = 11
    window._step_load_thread, window._step_load_worker = thread, worker
    window._step_load_terminal_received = window._step_load_thread_finished = False
    outcome = StepLoadOutcome(11, "finished", "source.step", result=empty_result())
    if order == "thread_first":
        window._cleanup_step_load_thread()
        assert window._step_load_worker is worker
        assert window._step_load_thread is thread
        window._on_step_load_terminal(outcome)
    else:
        window._on_step_load_terminal(outcome)
        assert window._step_load_worker is worker
        assert window._step_load_thread is thread
        window._cleanup_step_load_thread()
    assert window._step_load_thread is None and window._step_load_worker is None
    assert len(window.commits) == 1


def test_close_after_actual_finish_before_queued_terminal_defers_and_does_not_commit(viewer):
    window, _adapter = viewer
    thread, worker = QThread(window), StepLoadWorker("source.step", 0.4)
    worker.generation = window._step_load_generation = 13
    window._step_load_thread, window._step_load_worker = thread, worker
    window._step_load_terminal_received = window._step_load_thread_finished = False
    window._project_closing = window._project_close_waiting = True
    assert not thread.isRunning()
    assert window._cancel_step_load_for_shutdown() is False
    window._cleanup_step_load_thread()
    assert window._step_load_worker is worker and window.close_finishes == 0
    window._on_step_load_terminal(StepLoadOutcome(13, "finished", "source.step", result=empty_result()))
    assert window._step_load_thread is None and window.close_finishes == 1
    assert window.commits == [] and window.resets == 0


def test_finished_signal_does_not_release_native_owner_before_nonblocking_join(viewer):
    window, _adapter = viewer
    joined, deleted = [], []
    thread = SimpleNamespace(isRunning=lambda: False, wait=lambda timeout: bool(joined),
                             deleteLater=lambda: deleted.append(True))
    window._step_load_thread = thread
    window._step_load_terminal_received = window._step_load_thread_finished = True
    window._project_close_waiting = True
    window._release_step_load_if_complete()
    assert window._step_load_thread is thread
    assert deleted == [] and window.close_finishes == 0
    joined.append(True)
    wait_for(lambda: window._step_load_thread is None)
    assert deleted == [True] and window.close_finishes == 1


def test_stale_progress_and_success_cannot_mutate_current_scene_or_status(viewer):
    window, _adapter = viewer
    worker = StepLoadWorker("stale.step", 0.4)
    worker.generation = 1
    window._step_load_generation = 2
    window._step_load_worker = worker
    window._on_step_load_stage(1, "Stale stage")
    window._on_step_load_progress(1, 1, 10)
    window._on_step_load_terminal(StepLoadOutcome(1, "finished", "stale.step", result=empty_result()))
    assert window.step_status_label.text() == "Prior model"
    assert window._step_entity_info == {"prior": "displayed geometry"}
    assert window.resets == 0 and window.commits == []


def test_canceled_old_load_cannot_overwrite_clear_preview_status(viewer):
    window, _adapter = viewer
    worker = StepLoadWorker("source.step", 0.4)
    worker.generation = window._step_load_generation = 1
    window._step_load_thread, window._step_load_worker = QThread(window), worker
    window.clear_step_preview()
    window._on_step_load_terminal(StepLoadOutcome(1, "cancelled", "source.step"))
    assert window.step_status_label.text() == "No STEP file loaded yet."
    assert window._step_entity_info == {} and window.commits == []


def test_clear_or_cancel_during_commit_cannot_publish_project_or_loaded_status(viewer):
    window, adapter = viewer
    worker = StepLoadWorker("source.step", 0.4)
    worker.generation = window._step_load_generation = 19
    window._step_load_worker = worker

    def clear_during_refresh(**kwargs):
        window._step_load_generation += 1
        window._step_entity_info = {}
        window.step_status_label.setText("Cleared by user")

    adapter.refresh = clear_during_refresh
    window._on_step_load_terminal(StepLoadOutcome(19, "finished", "source.step", result=empty_result()))
    assert window.commits == []
    assert window.step_status_label.text() == "Cleared by user"


@pytest.mark.native_cad
def test_native_worker_cancel_between_face_stages_and_verified_success(tmp_path, native_cad_backend, monkeypatch):
    from compas.geometry import Box
    from compas_occ.brep import OCCBrep

    path = tmp_path / "native-box.step"
    OCCBrep.from_box(Box(2, 3, 4)).to_step(str(path))
    worker = StepLoadWorker(str(path), 0.4)
    tessellate = worker._tessellate
    calls = []

    def cancel_after_first_face(brep):
        value = tessellate(brep)
        calls.append(True)
        worker.request_cancel()
        return value

    monkeypatch.setattr(worker, "_tessellate", cancel_after_first_face)
    notifications = capture(worker)
    worker.run()
    assert calls == [True]
    assert notifications["terminal"][0].kind == "cancelled"
    assert not notifications["finished"]

    complete = StepLoadWorker(str(path), 0.4)._load()
    assert len(complete.face_meshes) == 6
    assert complete.source_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert complete.source_hash_status == "verified"


@pytest.mark.native_cad
def test_native_qthread_result_commits_on_gui_thread_with_verified_hash(viewer, tmp_path, native_cad_backend):
    from compas.geometry import Box
    from compas_occ.brep import OCCBrep

    window, adapter = viewer
    adapter.add = lambda geometry, **kwargs: None
    path = tmp_path / "threaded-box.step"
    OCCBrep.from_box(Box(2, 3, 4)).to_step(str(path))
    assert window._start_step_load(str(path))
    thread = window._step_load_thread
    assert thread.wait(5000)
    assert window.commits == []
    wait_for(lambda: window._step_load_thread is None)
    assert window.commit_threads == [QApplication.instance().thread()]
    assert window.commits == [(str(path), {"source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                         "source_hash_status": "verified"})]
