"""
Desktop GUI for tolstack (PySide6).

Window layout:
- Editable dimension table (name, nominal, tol+, tol-, sign, optional Cpk)
- Buttons to add/remove rows
- Buttons to run each analysis method (Worst Case, RSS, Monte Carlo)
- Results panel: text + histogram (matplotlib) for Monte Carlo

Run with:
    python gui/app.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QPushButton, QLabel, QComboBox,
    QMessageBox, QGroupBox, QHeaderView, QLineEdit
)
from PySide6.QtCore import Qt

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from tolstack import Stack, Dimension

COLUMNS = ["Name", "Nominal", "Tol +", "Tol -", "Sign (+1/-1)", "Cpk (optional)"]


class TolstackWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Tolerance Stack-up Tool")
        self.resize(900, 600)

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

        method_box = QGroupBox("Analysis method")
        method_layout = QHBoxLayout()
        self.method_combo = QComboBox()
        self.method_combo.addItems(["worst_case", "rss", "monte_carlo"])
        method_layout.addWidget(self.method_combo)

        method_layout.addWidget(QLabel("Global Cpk:"))
        self.default_cpk_input = QLineEdit()
        self.default_cpk_input.setPlaceholderText("empty = uniform")
        self.default_cpk_input.setMaximumWidth(90)
        method_layout.addWidget(self.default_cpk_input)

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

        # Seed example row so the GUI doesn't start empty
        self._seed_example()

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

    def add_row(self):
        self.table.insertRow(self.table.rowCount())

    def remove_row(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

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

    def run_analysis(self):
        try:
            stack = self._build_stack()
        except ValueError as e:
            QMessageBox.warning(self, "Invalid data", str(e))
            return

        if not stack.dimensions:
            QMessageBox.warning(self, "No data", "Add at least one dimension.")
            return

        method = self.method_combo.currentText()

        if method == "worst_case":
            result = stack.worst_case()
            self._show_stack_result(result)
            self.canvas.setVisible(False)

        elif method == "rss":
            result = stack.rss()
            self._show_stack_result(result)
            self.canvas.setVisible(False)

        elif method == "monte_carlo":
            try:
                default_cpk = self._get_default_cpk()
            except ValueError as e:
                QMessageBox.warning(self, "Invalid global Cpk", str(e))
                return

            result = stack.monte_carlo(default_cpk=default_cpk)

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
                f"Maximum    : {result.maximum:.4f}"
            )
            self._plot_histogram(result.samples)
            self.canvas.setVisible(True)

    def _show_stack_result(self, result):
        self.result_label.setText(
            f"{'-' * 30}\n"
            f"Nominal : {result.nominal:.4f}\n"
            f"Maximum : {result.upper_limit:.4f}\n"
            f"Minimum : {result.lower_limit:.4f}\n"
            f"+Tol    : {result.upper_limit - result.nominal:.4f}\n"
            f"-Tol    : {result.nominal - result.lower_limit:.4f}"
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
