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
    QInputDialog, QCheckBox, QDoubleSpinBox, QSpinBox
)
from PySide6.QtCore import Qt

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from tolstack import Stack, Dimension, DimensionBank, DimensionTemplate, MonteCarloResult

COLUMNS = ["Name", "Nominal", "Tol +", "Tol -", "Sign (+/-)", "Cpk (optional)"]


class TolstackWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Tol-Forge: Tolerance Stack Analysis")
        self.resize(1000, 650)

        self.bank = DimensionBank()
        self.interval_min_value = 0.0
        self.interval_max_value = 0.0
        self._histogram_ax = None
        self._interval_lines = []
        self._dragged_line = None
        self._dragged_line_index = None
        self._last_samples = None
        self._last_monte_carlo_payload = None

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)

        # --- Left panel: dimension table ---
        left_panel = QVBoxLayout()

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        left_panel.addWidget(self.table)

        legend = QHBoxLayout()
        legend.addWidget(QLabel("Legend:"))
        positive_label = QLabel("● Green = positive")
        positive_label.setStyleSheet("color: #4caf50; font-weight: bold;")
        legend.addWidget(positive_label)
        negative_label = QLabel("● Red = negative")
        negative_label.setStyleSheet("color: #f44336; font-weight: bold;")
        legend.addWidget(negative_label)
        legend.addStretch(1)
        left_panel.addLayout(legend)

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

        method_layout.addWidget(QLabel("Iterations:"))
        self.iterations_input = QSpinBox()
        self.iterations_input.setRange(100, 1000000)
        self.iterations_input.setSingleStep(1000)
        self.iterations_input.setValue(10000)
        self.iterations_input.setMaximumWidth(120)
        method_layout.addWidget(self.iterations_input)

        method_layout.addWidget(QLabel("Range min:"))
        self.range_min_input = QDoubleSpinBox()
        self.range_min_input.setRange(-1e12, 1e12)
        self.range_min_input.setDecimals(4)
        self.range_min_input.setValue(0.0)
        self.range_min_input.setMaximumWidth(110)
        method_layout.addWidget(self.range_min_input)

        method_layout.addWidget(QLabel("Range max:"))
        self.range_max_input = QDoubleSpinBox()
        self.range_max_input.setRange(-1e12, 1e12)
        self.range_max_input.setDecimals(4)
        self.range_max_input.setValue(0.0)
        self.range_max_input.setMaximumWidth(110)
        method_layout.addWidget(self.range_max_input)

        self.range_min_input.valueChanged.connect(self._sync_interval_from_inputs)
        self.range_max_input.valueChanged.connect(self._sync_interval_from_inputs)

        method_layout.addStretch(1)
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
        self.figure.canvas.mpl_connect("button_press_event", self._on_histogram_click)
        self.figure.canvas.mpl_connect("motion_notify_event", self._on_histogram_move)
        self.figure.canvas.mpl_connect("button_release_event", self._on_histogram_release)
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
                sign = self._get_sign_from_row(r)
            except (AttributeError, ValueError):
                raise ValueError(f"Row {r + 1} has invalid or incomplete data.")

            if sign not in {"+", "-"}:
                raise ValueError(f"Row {r + 1}: sign must be '+' or '-', not {sign}.")

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

    def _get_iterations(self) -> int:
        return int(self.iterations_input.value())

    def _get_range_bounds(self) -> tuple[float, float]:
        lower = float(self.range_min_input.value())
        upper = float(self.range_max_input.value())
        if lower > upper:
            raise ValueError("Range minimum cannot be greater than range maximum.")
        return lower, upper

    def _sync_interval_from_inputs(self):
        try:
            lower, upper = self._get_range_bounds()
        except ValueError:
            return

        self.interval_min_value = lower
        self.interval_max_value = upper
        self._update_interval_lines()
        self._refresh_interval_summary(self._last_samples)
        self.figure.canvas.draw_idle()

    def _update_interval_lines(self):
        if self._histogram_ax is None:
            return
        if not self._interval_lines:
            return
        self._interval_lines[0].set_xdata([self.interval_min_value, self.interval_min_value])
        self._interval_lines[1].set_xdata([self.interval_max_value, self.interval_max_value])
        self._histogram_ax.figure.canvas.draw_idle()

    def _refresh_interval_summary(self, samples):
        if samples is None or self._last_monte_carlo_payload is None:
            return

        try:
            lower, upper = self._get_range_bounds()
        except ValueError:
            return

        inside_count, outside_count, inside_percentage, outside_percentage = self._get_interval_stats(samples, lower, upper)
        model_lines = self._last_monte_carlo_payload["model_lines"]
        result = self._last_monte_carlo_payload["result"]
        fit = self._last_monte_carlo_payload["fit"]

        self.result_label.setText(
            f"Monte Carlo ({len(samples):,} iterations)\n"
            + "\n".join(model_lines) + "\n"
            f"{'-' * 30}\n"
            f"Mean       : {result.mean:.4f}\n"
            f"Std Dev    : {result.std_dev:.4f}\n"
            f"Range      : [{lower:.4f}, {upper:.4f}]\n"
            f"In range   : {inside_count:,}/{len(samples):,} ({inside_percentage:.2f}%)\n"
            f"Out of range: {outside_count:,}/{len(samples):,} ({outside_percentage:.2f}%)\n"
            + self._fit_text(fit)
        )

    def _get_interval_stats(self, samples, lower: float, upper: float):
        inside_mask = (samples >= lower) & (samples <= upper)
        inside_count = int(sum(inside_mask))
        total = int(len(samples))
        outside_count = total - inside_count
        inside_percentage = (inside_count / total * 100.0) if total else 0.0
        outside_percentage = (outside_count / total * 100.0) if total else 0.0
        return inside_count, outside_count, inside_percentage, outside_percentage

    def _on_histogram_click(self, event):
        if event.inaxes is None or event.inaxes is not self._histogram_ax or event.button != 1:
            return

        for index, line in enumerate(self._interval_lines):
            x_value = line.get_xdata()[0]
            if x_value is None:
                continue
            if abs(event.xdata - x_value) <= 0.03 * max(abs(self._histogram_ax.get_xlim()[1] - self._histogram_ax.get_xlim()[0]), 1.0):
                self._dragged_line = line
                self._dragged_line_index = index
                return

    def _on_histogram_move(self, event):
        if self._dragged_line is None or event.inaxes is not self._histogram_ax or event.xdata is None:
            return

        if self._dragged_line_index == 0:
            self.interval_min_value = float(event.xdata)
            if self.interval_min_value > self.interval_max_value:
                self.interval_max_value = self.interval_min_value
        else:
            self.interval_max_value = float(event.xdata)
            if self.interval_max_value < self.interval_min_value:
                self.interval_min_value = self.interval_max_value

        self._sync_interval_inputs_from_values()
        self._update_interval_lines()
        self._refresh_interval_summary(self._last_samples)
        self.figure.canvas.draw_idle()

    def _on_histogram_release(self, event):
        self._dragged_line = None
        self._dragged_line_index = None

    def _sync_interval_inputs_from_values(self):
        self.range_min_input.blockSignals(True)
        self.range_max_input.blockSignals(True)
        self.range_min_input.setValue(self.interval_min_value)
        self.range_max_input.setValue(self.interval_max_value)
        self.range_min_input.blockSignals(False)
        self.range_max_input.blockSignals(False)

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def run_analysis(self):
        try:
            stack = self._build_stack()
            lower, upper = self._get_range_bounds()
        except ValueError as e:
            QMessageBox.warning(self, "Invalid data", str(e))
            return

        if not stack.dimensions:
            QMessageBox.warning(self, "No data", "Add at least one dimension.")
            return

        method = self.method_combo.currentText()

        if method == "worst_case":
            result = stack.worst_case()
            fit = stack.assess_fit(result, target=0.0)
            self._show_stack_result(result, fit)
            self.canvas.setVisible(False)

        elif method == "rss":
            result = stack.rss()
            fit = stack.assess_fit(result, target=0.0)
            self._show_stack_result(result, fit)
            self.canvas.setVisible(False)

        elif method == "monte_carlo":
            try:
                default_cpk = self._get_default_cpk()
            except ValueError as e:
                QMessageBox.warning(self, "Invalid global Cpk", str(e))
                return

            iterations = self._get_iterations()
            result = stack.monte_carlo(iterations=iterations, default_cpk=default_cpk)
            fit = stack.assess_fit(result, target=0.0)

            model_lines = []
            for d in stack.dimensions:
                cpk = d.cpk if d.cpk is not None else default_cpk
                model = f"Cpk={cpk}" if cpk is not None else "uniform"
                model_lines.append(f"  {d.name}: {model}")

            self._last_samples = result.samples
            self._last_monte_carlo_payload = {"model_lines": model_lines, "result": result, "fit": fit}
            self._plot_histogram(result.samples)
            self._refresh_interval_summary(result.samples)
            self.canvas.setVisible(True)

    def _fit_text(self, fit) -> str:
        lines = [
            f"{'-' * 30}",
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
        self._histogram_ax = ax
        self._interval_lines = [
            ax.axvline(self.interval_min_value, color="#1f77b4", linestyle="--", linewidth=1.8),
            ax.axvline(self.interval_max_value, color="#ff7f0e", linestyle="--", linewidth=1.8),
        ]
        self.figure.tight_layout()
        self.canvas.draw()


def main():
    app = QApplication(sys.argv)
    window = TolstackWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()