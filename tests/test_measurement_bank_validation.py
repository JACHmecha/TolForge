"""Measured values retain precision and cannot bypass bank validation."""

import sys
from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication, QLineEdit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

from gui.measurement_mixin import MeasurementMixin
from gui.dimension_bank_mixin import DimensionBankMixin
from gui.analysis_mixin import AnalysisMixin
from gui.project_mixin import ProjectMixin
from gui.stack_table import StackTableView
from gui.stack_link_mixin import StackLinkMixin
from tolstack import DimensionBank, Project


class MeasurementBankHarness(MeasurementMixin):
    def __init__(self):
        self.bank = DimensionBank()
        self.measure_tol_plus_input = QLineEdit("0.000000123456789")
        self.measure_tol_minus_input = QLineEdit("0.0000000987654321")
        self._measure_slot = {
            "A": {"type": "edge", "index": 1, "circle": {"radius": 5.000000123456789}},
            "B": {"type": "edge", "index": 2},
        }
        self._measure_last = {
            "circle_center_distance": 0.000040123456789,
            "normal_distance": None, "angle_deg": None, "min_distance": 0.0,
        }

    def _refresh_bank_combo(self):
        pass


class StackBankHarness(DimensionBankMixin, ProjectMixin, AnalysisMixin):
    LINK_ROLE = StackLinkMixin.LINK_ROLE

    def __init__(self, bank):
        self.bank = bank
        self.table = StackTableView()
        self.project = Project("Measured precision")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def harness(app, monkeypatch):
    instance = MeasurementBankHarness()
    messages = []
    monkeypatch.setattr("gui.measurement_mixin.QInputDialog.getText", lambda *a, **kw: ("Measured", True))
    monkeypatch.setattr("gui.measurement_mixin.QMessageBox.warning", lambda *a: messages.append(a[-1]))
    monkeypatch.setattr("gui.measurement_mixin.QMessageBox.information", lambda *a: None)
    return instance, messages


@pytest.mark.parametrize("method,expected", [
    ("add_measurement_to_bank", 0.000040123456789),
    ("add_circle_diameter_a_to_bank", 5.000000123456789 * 2),
])
def test_measured_values_survive_bank_and_stack_project_roundtrip(harness, method, expected, tmp_path):
    instance, messages = harness
    getattr(instance, method)()
    assert not messages
    entry = instance.bank.get("Measured")
    assert entry.nominal == expected
    bank_path = tmp_path / "measured-bank.json"
    instance.bank.save(bank_path)
    restored_bank = DimensionBank.load(bank_path)
    bridge = StackBankHarness(restored_bank)
    dimension = restored_bank.to_dimension("Measured")
    bridge._add_table_row(dimension.name, dimension.nominal, dimension.tol_plus,
                          dimension.tol_minus, dimension.sign, dimension.cpk)
    assert bridge._build_stack().dimensions[0].nominal == expected
    bridge._project_sync_stack_from_ui()
    bridge.project = Project.from_dict(bridge.project.to_dict())
    bridge._project_restore_stack_to_ui()
    restored_dimension = bridge._build_stack().dimensions[0]
    assert restored_dimension.nominal == expected
    assert restored_dimension.tol_plus == 0.000000123456789
    assert restored_dimension.tol_minus == 0.0000000987654321
    bridge.table.close()


@pytest.mark.parametrize("method", ["add_measurement_to_bank", "add_circle_diameter_a_to_bank"])
@pytest.mark.parametrize("invalid", ["nan", "inf", "-0.01", "invalid"])
def test_invalid_measured_tolerance_is_reported_without_adding_bank_entry(harness, method, invalid):
    instance, messages = harness
    instance.measure_tol_plus_input.setText(invalid)
    getattr(instance, method)()
    assert not instance.bank.entries
    assert messages


@pytest.mark.parametrize("method", ["add_measurement_to_bank", "add_circle_diameter_a_to_bank"])
def test_nonfinite_measured_nominal_is_reported_without_adding_bank_entry(harness, method):
    instance, messages = harness
    instance._measure_last["circle_center_distance"] = float("nan")
    instance._measure_slot["A"]["circle"]["radius"] = float("inf")
    getattr(instance, method)()
    assert not instance.bank.entries
    assert messages
