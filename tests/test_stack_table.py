"""Stack editor regressions: shared model state and stable row ownership."""

import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QTableView, QTableWidget, QTableWidgetItem

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

from gui.dimension_bank_mixin import DimensionBankMixin
from gui.project_mixin import ProjectMixin
from gui.stack_table import StackTableModel, StackTableView
from tolstack import Project


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def table(app):
    view = StackTableView()
    yield view
    view.close()
    app.processEvents()


def test_model_edit_role_signs_and_text_snapshot(table):
    assert isinstance(table, QTableView)
    assert not isinstance(table, QTableWidget)
    assert isinstance(table.model(), StackTableModel)
    table.insertRow(0)
    changed = []
    table.itemChanged.connect(lambda item: changed.append((item.row(), item.column())))
    assert table.model().setData(table.model().index(0, 0), "Gap")
    table.set_text(0, 1, "12.0")
    table.set_text(0, 2, "0.1")
    table.set_text(0, 3, "0.2")
    table.set_sign(0, -1)
    assert table.item(0, 0).text() == "Gap"
    assert table.model().data(table.model().index(0, 4), Qt.CheckStateRole) == Qt.Unchecked
    assert table.model().rows_snapshot() == (("Gap", "12.0", "0.1", "0.2", "-", ""),)
    table.item(0, 2).setText("0.25")
    assert table.model().data(table.model().index(0, 2), Qt.EditRole) == "0.25"
    assert (0, 4) in changed


def test_sign_can_be_toggled_by_keyboard_and_notifies_preview(table):
    table.insertRow(0)
    table.setCurrentCell(0, 4)
    changed = []
    table.itemChanged.connect(lambda item: changed.append(item.column()))
    QTest.keyClick(table, Qt.Key_Space)
    assert table.sign(0) == "-"
    assert changed == [4]
    QTest.keyClick(table, Qt.Key_Space)
    assert table.sign(0) == "+"
    assert table.cellWidget(0, 4) is None


def test_metadata_and_slider_handles_follow_row_insertion_and_removal(table, app):
    table.setRowCount(2)
    table.set_text(0, 0, "First")
    table.set_text(1, 0, "Linked")
    linked = table.item(1, 0)
    linked.setData(Qt.UserRole + 100, {"feature_id": "f1", "mode": "normal_offset"})
    linked.setData(Qt.UserRole + 201, "tolerance-1")
    linked.setData(Qt.UserRole + 202, "term-1")
    linked.setData(Qt.UserRole + 999, {"custom": [1, 2]})
    slider = QLabel("preview")
    table.setCellWidget(1, 6, slider)
    table.insertRow(0)
    assert table.row(linked) == 2
    assert table.cellWidget(2, 6) is slider
    table.removeRow(0)
    table.removeRow(0)
    app.processEvents()
    assert table.row(linked) == 0
    assert table.cellWidget(0, 6) is slider
    linked.setText("Edited")
    assert table.item(0, 0).text() == "Edited"
    assert linked.data(Qt.UserRole + 100)["feature_id"] == "f1"
    assert linked.data(Qt.UserRole + 201) == "tolerance-1"
    assert linked.data(Qt.UserRole + 202) == "term-1"
    assert linked.data(Qt.UserRole + 999) == {"custom": [1, 2]}
    table.removeRow(0)
    assert table.row(linked) == -1
    assert linked.data(Qt.UserRole + 100) is None
    assert not linked.setData(Qt.EditRole, "orphan")


def test_current_row_signals_and_clear(table):
    table.setRowCount(2)
    current = []
    selection = []
    table.currentCellChanged.connect(lambda *args: current.append(args))
    table.itemSelectionChanged.connect(lambda: selection.append(True))
    table.setCurrentCell(1, 0)
    assert table.currentRow() == 1
    assert current[-1][:2] == (1, 0)
    assert selection
    table.setRowCount(0)
    assert table.currentRow() == -1
    assert table.item(0, 0) is None
    assert table.model().rows_snapshot() == ()


def test_model_rejects_invalid_structure_and_signs(table):
    model = table.model()
    assert not model.insertRows(-1, 1)
    assert not model.removeRows(0, 1)
    assert not model.setData(QModelIndex(), "invalid")
    table.insertRow(0)
    assert not model.setData(model.index(0, 4), "invalid sign")
    assert table.sign(0) == "+"
    assert model.rowCount(model.index(0, 0)) == 0
    assert model.columnCount(model.index(0, 0)) == 0
    assert not (model.flags(model.index(0, 6)) & Qt.ItemIsEditable)


def test_legacy_item_import_keeps_project_identifiers(table):
    table.insertRow(0)
    item = QTableWidgetItem("Existing dimension")
    item.setData(Qt.UserRole + 201, "tolerance-id")
    item.setData(Qt.UserRole + 202, "term-id")
    table.setItem(0, 0, item)
    assert table.item(0, 0).text() == "Existing dimension"
    assert table.item(0, 0).data(Qt.UserRole + 201) == "tolerance-id"
    assert table.item(0, 0).data(Qt.UserRole + 202) == "term-id"


class StackBridge(DimensionBankMixin, ProjectMixin):
    LINK_ROLE = Qt.UserRole + 100

    def __init__(self, table):
        self.table = table
        self.project = Project("Model bridge")


def test_project_sync_and_restore_use_same_model_data(table):
    bridge = StackBridge(table)
    bridge._add_table_row("Gap", 8.0, 0.2, 0.1, -1, 1.33)
    bridge._project_sync_stack_from_ui()
    name = table.item(0, 0)
    tolerance_id = name.data(bridge.TOLERANCE_ID_ROLE)
    term_id = name.data(bridge.STACK_TERM_ID_ROLE)
    assert tolerance_id and term_id
    table.model().setData(table.model().index(0, 1), "8.5")
    table.set_sign(0, "+")
    bridge._project_sync_stack_from_ui()
    assert bridge.project.tolerances[tolerance_id].nominal == 8.5
    assert next(iter(bridge.project.stacks.values())).terms[0].id == term_id
    bridge.project = Project.from_dict(bridge.project.to_dict())
    bridge._project_restore_stack_to_ui()
    assert table.sign(0) == "+"
    assert float(table.item(0, 1).text()) == 8.5
    assert table.item(0, 0).data(bridge.TOLERANCE_ID_ROLE) == tolerance_id
    assert table.item(0, 0).data(bridge.STACK_TERM_ID_ROLE) == term_id
