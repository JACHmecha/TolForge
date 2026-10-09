"""Table appearance must not edit values, identities, or precision editors."""

import os

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import (
    QApplication, QStyleOptionViewItem, QStyledItemDelegate, QTableView,
    QTableWidget, QTableWidgetItem,
)

from gui.gdt_mixin import PATTERN_RAW_VALUE_ROLE, PatternNumericItem
from gui.table_presentation import configure_table, fit_table_columns

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module", autouse=True)
def application():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.mark.parametrize("use_model", [False, True])
def test_presentation_preserves_cell_data_and_emits_no_model_changes(use_model):
    values = ["Very long feature name " * 30, "-0.000000123456789", "Review detail " * 30]
    if use_model:
        table = QTableView()
        model = QStandardItemModel(1, 3)
        table.setModel(model)
        for column, value in enumerate(values):
            model.setItem(0, column, QStandardItem(value))
    else:
        table = QTableWidget(1, 3)
        for column, value in enumerate(values):
            table.setItem(0, column, QTableWidgetItem(value))
        model = table.model()
    model.setData(model.index(0, 0), "stable-feature-id", Qt.UserRole)
    changed = QSignalSpy(model.dataChanged)
    configure_table(table, numeric_columns=(1,), text_columns=(0, 2))
    fit_table_columns(table)
    assert changed.count() == 0
    assert [model.data(model.index(0, column), Qt.EditRole) for column in range(3)] == values
    assert model.data(model.index(0, 0), Qt.UserRole) == "stable-feature-id"
    assert table.columnWidth(0) <= 180
    assert table.columnWidth(1) <= 140
    assert table.columnWidth(2) <= 240
    assert table.rowHeight(0) == 36
    index = model.index(0, 1)
    option = QStyleOptionViewItem()
    delegate = table.itemDelegateForColumn(1)
    delegate.initStyleOption(option, index)
    assert option.displayAlignment == Qt.AlignRight | Qt.AlignVCenter
    table.close()


def test_numeric_alignment_keeps_full_precision_edit_role():
    table = QTableWidget(1, 2)
    item = PatternNumericItem(10.1234567890123)
    table.setItem(0, 1, item)
    changed = QSignalSpy(table.itemChanged)
    configure_table(table, numeric_columns=(1,), text_columns=(0,))
    assert changed.count() == 0
    index = table.model().index(0, 1)
    delegate = table.itemDelegateForColumn(1)
    editor = delegate.createEditor(table, QStyleOptionViewItem(), index)
    delegate.setEditorData(editor, index)
    assert editor.text() == "10.1234567890123"
    delegate.setModelData(editor, table.model(), index)
    assert item.data(PATTERN_RAW_VALUE_ROLE) == 10.1234567890123
    editor.deleteLater()
    table.close()


def test_specialized_editors_remain_installed():
    class PrecisionDelegate(QStyledItemDelegate):
        pass

    table = QTableWidget(1, 3)
    specialized = PrecisionDelegate(table)
    table.setItemDelegateForColumn(1, specialized)
    configure_table(table, numeric_columns=(1, 2))
    assert table.itemDelegateForColumn(1) is specialized
    assert table.itemDelegateForColumn(2) is not None
    configure_table(table, numeric_columns=(1,))
    assert table.itemDelegateForColumn(1) is specialized
    assert table.itemDelegateForColumn(2) is None
    global_delegate = PrecisionDelegate(table)
    table.setItemDelegate(global_delegate)
    configure_table(table, numeric_columns=(1, 2))
    assert table.itemDelegate() is global_delegate
    assert table.itemDelegateForColumn(2) is None
    table.close()
