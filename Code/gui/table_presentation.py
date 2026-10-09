"""Shared table presentation without changing engineering cell data."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QStyledItemDelegate


class NumericAlignmentDelegate(QStyledItemDelegate):
    """Align the painted value and editor while retaining the model's EditRole."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.displayAlignment = Qt.AlignRight | Qt.AlignVCenter

    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        if editor is not None and hasattr(editor, "setAlignment"):
            editor.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return editor


def configure_table(table, *, numeric_columns=(), text_columns=()):
    """Use one table treatment; preserve explicit delegates and all model roles.

    Numeric alignment is a view concern. Writing TextAlignmentRole into existing
    items would emit edit signals and invalidate engineering reports, so normal
    columns use a delegate instead. Specialized editors remain in place.
    """
    numeric_columns = frozenset(numeric_columns)
    owned_delegates = getattr(table, "_presentation_numeric_delegates", {})
    for column, delegate in tuple(owned_delegates.items()):
        if column not in numeric_columns:
            if table.itemDelegateForColumn(column) is delegate:
                table.setItemDelegateForColumn(column, None)
            delegate.deleteLater()
            del owned_delegates[column]
    table._presentation_numeric_delegates = owned_delegates
    table._presentation_numeric_columns = numeric_columns
    table._presentation_text_columns = frozenset(text_columns)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setWordWrap(False)
    table.setTextElideMode(Qt.ElideRight)
    rows = table.verticalHeader()
    rows.setDefaultSectionSize(36)
    rows.setMinimumSectionSize(36)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.Interactive)
    header.setMinimumSectionSize(64)
    header.setStretchLastSection(False)

    # A custom global delegate can also own precision or validation behavior.
    if type(table.itemDelegate()) is QStyledItemDelegate:
        for column in table._presentation_numeric_columns:
            if table.itemDelegateForColumn(column) is None:
                delegate = NumericAlignmentDelegate(table)
                table.setItemDelegateForColumn(column, delegate)
                owned_delegates[column] = delegate
    fit_table_columns(table)


def fit_table_columns(table):
    """Fit contents within readable bounds; wide data scrolls inside the table.

    Use the model API so this works for both QTableWidget and QTableView. Hosts
    that only construct a table in a focused harness still receive safe bounds.
    """
    model = table.model()
    if model is None:
        return
    numeric = getattr(table, "_presentation_numeric_columns", frozenset())
    text = getattr(table, "_presentation_text_columns", frozenset())
    table.resizeColumnsToContents()
    for column in range(model.columnCount()):
        if column in numeric:
            minimum, maximum = 88, 140
        elif column in text:
            minimum, maximum = 120, 180 if column == 0 else 240
        else:
            minimum, maximum = 88, 240
        table.setColumnWidth(column, max(minimum, min(maximum, table.columnWidth(column))))
