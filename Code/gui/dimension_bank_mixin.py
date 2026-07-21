"""Mixin providing dimension table row management, the reusable dimension
bank (save/load templates to/from JSON), and initial seed data for
TolstackWindow.
"""

from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QInputDialog, QMessageBox, QTableWidgetItem
)

from tolstack import DimensionBank, DimensionTemplate


class DimensionBankMixin:
    """Expects the host class (TolstackWindow) to provide, from its own
    __init__: self.table, self.bank, self.bank_combo.
    """

    # ------------------------------------------------------------------
    # Seed data
    # ------------------------------------------------------------------

    def _seed_example(self):
        # cpk="" leaves the row in uniform mode; a row with cpk set shows
        # what a dimension with a known manufacturing process looks like.
        for name, nominal, tol_plus, tol_minus, sign, cpk in [
            ("Base", 25.0, 0.10, 0.05, "+", ""),
            ("Spacer", 12.5, 0.05, 0.05, "+", "1.33"),
            ("Bearing", 40.0, 0.20, 0.10, "-", ""),
        ]:
            self.add_row()
            r = self.table.rowCount() - 1
            values = [name, nominal, tol_plus, tol_minus, sign, cpk]
            for c, v in enumerate(values):
                if c == 4:
                    self._set_sign_switch(r, v)
                else:
                    self.table.setItem(r, c, QTableWidgetItem(str(v)))

    def _seed_bank(self):
        for name, nominal, tol_plus, tol_minus, cpk in [
            ("Base", 25.0, 0.10, 0.05, None),
            ("Spacer", 12.5, 0.05, 0.05, 1.33),
            ("Bearing", 40.0, 0.20, 0.10, None),
        ]:
            self.bank.add(DimensionTemplate(
                name=name, nominal=nominal,
                tol_plus=tol_plus, tol_minus=tol_minus, cpk=cpk
            ))
        self._refresh_bank_combo()

    # ------------------------------------------------------------------
    # Table row management
    # ------------------------------------------------------------------

    def add_row(self):
        self.table.insertRow(self.table.rowCount())
        self._set_sign_switch(self.table.rowCount() - 1, "+")

    def remove_row(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def _set_sign_switch(self, row: int, sign: str | int):
        checkbox = QCheckBox()
        checkbox.setChecked(sign in {1, "+"})
        checkbox.setToolTip("Toggle the dimension sign")
        checkbox.setStyleSheet(
            "QCheckBox { padding: 2px; }"
            "QCheckBox::indicator { width: 34px; height: 18px; border-radius: 9px; border: 1px solid #777; background: #f44336; color: white; font-weight: bold; }"
            "QCheckBox::indicator:checked { background: #4caf50; }"
            "QCheckBox::indicator:checked::before { content: '+'; }"
            "QCheckBox::indicator:unchecked::before { content: '-'; }"
        )
        self.table.setCellWidget(row, 4, checkbox)

    def _get_sign_from_row(self, row: int) -> str:
        widget = self.table.cellWidget(row, 4)
        if isinstance(widget, QCheckBox):
            return "+" if widget.isChecked() else "-"

        item = self.table.item(row, 4)
        if item is None:
            return "+"

        text = item.text().strip()
        if text in {"+", "1", "+1"}:
            return "+"
        if text in {"-", "-1"}:
            return "-"
        raise ValueError(f"Row {row + 1}: sign must be '+' or '-', not {text}.")

    def _add_table_row(self, name, nominal, tol_plus, tol_minus, sign, cpk):
        self.add_row()
        r = self.table.rowCount() - 1
        cpk_text = "" if cpk is None else str(cpk)
        values = [name, nominal, tol_plus, tol_minus, sign, cpk_text]
        for c, v in enumerate(values):
            if c == 4:
                self._set_sign_switch(r, v)
            else:
                self.table.setItem(r, c, QTableWidgetItem(str(v)))

    # ------------------------------------------------------------------
    # Dimension bank
    # ------------------------------------------------------------------

    def _refresh_bank_combo(self):
        self.bank_combo.clear()
        self.bank_combo.addItems(self.bank.names())

    def add_from_bank(self):
        name = self.bank_combo.currentText()
        if not name:
            QMessageBox.warning(self, "Empty bank", "The bank has no entries to add.")
            return

        sign_text, ok = QInputDialog.getItem(
            self, "Sign in this stack",
            f"Sign for '{name}' in the current stack:",
            ["+", "-"], 0, False
        )
        if not ok:
            return

        sign = "+" if sign_text == "+" else "-"
        template = self.bank.get(name)
        self._add_table_row(
            template.name, template.nominal, template.tol_plus,
            template.tol_minus, sign, template.cpk
        )

    def save_row_to_bank(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No row selected", "Select a row in the table first.")
            return

        try:
            name = self.table.item(row, 0).text().strip()
            nominal = float(self.table.item(row, 1).text())
            tol_plus = float(self.table.item(row, 2).text())
            tol_minus = float(self.table.item(row, 3).text())
        except (AttributeError, ValueError):
            QMessageBox.warning(self, "Invalid row", "This row has invalid or incomplete data.")
            return

        cpk_item = self.table.item(row, 5)
        cpk_text = cpk_item.text().strip() if cpk_item else ""
        cpk = None
        if cpk_text:
            try:
                cpk = float(cpk_text)
            except ValueError:
                QMessageBox.warning(self, "Invalid Cpk", f"Cpk '{cpk_text}' is not a valid number.")
                return

        template = DimensionTemplate(
            name=name, nominal=nominal, tol_plus=tol_plus, tol_minus=tol_minus, cpk=cpk
        )

        if name in self.bank.names():
            choice = QMessageBox.question(
                self, "Overwrite entry",
                f"'{name}' already exists in the bank. Overwrite it?"
            )
            if choice != QMessageBox.Yes:
                return
            self.bank.add(template, overwrite=True)
        else:
            self.bank.add(template)

        self._refresh_bank_combo()

    def remove_from_bank(self):
        name = self.bank_combo.currentText()
        if not name:
            return
        self.bank.remove(name)
        self._refresh_bank_combo()

    def load_bank_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load bank", "", "JSON files (*.json)")
        if not path:
            return
        try:
            self.bank = DimensionBank.load(path)
        except Exception as e:
            QMessageBox.warning(self, "Could not load bank", str(e))
            return
        self._refresh_bank_combo()

    def save_bank_file(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save bank", "bank.json", "JSON files (*.json)")
        if not path:
            return
        try:
            self.bank.save(path)
        except Exception as e:
            QMessageBox.warning(self, "Could not save bank", str(e))
