import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem

from gui.project_mixin import ProjectMixin
from tolstack import FeatureDefinition, PartDefinition, PartOccurrence, Project


class ProjectBridgeHarness(ProjectMixin):
    LINK_ROLE = Qt.UserRole + 100
    STACK_LINK_VALUE_COLUMN = 6

    def __init__(self):
        self.project = Project("Bridge test")
        self._active_part_id = None
        self._active_occurrence_id = None
        self._active_datum_system_id = None
        self._entity_by_feature_id = {}
        self._step_entity_info = {}
        self.table = QTableWidget(0, 7)

    def _get_sign_from_row(self, row):
        return self.table.item(row, 4).text()

    def _add_table_row(self, name, nominal, tol_plus, tol_minus, sign, cpk):
        row = self.table.rowCount()
        self.table.insertRow(row)
        values = (name, nominal, tol_plus, tol_minus, "+" if sign in (1, "+") else "-", cpk)
        for column, value in enumerate(values):
            self.table.setItem(row, column, QTableWidgetItem("" if value is None else str(value)))

    def _stack_link_set_row_link(self, row, link):
        self.table.item(row, 0).setData(self.LINK_ROLE, link)

    def _measure_ensure_circle_fit(self, info):
        return None


def _app():
    return QApplication.instance() or QApplication([])


def _add_part_and_feature(harness):
    part = harness.project.add_part(PartDefinition("Plate", id="part-1"))
    harness.project.add_occurrence(PartOccurrence(part.id, "Plate:1", id="occ-1"))
    feature = harness.project.add_feature(
        FeatureDefinition(part.id, "Datum face", "plane", id="feature-1")
    )
    harness._active_part_id = part.id
    return feature


def test_stack_table_sync_uses_stable_feature_and_tolerance_ids():
    app = _app()
    harness = ProjectBridgeHarness()
    feature = _add_part_and_feature(harness)
    harness._add_table_row("Gap", 10.0, 0.2, 0.1, -1, 1.33)
    name_item = harness.table.item(0, 0)
    name_item.setData(harness.LINK_ROLE, {"feature_id": feature.id, "mode": "normal_offset"})

    harness._project_sync_stack_from_ui()

    stack = next(iter(harness.project.stacks.values()))
    tolerance = harness.project.tolerances[stack.terms[0].tolerance_id]
    assert tolerance.feature_id == "feature-1"
    assert tolerance.distribution.parameters == {"cpk": 1.33}
    assert stack.terms[0].sign == -1
    assert name_item.data(harness.TOLERANCE_ID_ROLE) == tolerance.id
    app.processEvents()


def test_stack_table_restores_links_from_project():
    app = _app()
    source = ProjectBridgeHarness()
    feature = _add_part_and_feature(source)
    source._add_table_row("Diameter", 8.0, 0.1, 0.0, 1, None)
    source.table.item(0, 0).setData(
        source.LINK_ROLE, {"feature_id": feature.id, "mode": "diametral"}
    )
    source._project_sync_stack_from_ui()

    restored = ProjectBridgeHarness()
    restored.project = Project.from_dict(source.project.to_dict())
    restored._project_restore_stack_to_ui()

    link = restored.table.item(0, 0).data(restored.LINK_ROLE)
    assert link == {"feature_id": "feature-1", "mode": "diametral"}
    assert restored.table.item(0, 0).data(restored.TOLERANCE_ID_ROLE)
    app.processEvents()


def test_saved_feature_signature_reattaches_after_geometry_reload():
    _app()
    harness = ProjectBridgeHarness()
    part = harness.project.add_part(PartDefinition("Plate", id="part-1"))
    harness._active_part_id = part.id
    points = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], dtype=float)
    original_info = {"type": "face", "index": 4, "points": points}
    feature_id = harness._project_register_feature(original_info, "Mounting plane")

    reloaded_info = {"type": "face", "index": 99, "points": points.copy()}
    harness._step_entity_info = {123: reloaded_info}
    harness._project_reattach_features()

    assert feature_id == reloaded_info["feature_id"]
    assert harness._project_find_entity_info(feature_id) is reloaded_info


def test_plane_and_circle_candidates_are_matched_by_saved_signature_kind():
    _app()
    harness = ProjectBridgeHarness()
    part = harness.project.add_part(PartDefinition("Plate", id="part-1"))
    harness._active_part_id = part.id
    plane_points = np.array([[0, 0, 0], [2, 0, 0], [0, 2, 0], [2, 2, 0]], dtype=float)
    plane_info = {"type": "face", "index": 0, "points": plane_points}
    plane_id = harness._project_register_feature(plane_info, "Plane")

    circle_points = np.array([[1, 0, 0], [0, 1, 0], [-1, 0, 0], [0, -1, 0]], dtype=float)
    circle = {
        "center": np.array([0, 0, 0], dtype=float),
        "normal": np.array([0, 0, 1], dtype=float),
        "radius": 1.0,
    }
    circle_info = {"type": "edge", "index": 1, "points": circle_points, "circle": circle}
    circle_id = harness._project_register_feature(circle_info, "Circle")

    unrelated_circle = {**circle, "radius": 2.0}
    reloaded_plane = {
        "type": "face", "index": 10, "points": plane_points.copy(),
        "circle": unrelated_circle,
    }
    reloaded_circle = {"type": "edge", "index": 11, "points": circle_points.copy(), "circle": circle}
    harness._step_entity_info = {1: reloaded_plane, 2: reloaded_circle}
    harness._project_reattach_features()

    assert harness._project_find_entity_info(plane_id) is reloaded_plane
    assert harness._project_find_entity_info(circle_id) is reloaded_circle
