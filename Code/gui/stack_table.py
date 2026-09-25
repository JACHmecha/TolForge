"""Model-backed engineering stack editor.

Text, sign and feature/project identifiers belong to ``StackTableModel``.
The view keeps a small item-style facade while project and viewport callers
migrate to model APIs. Facades use persistent indexes, so a slider or caller
holding a cell continues to address the same dimension after row removal.
Only the optional 3D-preview slider remains an index widget.
"""

from copy import deepcopy

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt, Signal
from PySide6.QtWidgets import QTableView


DEFAULT_HEADERS = ("Name", "Nominal", "Tol +", "Tol -", "+/-", "Cpk", "3D Value")
SIGN_COLUMN = 4
PREVIEW_COLUMN = 6


def _sign_text(value):
    if value in (1, "+", "+1", "1"):
        return "+"
    if value in (-1, "-", "−", "-1"):
        return "-"
    raise ValueError(f"Sign must be '+' or '-', not {value!r}.")


class StackTableModel(QAbstractTableModel):
    """Owns editable strings and arbitrary Qt metadata roles for stack rows.

    Numeric text is deliberately retained while users edit it; the analysis
    service validates complete rows before calculation or project persistence.
    """

    def __init__(self, rows=0, columns=len(DEFAULT_HEADERS), parent=None):
        super().__init__(parent)
        self._headers = list(DEFAULT_HEADERS[:columns])
        self._headers.extend("" for _ in range(columns - len(self._headers)))
        self._rows = [self._empty_row() for _ in range(rows)]

    def _empty_row(self):
        return [{int(Qt.EditRole): "+" if column == SIGN_COLUMN else ""}
                for column in range(len(self._headers))]

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._headers)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        cell = self._rows[index.row()][index.column()]
        value = cell.get(int(Qt.EditRole), "")
        if role in (Qt.DisplayRole, Qt.EditRole):
            return "−" if index.column() == SIGN_COLUMN and role == Qt.DisplayRole and value == "-" else value
        if role == Qt.CheckStateRole and index.column() == SIGN_COLUMN:
            return Qt.Checked if value == "+" else Qt.Unchecked
        if role == Qt.TextAlignmentRole and index.column() in (1, 2, 3, 5):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return deepcopy(cell.get(int(role)))

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid():
            return False
        role = int(role)
        roles = [role]
        if role in (int(Qt.DisplayRole), int(Qt.EditRole), int(Qt.CheckStateRole)):
            if role == int(Qt.CheckStateRole):
                if index.column() != SIGN_COLUMN:
                    return False
                if value not in (Qt.Checked, Qt.Unchecked, Qt.Checked.value, Qt.Unchecked.value):
                    return False
                value = "+" if value in (Qt.Checked, Qt.Checked.value) else "-"
            if index.column() == SIGN_COLUMN:
                try:
                    value = _sign_text(value)
                except ValueError:
                    return False
            else:
                value = str(value)
            role = int(Qt.EditRole)
            roles = [int(Qt.DisplayRole), int(Qt.EditRole)]
            if index.column() == SIGN_COLUMN:
                roles.append(int(Qt.CheckStateRole))
        cell = self._rows[index.row()][index.column()]
        if cell.get(role) == value:
            return True
        cell[role] = deepcopy(value)
        self.dataChanged.emit(index, index, roles)
        return True

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() == SIGN_COLUMN:
            return flags | Qt.ItemIsUserCheckable
        if index.column() != PREVIEW_COLUMN:
            flags |= Qt.ItemIsEditable
        return flags

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and 0 <= section < len(self._headers):
            return self._headers[section]
        if orientation == Qt.Vertical and 0 <= section < len(self._rows):
            return str(section + 1)
        return None

    def set_headers(self, labels):
        if len(labels) != self.columnCount():
            raise ValueError("Header count must match the stack table columns.")
        self._headers = list(labels)
        if labels:
            self.headerDataChanged.emit(Qt.Horizontal, 0, len(labels) - 1)

    def insertRows(self, row, count, parent=QModelIndex()):
        if parent.isValid() or count <= 0 or not 0 <= row <= len(self._rows):
            return False
        self.beginInsertRows(parent, row, row + count - 1)
        self._rows[row:row] = [self._empty_row() for _ in range(count)]
        self.endInsertRows()
        return True

    def removeRows(self, row, count, parent=QModelIndex()):
        if parent.isValid() or count <= 0 or row < 0 or row + count > len(self._rows):
            return False
        self.beginRemoveRows(parent, row, row + count - 1)
        del self._rows[row:row + count]
        self.endRemoveRows()
        return True

    def rows_snapshot(self):
        """Immutable text snapshot for parsing outside the widget layer."""
        return tuple(tuple(cell[int(Qt.EditRole)] for cell in row[:PREVIEW_COLUMN])
                     for row in self._rows)


class StackTableCell:
    """Live cell handle for project/link callers; stores no duplicate data."""

    def __init__(self, model, index):
        self._model = model
        self._index = QPersistentModelIndex(index)

    def row(self):
        return self._index.row()

    def column(self):
        return self._index.column()

    def text(self):
        return self.data(Qt.EditRole) or ""

    def setText(self, value):
        self.setData(Qt.EditRole, value)

    def data(self, role):
        return self._model.data(self._index, role) if self._index.isValid() else None

    def setData(self, role, value):
        return self._model.setData(self._index, value, role)


class StackTableView(QTableView):
    """Stack model view with the narrow legacy API used by GUI mixins."""

    itemChanged = Signal(object)
    itemSelectionChanged = Signal()
    currentCellChanged = Signal(int, int, int, int)

    def __init__(self, rows=0, columns=len(DEFAULT_HEADERS), parent=None):
        super().__init__(parent)
        self.setModel(StackTableModel(rows, columns, self))
        self.model().dataChanged.connect(self._emit_item_changes)
        self.selectionModel().currentChanged.connect(self._emit_current_change)
        self.selectionModel().selectionChanged.connect(lambda *_: self.itemSelectionChanged.emit())

    def _emit_item_changes(self, top_left, bottom_right, _roles):
        for row in range(top_left.row(), bottom_right.row() + 1):
            for column in range(top_left.column(), bottom_right.column() + 1):
                self.itemChanged.emit(self.item(row, column))

    def _emit_current_change(self, current, previous):
        self.currentCellChanged.emit(current.row(), current.column(), previous.row(), previous.column())

    def rowCount(self):
        return self.model().rowCount()

    def columnCount(self):
        return self.model().columnCount()

    def insertRow(self, row):
        return self.model().insertRow(row)

    def removeRow(self, row):
        return self.model().removeRow(row)

    def setRowCount(self, count):
        if count < 0:
            raise ValueError("Row count cannot be negative.")
        existing = self.rowCount()
        if count < existing:
            self.model().removeRows(count, existing - count)
        elif count > existing:
            self.model().insertRows(existing, count - existing)

    def setHorizontalHeaderLabels(self, labels):
        self.model().set_headers(labels)

    def item(self, row, column):
        index = self.model().index(row, column)
        return StackTableCell(self.model(), index) if index.isValid() else None

    def row(self, item):
        return item.row() if isinstance(item, StackTableCell) and item._model is self.model() else -1

    def set_text(self, row, column, value):
        return self.model().setData(self.model().index(row, column), str(value))

    def setItem(self, row, column, item):
        """Import legacy text items; subsequent changes use ``item(row, col)``.

        Preserve the standard presentation roles and existing feature/term
        identifier roles when importing a legacy QTableWidgetItem. New code
        can store any custom role directly through the model or cell facade.
        """
        index = self.model().index(row, column)
        if not index.isValid():
            return
        self.model().setData(index, item.text())
        for role in (Qt.DecorationRole, Qt.ToolTipRole, Qt.StatusTipRole,
                     Qt.WhatsThisRole, Qt.FontRole, Qt.BackgroundRole,
                     Qt.ForegroundRole, Qt.UserRole, Qt.UserRole + 100,
                     Qt.UserRole + 201, Qt.UserRole + 202):
            value = item.data(role)
            if value is not None:
                self.model().setData(index, value, role)

    def set_sign(self, row, sign):
        return self.model().setData(self.model().index(row, SIGN_COLUMN), _sign_text(sign))

    def sign(self, row):
        index = self.model().index(row, SIGN_COLUMN)
        if not index.isValid():
            raise ValueError(f"Row {row + 1} does not exist.")
        return self.model().data(index, Qt.EditRole)

    def currentRow(self):
        return self.currentIndex().row()

    def setCurrentCell(self, row, column):
        self.setCurrentIndex(self.model().index(row, column))

    def cellWidget(self, row, column):
        return self.indexWidget(self.model().index(row, column))

    def setCellWidget(self, row, column, widget):
        self.setIndexWidget(self.model().index(row, column), widget)

    def removeCellWidget(self, row, column):
        self.setIndexWidget(self.model().index(row, column), None)
