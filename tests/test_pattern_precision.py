"""CAD pattern display/edit/persistence boundaries preserve engineering precision."""

import os
import sys
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QComboBox, QLabel, QLineEdit, QStyleOptionViewItem, QTableWidget,
)

from gui.gdt_mixin import GdtMixin, PATTERN_RAW_VALUE_ROLE, PatternNumericItem
from gui.project_mixin import ProjectMixin
from tolstack import DatumReference, DatumSystem, FeatureDefinition, PartDefinition, Project
from tolstack.gdt import evaluate_pattern_nominal, run_pattern_monte_carlo


@pytest.fixture(scope="module", autouse=True)
def qt_application():
    app = QApplication.instance() or QApplication([])
    yield app


class Frame:
    def to_local_xy(self, point):
        return float(point[0]), float(point[1])


class PatternHarness(ProjectMixin, GdtMixin):
    """Use production pattern rows and project adapters without a native viewer."""

    def __init__(self):
        self._project_init_state()
        self.table = QTableWidget(0, 7)
        self.pattern_table = QTableWidget(0, 10)
        self.pattern_table.itemChanged.connect(self._invalidate_gdt_results)
        self.gdt_base_tolerance_input = QLineEdit("0.00005")
        self.gdt_mmc_size_input = QLineEdit("10.0")
        self.gdt_lmc_size_input = QLineEdit("10.2")
        self.gdt_modifier_combo = QComboBox()
        self.gdt_modifier_combo.addItems(["RFS", "MMC", "LMC"])
        self.gdt_feature_kind_combo = QComboBox()
        self.gdt_feature_kind_combo.addItems(["hole", "pin"])
        self.step_status_label = QLabel()
        self._current_drf = Frame()
        self._datum_slot = {name: {} for name in ("Primary", "Secondary", "Tertiary")}

    def _measure_ensure_circle_fit(self, info):
        pass

    def _project_sync_datums_from_ui(self):
        pass

    def _project_sync_stack_from_ui(self):
        pass

    def _study_capture(self):
        pass

    def _project_update_title(self):
        pass


def populate_pattern(harness):
    part = harness.project.add_part(PartDefinition("Plate", id="part-1"))
    feature = harness.project.add_feature(
        FeatureDefinition(part.id, "Hole 1", "circle", id="feature-1")
    )
    datum = harness.project.add_datum_reference(DatumReference(feature.id, "A", id="datum-1"))
    system = harness.project.add_datum_system(DatumSystem("DRF", [datum.id], id="drf-1"))
    harness._active_part_id = part.id
    harness._active_datum_system_id = system.id
    y = 1.234567891234
    diameter = 10.1234567890123
    harness._entity_by_feature_id[feature.id] = {
        "feature_id": feature.id,
        "type": "edge", "index": 1,
        "circle": {
            "center": np.array([0.00004, y, 0.0]),
            "normal": np.array([0.0, 0.0, 1.0]),
            "radius": diameter / 2,
        },
    }
    harness._pattern_add_row("Hole 1", 0.0, y, 0.00004, y, diameter, feature.id)
    return harness._entity_by_feature_id


def assert_failure(control):
    evaluation = evaluate_pattern_nominal(control)[0][1]
    assert not evaluation.passes
    assert not evaluation.position_conforming
    return evaluation


def test_tiny_offset_and_diameter_remain_exact_at_every_display_precision():
    harness = PatternHarness()
    populate_pattern(harness)
    assert harness.pattern_table.item(0, 3).text() == "0.0000"
    assert harness.pattern_table.item(0, 5).text() == "10.1235"
    original = harness._pattern_read_control()
    assert_failure(original)
    assert original.features[0].actual_x == 0.00004
    assert original.features[0].basic_y == 1.234567891234
    assert original.features[0].size_nominal == 10.1234567890123
    original_samples = run_pattern_monte_carlo(original, iterations=20, seed=42)
    assert original_samples.pattern_fail_rate == 1.0

    for decimals in (0, 2, 8, 15):
        for column in range(1, 9):
            harness.pattern_table.item(0, column).set_display_precision(decimals)
        assert harness._pattern_read_control() == original
        assert assert_failure(harness._pattern_read_control()).position_error == 0.00008
        assert harness._project_build_pattern_control() == original
        samples = run_pattern_monte_carlo(harness._pattern_read_control(), iterations=20, seed=42)
        np.testing.assert_array_equal(samples.worst_feature_margin, original_samples.worst_feature_margin)
        assert samples.pattern_fail_rate == 1.0


@pytest.mark.parametrize("column, edit_text", [(2, "1.234567891234"), (5, "10.1234567890123")])
def test_editor_receives_raw_value_and_unchanged_acceptance_does_not_round_it(column, edit_text):
    harness = PatternHarness()
    populate_pattern(harness)
    item = harness.pattern_table.item(0, column)
    index = harness.pattern_table.model().index(0, column)
    delegate = harness.pattern_table.itemDelegate()
    editor = delegate.createEditor(harness.pattern_table, QStyleOptionViewItem(), index)
    delegate.setEditorData(editor, index)
    assert editor.text() == edit_text
    delegate.setModelData(editor, harness.pattern_table.model(), index)
    assert item.data(PATTERN_RAW_VALUE_ROLE) == float(edit_text)
    assert_failure(harness._pattern_read_control())
    editor.deleteLater()


def test_text_and_model_edits_replace_raw_values_and_clear_invalid_values():
    harness = PatternHarness()
    populate_pattern(harness)
    item = harness.pattern_table.item(0, 1)
    item.setText("0.000000123456789")
    assert harness._pattern_read_features()[0].basic_x == 0.000000123456789
    assert_failure(harness._pattern_read_control())
    harness.pattern_table.model().setData(
        harness.pattern_table.model().index(0, 1), "0.00001", Qt.EditRole
    )
    assert item.data(PATTERN_RAW_VALUE_ROLE) == 0.00001
    assert assert_failure(harness._pattern_read_control()).position_error == pytest.approx(0.00006)
    for invalid in ("invalid", ""):
        item.setText(invalid)
        assert item.data(PATTERN_RAW_VALUE_ROLE) is None
        with pytest.raises(ValueError):
            harness._pattern_read_features()
        with pytest.raises(ValueError):
            harness._project_sync_position_from_ui()
    item.setText("0.0")
    harness.pattern_table.item(0, 6).setText("0.0000000123456789")
    assert harness._pattern_read_features()[0].position_tol_plus_x == 0.0000000123456789
    harness.pattern_table.item(0, 6).setText("")
    assert harness._pattern_read_features()[0].position_tol_plus_x == 0.0
    assert_failure(harness._pattern_read_control())


@pytest.mark.parametrize("basic_x_text", ["0.0", "0.000000123456789"])
def test_save_load_and_geometry_restore_preserve_values_disposition_and_ids(tmp_path, basic_x_text):
    source = PatternHarness()
    geometry = populate_pattern(source)
    source.pattern_table.item(0, 1).setText(basic_x_text)
    source.pattern_table.item(0, 5).setText("10.1234567890987")
    for column in (6, 7, 8):
        source.pattern_table.item(0, column).setText("0.0000000123456789")
    expected = source._pattern_read_control()
    assert_failure(expected)
    path = tmp_path / "precise.tolforge.json"
    source._project_save_to(str(path))
    assert source._project_path == str(path)
    saved = source.project.to_dict()
    source_name = source.pattern_table.item(0, 0)
    roles = (source.PATTERN_FEATURE_ID_ROLE, source.PATTERN_MEMBER_ID_ROLE,
             source.PATTERN_SIZE_TOLERANCE_ID_ROLE, source.PATTERN_X_TOLERANCE_ID_ROLE,
             source.PATTERN_Y_TOLERANCE_ID_ROLE)
    ids = [source_name.data(role) for role in roles]
    assert all(ids)

    restored = PatternHarness()
    restored.project = Project.load(path)
    restored._active_datum_system_id = "drf-1"
    restored._active_position_control_id = source._active_position_control_id
    restored._entity_by_feature_id = geometry
    restored._project_restore_position_control()
    assert restored._pattern_read_control() == expected
    assert restored._project_build_pattern_control() == expected
    assert_failure(restored._pattern_read_control())
    assert [restored.pattern_table.item(0, 0).data(role) for role in roles] == ids
    assert restored.project.to_dict() == saved


def test_pick_coordinate_defaults_are_round_trip_text(monkeypatch):
    harness = PatternHarness()
    geometry = populate_pattern(harness)
    harness.pattern_table.setRowCount(0)
    info = geometry["feature-1"]
    info["circle"]["center"] = np.array([0.00004, 1.234567891234, 0.0])
    prompts = []

    def accept_default(_parent, title, _label, **kwargs):
        prompts.append((title, kwargs["text"]))
        return kwargs["text"], True

    monkeypatch.setattr("gui.gdt_mixin.QInputDialog.getText", accept_default)
    harness._pattern_consume_pick(info)
    feature = harness._pattern_read_features()[0]
    assert prompts[1:] == [("Basic X", "4e-05"), ("Basic Y", "1.234567891234")]
    assert feature.basic_x == feature.actual_x == 0.00004
    assert feature.basic_y == feature.actual_y == 1.234567891234
    assert isinstance(harness.pattern_table.item(0, 1), PatternNumericItem)
