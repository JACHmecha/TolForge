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
- STEP preview: load a STEP file via compas_occ and view/select its
  faces, edges, and vertices in an embedded 3D viewport

This file is intentionally slim: the actual logic lives in mixins in this
same package (step_viewer_mixin.py, dimension_bank_mixin.py,
analysis_mixin.py) and the 3D viewport widget in step_renderer.py. This
file only builds the UI layout and wires widgets to the methods those
mixins provide.

Run with:
    python gui/app.py
"""

import os
import sys
from pathlib import Path

# Windows-only: Python 3.8+ no longer searches PATH for the DLLs a C-extension
# depends on (a deliberate security change). If compas_occ was built from
# source against a manually-built OCCT (rather than the conda-forge prebuilt
# package), OCCT's DLLs live in a location Python won't find on its own, so
# we register them explicitly before compas_occ ever gets imported. STEP
# reading specifically (OCC.Core.STEPControl) transitively needs FreeType and
# TCL/TK runtime DLLs in addition to OCCT's own toolkits - found via
# `dumpbin /dependents` tracing, since the basic gp/math modules load fine
# without them but STEPControl does not. These paths are specific to a
# from-source OCCT build and won't exist/won't be needed on machines using
# the conda-forge compas_occ package instead.
#
# NOTE: this app must be run with the Python 3.10 interpreter at
# D:\PROGRAMS\PYTHON\python.exe - compas_viewer is not compatible with
# Python 3.14 (its Config class breaks under Python 3.14's new lazy
# annotation evaluation, PEP 649), so pythonocc-core/compas_occ/compas_viewer
# were all installed against 3.10 specifically, not whatever `python`
# happens to resolve to on PATH.
if os.name == "nt":
    for _dll_dir in (
        r"D:\GIT\REPOS\occt-install\win64\vc14\bin",
        r"D:\GIT\REPOS\3rdparty-vc14-64\3rdparty-vc14-64\freetype-2.13.3-x64\bin",
        r"D:\GIT\REPOS\3rdparty-vc14-64\3rdparty-vc14-64\tcltk-8.6.15-x64\bin",
    ):
        if Path(_dll_dir).is_dir():
            os.add_dll_directory(_dll_dir)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QPushButton, QLabel, QComboBox,
    QGroupBox, QHeaderView, QLineEdit,
    QCheckBox, QDoubleSpinBox, QSpinBox
)
from PySide6.QtCore import Qt

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from tolstack import DimensionBank

from gui.step_renderer import Renderer, detect_step_backend  # noqa: F401 - re-exported for tests/back-compat
from gui.step_viewer_mixin import StepViewerMixin
from gui.dimension_bank_mixin import DimensionBankMixin
from gui.analysis_mixin import AnalysisMixin

COLUMNS = ["Name", "Nominal", "Tol +", "Tol -", "Sign (+/-)", "Cpk (optional)"]


class TolstackWindow(QMainWindow, StepViewerMixin, DimensionBankMixin, AnalysisMixin):
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
        self._step_preview_widget = None
        self._step_preview_renderer = None
        self._step_entity_info = {}

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

        step_box = QGroupBox("STEP preview")
        step_layout = QVBoxLayout()
        self.step_status_label = QLabel("No STEP file loaded yet.")
        self.step_status_label.setWordWrap(True)
        self.step_status_label.setStyleSheet("font-size: 11px;")
        step_layout.addWidget(self.step_status_label)

        step_buttons = QHBoxLayout()
        load_step_btn = QPushButton("Load STEP")
        load_step_btn.clicked.connect(self.load_step_file)
        clear_step_btn = QPushButton("Clear")
        clear_step_btn.clicked.connect(self.clear_step_preview)
        step_buttons.addWidget(load_step_btn)
        step_buttons.addWidget(clear_step_btn)
        step_layout.addLayout(step_buttons)

        self.step_preview_container = QWidget()
        self.step_preview_container.setMinimumHeight(240)
        self.step_preview_container.setStyleSheet("border: 1px solid #cccccc; border-radius: 4px; background-color: #f8f8f8;")
        self.step_preview_layout = QVBoxLayout(self.step_preview_container)
        self.step_preview_layout.setContentsMargins(6, 6, 6, 6)
        self._init_step_preview_renderer()
        step_layout.addWidget(self.step_preview_container)
        step_box.setLayout(step_layout)
        right_panel.addWidget(step_box)

        root_layout.addLayout(right_panel, stretch=3)

        # Seed example row + bank so the GUI doesn't start empty
        self._seed_example()
        self._seed_bank()


def main():
    # compas_viewer's Renderer widget internally accesses a Viewer() singleton
    # (via compas_viewer.base.Base.viewer), and Viewer.__init__ unconditionally
    # creates its own QApplication(sys.argv) the first time it's instantiated.
    # Since Viewer is a true singleton (__init__ only runs once, see
    # compas_viewer.singleton.SingletonMeta), we let IT create the one and
    # only QApplication here, then reuse that same instance for our own
    # QMainWindow. If we instead created our own QApplication first, the
    # first Renderer() we embed would try to spin up a second QApplication
    # and crash with a shiboken "destroy the QApplication singleton" error.
    try:
        from compas_viewer.viewer import Viewer
        Viewer()  # triggers QApplication creation; safe no-op on repeat calls
        app = QApplication.instance()
    except Exception:
        app = QApplication.instance() or QApplication(sys.argv)

    window = TolstackWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
