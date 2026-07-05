"""
Desktop GUI for the tolerance stack-up tool.

Structure of the GUI:
- Editable table of dimensions (name, nominal, tol+, tol-, sign)
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
    QMessageBox, QGroupBox, QHeaderView
)
from PySide6.QtCore import Qt

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from tolstack import Stack, Dimension

COLUMNS = ["Nombre", "Nominal", "Tol +", "Tol -", "Sign (+1/-1)"]


class TolstackWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Tolerance Stack-up Tool")
        self.resize(900, 600)

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)

        # --- Panel izquierdo: tabla de dimensiones ---
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

        method_box = QGroupBox("Analysis Method")
        method_layout = QHBoxLayout()
        self.method_combo = QComboBox()
        self.method_combo.addItems(["worst_case", "rss", "monte_carlo"])
        run_btn = QPushButton("Calculate")
        run_btn.clicked.connect(self.run_analysis)
        method_layout.addWidget(self.method_combo)
        method_layout.addWidget(run_btn)
        method_box.setLayout(method_layout)
        left_panel.addWidget(method_box)

        root_layout.addLayout(left_panel, stretch=2)

        # --- Panel derecho: resultados ---
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

        # Fila de ejemplo para que la GUI no arranque vacía
        self._seed_example()

    def _seed_example(self):
        for name, nominal, tol_plus, tol_minus, sign in [
            ("Base", 25.0, 0.10, 0.05, 1),
            ("Spacer", 12.5, 0.05, 0.05, 1),
            ("Bearing", 40.0, 0.20, 0.10, -1),
        ]:
            self.add_row()
            r = self.table.rowCount() - 1
            values = [name, nominal, tol_plus, tol_minus, sign]
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
                raise ValueError(f"Row {r + 1}: the sign must be +1 or -1, not {sign}.")

            stack.add_dimension(Dimension(
                name=name, nominal=nominal,
                tol_plus=tol_plus, tol_minus=tol_minus, sign=sign
            ))
        return stack

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
            result = stack.monte_carlo()
            self.result_label.setText(
                f"Monte Carlo (10,000 iterations)\n"
                f"{'-' * 30}\n"
                f"Media      : {result.mean:.4f}\n"
                f"Desv. Std  : {result.std_dev:.4f}\n"
                f"Mínimo     : {result.minimum:.4f}\n"
                f"Máximo     : {result.maximum:.4f}"
            )
            self._plot_histogram(result.samples)
            self.canvas.setVisible(True)

    def _show_stack_result(self, result):
        self.result_label.setText(
            f"{'-' * 30}\n"
            f"Nominal : {result.nominal:.4f}\n"
            f"Max     : {result.upper_limit:.4f}\n"
            f"Min     : {result.lower_limit:.4f}\n"
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
