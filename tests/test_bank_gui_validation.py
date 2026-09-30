import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

from PySide6.QtWidgets import QApplication, QComboBox, QTableWidget, QTableWidgetItem

from gui import dimension_bank_mixin
from gui.dimension_bank_mixin import DimensionBankMixin
from tolstack.bank import DimensionBank, DimensionTemplate


class BankHarness(DimensionBankMixin):
    def __init__(self):
        self.bank = DimensionBank()
        self.bank_combo = QComboBox()
        self.table = QTableWidget(1, 6)
        for column, text in enumerate(("Spacer", "10", "0.1", "0.2", "+", "1.33")):
            self.table.setItem(0, column, QTableWidgetItem(text))
        self.table.setCurrentCell(0, 0)


@pytest.mark.parametrize("column,text", [
    (0, ""), (1, "NaN"), (1, "Infinity"), (2, "-0.1"),
    (3, "NaN"), (5, "0"), (5, "-1"), (5, "Infinity"),
])
def test_save_row_reports_invalid_engineering_data_without_adding_it(monkeypatch, column, text):
    app = QApplication.instance() or QApplication([])
    harness = BankHarness()
    harness.table.item(0, column).setText(text)
    warnings = []
    monkeypatch.setattr(dimension_bank_mixin.QMessageBox, "warning",
                        lambda parent, title, message: warnings.append(message))
    harness.save_row_to_bank()
    assert harness.bank.entries == {}
    assert len(warnings) == 1
    app.processEvents()


def test_adding_an_entry_mutated_after_load_reports_error_without_inserting_a_row(monkeypatch):
    app = QApplication.instance() or QApplication([])
    harness = BankHarness()
    harness.bank.add(DimensionTemplate("Spacer", 10, 0.1, 0.2))
    harness._refresh_bank_combo()
    harness.bank.entries["Spacer"].nominal = float("nan")
    warnings = []
    monkeypatch.setattr(dimension_bank_mixin.QMessageBox, "warning",
                        lambda parent, title, message: warnings.append(message))
    monkeypatch.setattr(dimension_bank_mixin.QInputDialog, "getItem", lambda *args: ("+", True))
    harness.add_from_bank()
    assert harness.table.rowCount() == 1
    assert len(warnings) == 1
    app.processEvents()
