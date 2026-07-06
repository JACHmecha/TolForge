"""Desktop GUI for tolstack (PySide6).

Window layout:
- Editable dimension table (name, nominal, tol+, tol-, sign, optional Cpk)
- Buttons to add/remove rows
- Dimension bank: reusable dimension templates (no sign) that can be
  pulled into the current stack, saved from a row, and persisted to/from
  a JSON file
- Analysis controls: method, global Cpk, target (for gap/interference)
- Results panel: text + histogram (matplotlib) for Monte Carlo, plus a
  fit assessment (gap / interference / mixed) against the target

Run with:
    python gui/app.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QPushButton, QLabel, QComboBox,
    QMessageBox, QGroupBox, QHeaderView, QLineEdit, QFileDialog,
    QInputDialog
)
from PySide6.QtCore import Qt

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from tolstack import Stack, Dimension, DimensionBank, DimensionTemplate, MonteCarloResult

COLUMNS = ["Name", "Nominal", "Tol +", "Tol -", "Sign (+1/-1)", "Cpk (optional)"]


class TolstackWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Tol-Forge: Tolerance Stack Analysis")
        self.resize(1000, 650)

        self.bank = DimensionBank()

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)

        # --- Left panel: dimension table ---
        left_panel = QVBoxLayout()

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        left_panel.addWidget(self.table)

        row_btns = QHBoxLayout()
        add_btn = QPushButton("+ Add dimension")
        add_btn.clicked.connect(self.add_row)
        remove_btn = QPushButton("- Remove selected")
        remove_btn.clicked.connect(self.remove_row)
        row_btns.addWidget(add_btn)
        row_btns.addWidget(remove_btn)
        left_panel.addLayout(row_btns)

        # --- Dimension bank panel ---
        bank_box = QGroupBox("Dimension bank")
        bank_layout = QVBoxLayout()

        bank_row1 = QHBoxLayout()
        self.bank_combo = QComboBox()
        bank_row1.addWidget(self.bank_combo, stretch=1)
        add_from_bank_btn = QPushButton("Add to stack")
        add_from_bank_btn.clicked.connect(self.add_from_bank)
        bank_row1.addWidget(add_from_bank_btn)
        remove_from_bank_btn = QPushButton("Remove from bank")
        remove_from_bank_btn.clicked.connect(self.remove_from_bank)
        bank_row1.addWidget(remove_from_bank_btn)
        bank_layout.addLayout(bank_row1)

        bank_row2 = QHBoxLayout()
        save_row_btn = QPushButton("Save selected row to bank")
        save_row_btn.clicked.connect(self.save_row_to_bank)
        bank_row2.addWidget(save_row_btn)
        load_bank_btn = QPushButton("Load bank...")
        load_bank_btn.clicked.connect(self.load_bank_file)
        bank_row2.addWidget(load_bank_btn)
        save_bank_btn = QPushButton("Save bank...")
        save_bank_btn.clicked.connect(self.save_bank_file)
        bank_row2.addWidget(save_bank_btn)
        bank_layout.addLayout(bank_row2)

        bank_box.setLayout(bank_layout)
        left_panel.addWidget(bank_box)

        method_box = QGroupBox("Analysis")
        method_layout = QHBoxLayout()
        self.method_combo = QComboBox()
        self.method_combo.addItems(["worst_case", "rss", "monte_carlo"])
        method_layout.addWidget(self.method_combo)

        method_layout.addWidget(QLabel("Global Cpk:"))
        self.default_cpk_input = QLineEdit()
        self.default_cpk_input.setPlaceholderText("empty = uniform")
        self.default_cpk_input.setMaximumWidth(90)
        method_layout.addWidget(self.default_cpk_input)

        method_layout.addWidget(QLabel("Target:"))
        self.target_input = QLineEdit()
        self.target_input.setPlaceholderText("0")
        self.target_input.setMaximumWidth(70)
        method_layout.addWidget(self.target_input)

        run_btn = QPushButton("Calculate")
        run_btn.clicked.connect(self.run_analysis)
        method_layout.addWidget(run_btn)
        method_box.setLayout(method_layout)
        left_panel.addWidget(method_box)

        root_layout.addLayout(left_panel, stretch=2)

        # --- Right panel: results ---
        right_panel = QVBoxLayout()

        self.result_label = QLabel("No results yet.")
        self.result_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.result_label.setWordWrap(True)
        self.result_label.setStyleSheet("font-family: monospace; font-size: 12px;")
        right_panel.addWidget(self.result_label)

        self.figure = Figure(figsize=(4, 3))
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setVisible(False)
        right_panel.addWidget(self.canvas)

        root_layout.addLayout(right_panel, stretch=3)

        # Seed example row + bank so the GUI doesn't start empty
        self._seed_example()
        self._seed_bank()

    # ------------------------------------------------------------------
    # Seed data
    # ------------------------------------------------------------------

    def _seed_example(self):
        # cpk="" leaves the row in uniform mode; a row with cpk set shows
        # what a dimension with a known manufacturing process looks like.
        for name, nominal, tol_plus, tol_minus, sign, cpk in [
            ("Base", 25.0, 0.10, 0.05, 1, ""),
            ("Spacer", 12.5, 0.05, 0.05, 1, "1.33"),
            ("Bearing", 40.0, 0.20, 0.10, -1, ""),
        ]:
            self.add_row()
            r = self.table.rowCount() - 1
            values = [name, nominal, tol_plus, tol_minus, sign, cpk]
            for c, v in enumerate(values):
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

    def remove_row(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def _add_table_row(self, name, nominal, tol_plus, tol_minus, sign, cpk):
        self.add_row()
        r = self.table.rowCount() - 1
        cpk_text = "" if cpk is None else str(cpk)
        values = [name, nominal, tol_plus, tol_minus, sign, cpk_text]
        for c, v in enumerate(values):
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
            ["+1", "-1"], 0, False
        )
        if not ok:
            return

        sign = int(sign_text)
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

    # ------------------------------------------------------------------
    # Stack construction from the table
    # ------------------------------------------------------------------

    def _build_stack(self) -> Stack:
        stack = Stack()
        for r in range(self.table.rowCount()):
            try:
                name = self.table.item(r, 0).text().strip()
                nominal = float(self.table.item(r, 1).text())
                tol_plus = float(self.table.item(r, 2).text())
                tol_minus = float(self.table.item(r, 3).text())
                sign = int(self.table.item(r, 4).text())
            except (AttributeError, ValueError):
                raise ValueError(f"Row {r + 1} has invalid or incomplete data.")

            if sign not in (1, -1):
                raise ValueError(f"Row {r + 1}: sign must be +1 or -1, not {sign}.")

            # Cpk column is optional: empty or missing cell -> None (uniform)
            cpk_item = self.table.item(r, 5)
            cpk_text = cpk_item.text().strip() if cpk_item else ""
            if cpk_text == "":
                cpk = None
            else:
                try:
                    cpk = float(cpk_text)
                except ValueError:
                    raise ValueError(f"Row {r + 1}: Cpk '{cpk_text}' is not a valid number.")
                if cpk <= 0:
                    raise ValueError(f"Row {r + 1}: Cpk must be greater than 0, not {cpk}.")

            stack.add_dimension(Dimension(
                name=name, nominal=nominal,
                tol_plus=tol_plus, tol_minus=tol_minus, sign=sign, cpk=cpk
            ))
        return stack

    def _get_default_cpk(self) -> float | None:
        """Reads the global Cpk field. Empty -> None (no default, falls back to uniform)."""
        text = self.default_cpk_input.text().strip()
        if text == "":
            return None
        try:
            value = float(text)
        except ValueError:
            raise ValueError(f"Global Cpk '{text}' is not a valid number.")
        if value <= 0:
            raise ValueError(f"Global Cpk must be greater than 0, not {value}.")
        return value

    def _get_target(self) -> float:
        """Reads the target field. Empty -> 0.0."""
        text = self.target_input.text().strip()
        if text == "":
            return 0.0
        try:
            return float(text)
        except ValueError:
            raise ValueError(f"Target '{text}' is not a valid number.")

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def run_analysis(self):
        try:
            stack = self._build_stack()
            target = self._get_target()
        except ValueError as e:
            QMessageBox.warning(self, "Invalid data", str(e))
            return

        if not stack.dimensions:
            QMessageBox.warning(self, "No data", "Add at least one dimension.")
            return

        method = self.method_combo.currentText()

        if method == "worst_case":
            result = stack.worst_case()
            fit = stack.assess_fit(result, target=target)
            self._show_stack_result(result, fit)
            self.canvas.setVisible(False)

        elif method == "rss":
            result = stack.rss()
            fit = stack.assess_fit(result, target=target)
            self._show_stack_result(result, fit)
            self.canvas.setVisible(False)

        elif method == "monte_carlo":
            try:
                default_cpk = self._get_default_cpk()
            except ValueError as e:
                QMessageBox.warning(self, "Invalid global Cpk", str(e))
                return

            result = stack.monte_carlo(default_cpk=default_cpk)
            fit = stack.assess_fit(result, target=target)

            # Show which model was used per dimension, so it's never a surprise
            model_lines = []
            for d in stack.dimensions:
                cpk = d.cpk if d.cpk is not None else default_cpk
                model = f"Cpk={cpk}" if cpk is not None else "uniform"
                model_lines.append(f"  {d.name}: {model}")

            self.result_label.setText(
                f"Monte Carlo (10,000 iterations)\n"
                + "\n".join(model_lines) + "\n"
                f"{'-' * 30}\n"
                f"Mean       : {result.mean:.4f}\n"
                f"Std Dev    : {result.std_dev:.4f}\n"
                f"Minimum    : {result.minimum:.4f}\n"
                f"Maximum    : {result.maximum:.4f}\n"
                + self._fit_text(fit)
            )
            self._plot_histogram(result.samples)
            self.canvas.setVisible(True)

    def _fit_text(self, fit) -> str:
        lines = [
            f"{'-' * 30}",
            f"Target       : {fit.target:.4f}",
            f"Verdict      : {fit.verdict.upper()}",
            f"Margin (min) : {fit.margin_min:+.4f}",
            f"Margin (max) : {fit.margin_max:+.4f}",
        ]
        if fit.interference_probability is not None:
            lines.append(f"P(interference): {fit.interference_probability * 100:.2f}%")
        return "\n".join(lines)

    def _show_stack_result(self, result, fit):
        self.result_label.setText(
            f"{'-' * 30}\n"
            f"Nominal : {result.nominal:.4f}\n"
            f"Maximum : {result.upper_limit:.4f}\n"
            f"Minimum : {result.lower_limit:.4f}\n"
            f"+Tol    : {result.upper_limit - result.nominal:.4f}\n"
            f"-Tol    : {result.nominal - result.lower_limit:.4f}\n"
            + self._fit_text(fit)
        )

    def _plot_histogram(self, samples):
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.hist(samples, bins=50)
        ax.set_title("Monte Carlo distribution")
        ax.set_xlabel("Value")
        ax.set_ylabel("Frequency")
        self.figure.tight_layout()
        self.canvas.draw()


def main():
    app = QApplication(sys.argv)
    window = TolstackWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()