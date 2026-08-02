"""Desktop GUI for tolstack (PySide6).

Window layout (slicer-style):
- Main widget is the 3D STEP viewport, occupying the majority of the
  window, with a slim status/legend strip beneath it and an
  always-visible analysis toolbar above it (method, global Cpk,
  iterations, range, Calculate button) - similar to how a 3D printing
  slicer keeps its viewport controls docked to the viewport itself.
- A left sidebar (QTabWidget) holds the three other functional areas as
  separate tabs, mirroring the "Prepare" / "Preview" tab pattern common
  in slicers:
    - "Dimension Bank": reusable dimension templates (no sign) that can
      be pulled into the current stack, saved from a row, and persisted
      to/from a JSON file
    - "Stack Table": the editable dimension table (name, nominal, tol+,
      tol-, sign, optional Cpk) with add/remove row buttons
    - "Results": text summary + histogram (matplotlib) for Monte Carlo,
      plus a fit assessment (gap / interference / mixed) against target
- STEP preview: load a STEP file via compas_occ and view/select its
  faces, edges, and vertices in the embedded 3D viewport

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
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QTableWidget, QPushButton, QLabel, QComboBox,
    QHeaderView, QLineEdit,
    QCheckBox, QDoubleSpinBox, QSpinBox,
    QTabWidget, QFrame, QSizePolicy, QScrollArea
)
from PySide6.QtCore import Qt

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from tolstack import DimensionBank

from gui.step_renderer import Renderer, detect_step_backend  # noqa: F401 - re-exported for tests/back-compat
from gui.step_viewer_mixin import StepViewerMixin
from gui.dimension_bank_mixin import DimensionBankMixin
from gui.analysis_mixin import AnalysisMixin
from gui.measurement_mixin import MeasurementMixin
from gui.eclipse_mixin import EclipseMixin
from gui.gdt_mixin import GdtMixin, PATTERN_COLUMNS

COLUMNS = ["Name", "Nominal", "Tol +", "Tol -", "+/-", "Cpk"]


class TolstackWindow(
    QMainWindow, StepViewerMixin, DimensionBankMixin, AnalysisMixin,
    MeasurementMixin, EclipseMixin, GdtMixin,
):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Tol-Forge: Tolerance Stack Analysis")
        self.resize(1300, 800)

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
        self._step_load_thread = None
        self._step_load_worker = None
        self._step_load_generation = 0
        self._pick_filter = "any"
        self._pick_markers = []
        self._measure_init_state()
        self._gdt_init_state()

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ==================================================================
        # Left sidebar: tabbed panel (Dimension Bank / Stack Table / Results)
        # Slicer-style "Prepare" panel - everything that isn't the 3D view.
        # ==================================================================
        sidebar = QTabWidget()
        sidebar.setMinimumWidth(340)
        sidebar.setMaximumWidth(460)
        sidebar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        # --- Tab 1: Dimension bank ---
        bank_tab = QWidget()
        bank_layout = QVBoxLayout(bank_tab)

        bank_row1 = QHBoxLayout()
        self.bank_combo = QComboBox()
        bank_row1.addWidget(self.bank_combo, stretch=1)
        bank_layout.addLayout(bank_row1)

        add_from_bank_btn = QPushButton("Add to stack")
        add_from_bank_btn.clicked.connect(self.add_from_bank)
        bank_layout.addWidget(add_from_bank_btn)
        remove_from_bank_btn = QPushButton("Remove from bank")
        remove_from_bank_btn.clicked.connect(self.remove_from_bank)
        bank_layout.addWidget(remove_from_bank_btn)

        bank_layout.addSpacing(12)
        save_row_btn = QPushButton("Save selected row to bank")
        save_row_btn.clicked.connect(self.save_row_to_bank)
        bank_layout.addWidget(save_row_btn)
        load_bank_btn = QPushButton("Load bank...")
        load_bank_btn.clicked.connect(self.load_bank_file)
        bank_layout.addWidget(load_bank_btn)
        save_bank_btn = QPushButton("Save bank...")
        save_bank_btn.clicked.connect(self.save_bank_file)
        bank_layout.addWidget(save_bank_btn)
        bank_layout.addStretch(1)

        sidebar.addTab(bank_tab, "Dimension Bank")

        # --- Tab 2: Stack table ---
        stack_tab = QWidget()
        stack_layout = QVBoxLayout(stack_tab)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        stack_layout.addWidget(self.table)

        legend = QHBoxLayout()
        legend.addWidget(QLabel("Legend:"))
        positive_label = QLabel("● Green = positive")
        positive_label.setStyleSheet("color: #4caf50; font-weight: bold;")
        legend.addWidget(positive_label)
        negative_label = QLabel("● Red = negative")
        negative_label.setStyleSheet("color: #f44336; font-weight: bold;")
        legend.addWidget(negative_label)
        legend.addStretch(1)
        stack_layout.addLayout(legend)

        row_btns = QHBoxLayout()
        add_btn = QPushButton("+ Add dimension")
        add_btn.clicked.connect(self.add_row)
        remove_btn = QPushButton("- Remove selected")
        remove_btn.clicked.connect(self.remove_row)
        row_btns.addWidget(add_btn)
        row_btns.addWidget(remove_btn)
        stack_layout.addLayout(row_btns)

        sidebar.addTab(stack_tab, "Stack Table")

        # --- Tab 3: Results ---
        results_tab = QWidget()
        results_layout = QVBoxLayout(results_tab)

        self.result_label = QLabel("No results yet.")
        self.result_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.result_label.setWordWrap(True)
        self.result_label.setStyleSheet("font-family: monospace; font-size: 12px;")
        results_layout.addWidget(self.result_label)

        self.figure = Figure(figsize=(4, 3))
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setVisible(False)
        self.figure.canvas.mpl_connect("button_press_event", self._on_histogram_click)
        self.figure.canvas.mpl_connect("motion_notify_event", self._on_histogram_move)
        self.figure.canvas.mpl_connect("button_release_event", self._on_histogram_release)
        results_layout.addWidget(self.canvas, stretch=1)

        sidebar.addTab(results_tab, "Results")

        # --- Tab 4: Measure ---
        measure_tab = QWidget()
        measure_layout = QVBoxLayout(measure_tab)

        measure_intro = QLabel(
            "Pick two faces, edges, or vertices in the 3D viewport to "
            "measure the distance and angle between them."
        )
        measure_intro.setWordWrap(True)
        measure_intro.setStyleSheet("color: #555555; font-size: 11px;")
        measure_layout.addWidget(measure_intro)

        slot_a_row = QHBoxLayout()
        self.measure_slot_a_label = QLabel("A: (none)")
        clear_a_btn = QPushButton("Clear")
        clear_a_btn.clicked.connect(self.measure_clear_slot_a)
        slot_a_row.addWidget(self.measure_slot_a_label, stretch=1)
        slot_a_row.addWidget(clear_a_btn)
        measure_layout.addLayout(slot_a_row)

        slot_b_row = QHBoxLayout()
        self.measure_slot_b_label = QLabel("B: (none)")
        clear_b_btn = QPushButton("Clear")
        clear_b_btn.clicked.connect(self.measure_clear_slot_b)
        slot_b_row.addWidget(self.measure_slot_b_label, stretch=1)
        slot_b_row.addWidget(clear_b_btn)
        measure_layout.addLayout(slot_b_row)

        measure_hint = QLabel(
            "Right-click a face, edge, or vertex in the viewport to assign it as Measure A or Measure B."
        )
        measure_hint.setWordWrap(True)
        measure_hint.setStyleSheet("color: #555555; font-size: 11px;")
        measure_layout.addWidget(measure_hint)

        measure_layout.addSpacing(10)
        results_box = QFrame()
        results_box.setFrameShape(QFrame.StyledPanel)
        results_box_layout = QVBoxLayout(results_box)
        self.measure_result_labels = {}
        for key, caption in [
            ("min", "Min distance:"), ("max", "Max distance:"),
            ("normal", "Normal distance:"), ("xyz", "Offset (X/Y/Z):"),
            ("angle", "Angle:"), ("radius_a", "Diameter A (if circular):"),
            ("radius_b", "Diameter B (if circular):"),
            ("circle_center", "Circle center offset:"),
        ]:
            row = QHBoxLayout()
            caption_label = QLabel(caption)
            caption_label.setStyleSheet("font-weight: bold;")
            value_label = QLabel("-")
            value_label.setWordWrap(True)
            self.measure_result_labels[key] = value_label
            row.addWidget(caption_label)
            row.addWidget(value_label, stretch=1)
            results_box_layout.addLayout(row)
        measure_layout.addWidget(results_box)

        measure_layout.addSpacing(10)
        tol_row = QHBoxLayout()
        tol_row.addWidget(QLabel("Tol +:"))
        self.measure_tol_plus_input = QLineEdit("0.0")
        self.measure_tol_plus_input.setMaximumWidth(70)
        tol_row.addWidget(self.measure_tol_plus_input)
        tol_row.addWidget(QLabel("Tol -:"))
        self.measure_tol_minus_input = QLineEdit("0.0")
        self.measure_tol_minus_input.setMaximumWidth(70)
        tol_row.addWidget(self.measure_tol_minus_input)
        tol_row.addStretch(1)
        measure_layout.addLayout(tol_row)

        offset_row = QHBoxLayout()
        show_offset_btn = QPushButton("Show tolerance offset")
        show_offset_btn.clicked.connect(self.show_tolerance_offset)
        clear_offset_btn = QPushButton("Clear offset")
        clear_offset_btn.clicked.connect(self.clear_tolerance_offset)
        offset_row.addWidget(show_offset_btn)
        offset_row.addWidget(clear_offset_btn)
        measure_layout.addLayout(offset_row)

        measure_layout.addSpacing(10)
        add_to_bank_btn = QPushButton("Add measurement to Dimension Bank")
        add_to_bank_btn.setStyleSheet("font-weight: bold;")
        add_to_bank_btn.clicked.connect(self.add_measurement_to_bank)
        measure_layout.addWidget(add_to_bank_btn)

        diameter_bank_row = QHBoxLayout()
        add_diameter_a_btn = QPushButton("Bank diameter A")
        add_diameter_a_btn.clicked.connect(self.add_circle_diameter_a_to_bank)
        add_diameter_b_btn = QPushButton("Bank diameter B")
        add_diameter_b_btn.clicked.connect(self.add_circle_diameter_b_to_bank)
        diameter_bank_row.addWidget(add_diameter_a_btn)
        diameter_bank_row.addWidget(add_diameter_b_btn)
        measure_layout.addLayout(diameter_bank_row)

        measure_layout.addStretch(1)
        sidebar.addTab(measure_tab, "Measure")

        # --- Tab 5: Eclipse (LED-hole vs sticker-hole occlusion) ---
        eclipse_tab = QWidget()
        eclipse_layout = QVBoxLayout(eclipse_tab)

        eclipse_intro = QLabel(
            "How much of an LED-hole's light gets blocked by a covering "
            "sticker hole, given tolerances on both hole diameters and "
            "their relative position."
        )
        eclipse_intro.setWordWrap(True)
        eclipse_intro.setStyleSheet("color: #555555; font-size: 11px;")
        eclipse_layout.addWidget(eclipse_intro)

        def add_tolerance_row(layout, prefix: str, caption: str, use_measured_btn=None):
            group = QFrame()
            group.setFrameShape(QFrame.StyledPanel)
            group_layout = QVBoxLayout(group)
            header_row = QHBoxLayout()
            header_label = QLabel(caption)
            header_label.setStyleSheet("font-weight: bold;")
            header_row.addWidget(header_label, stretch=1)
            if use_measured_btn is not None:
                btn = QPushButton(use_measured_btn[0])
                btn.clicked.connect(use_measured_btn[1])
                header_row.addWidget(btn)
            group_layout.addLayout(header_row)

            fields_row = QHBoxLayout()
            for field_name, field_label, default in [
                ("nominal", "Nominal:", "0.0"), ("tol_plus", "Tol +:", "0.0"),
                ("tol_minus", "Tol -:", "0.0"), ("cpk", "Cpk:", ""),
            ]:
                fields_row.addWidget(QLabel(field_label))
                field_input = QLineEdit(default)
                field_input.setMaximumWidth(60)
                if field_name == "cpk":
                    field_input.setPlaceholderText("uniform")
                setattr(self, f"eclipse_{prefix}_{field_name}_input", field_input)
                fields_row.addWidget(field_input)
            group_layout.addLayout(fields_row)
            layout.addWidget(group)

        add_tolerance_row(
            eclipse_layout, "handle", "Handle hole diameter",
            use_measured_btn=("Use measured A", self.use_measured_a_for_handle),
        )
        add_tolerance_row(
            eclipse_layout, "sticker", "Sticker hole diameter",
            use_measured_btn=("Use measured B", self.use_measured_b_for_sticker),
        )
        add_tolerance_row(eclipse_layout, "offset_x", "Position offset X")
        add_tolerance_row(eclipse_layout, "offset_y", "Position offset Y")

        use_offset_btn = QPushButton("Use measured circle-center offset (-> offset X)")
        use_offset_btn.clicked.connect(self.use_measured_offset)
        eclipse_layout.addWidget(use_offset_btn)

        eclipse_layout.addSpacing(10)
        run_row = QHBoxLayout()
        run_row.addWidget(QLabel("Iterations:"))
        self.eclipse_iterations_input = QSpinBox()
        self.eclipse_iterations_input.setRange(100, 1000000)
        self.eclipse_iterations_input.setSingleStep(1000)
        self.eclipse_iterations_input.setValue(10000)
        run_row.addWidget(self.eclipse_iterations_input)
        run_row.addWidget(QLabel("Alarm above %:"))
        self.eclipse_threshold_input = QLineEdit("20.0")
        self.eclipse_threshold_input.setMaximumWidth(60)
        run_row.addWidget(self.eclipse_threshold_input)
        eclipse_layout.addLayout(run_row)

        run_eclipse_btn = QPushButton("Run eclipse analysis")
        run_eclipse_btn.setStyleSheet("font-weight: bold;")
        run_eclipse_btn.clicked.connect(self.run_eclipse_analysis)
        eclipse_layout.addWidget(run_eclipse_btn)

        eclipse_results_box = QFrame()
        eclipse_results_box.setFrameShape(QFrame.StyledPanel)
        eclipse_results_layout = QVBoxLayout(eclipse_results_box)
        self.eclipse_result_labels = {}
        for key, caption in [
            ("mean", "Mean eclipse:"), ("std", "Std dev:"),
            ("mc_range", "Monte Carlo range:"), ("worst_case", "Exact worst case:"),
            ("probability", "Risk:"),
        ]:
            row = QHBoxLayout()
            caption_label = QLabel(caption)
            caption_label.setStyleSheet("font-weight: bold;")
            value_label = QLabel("-")
            value_label.setWordWrap(True)
            self.eclipse_result_labels[key] = value_label
            row.addWidget(caption_label)
            row.addWidget(value_label, stretch=1)
            eclipse_results_layout.addLayout(row)
        eclipse_layout.addWidget(eclipse_results_box)

        self.eclipse_figure = Figure(figsize=(4, 3))
        self.eclipse_canvas = FigureCanvasQTAgg(self.eclipse_figure)
        self.eclipse_canvas.setMinimumHeight(240)
        self.eclipse_canvas.setVisible(False)
        eclipse_layout.addWidget(self.eclipse_canvas, stretch=1)

        eclipse_layout.addStretch(1)

        eclipse_scroll = QScrollArea()
        eclipse_scroll.setWidgetResizable(True)
        eclipse_scroll.setWidget(eclipse_tab)
        eclipse_scroll.setFrameShape(QFrame.NoFrame)
        sidebar.addTab(eclipse_scroll, "Eclipse")

        # --- Tab 6: GD&T Position ---
        gdt_tab = QWidget()
        gdt_layout = QVBoxLayout(gdt_tab)

        gdt_intro = QLabel(
            "Position tolerance (\u2316) for a pattern of features against a "
            "3-datum reference frame. Datums: pick a face or a circular "
            "edge/hole for each of Primary/Secondary/Tertiary."
        )
        gdt_intro.setWordWrap(True)
        gdt_intro.setStyleSheet("color: #555555; font-size: 11px;")
        gdt_layout.addWidget(gdt_intro)

        datum_box = QFrame()
        datum_box.setFrameShape(QFrame.StyledPanel)
        datum_box_layout = QVBoxLayout(datum_box)
        self.datum_slot_labels = {}
        for slot_name, arm_fn, clear_fn in [
            ("Primary", self.datum_arm_primary, self.datum_clear_primary),
            ("Secondary", self.datum_arm_secondary, self.datum_clear_secondary),
            ("Tertiary", self.datum_arm_tertiary, self.datum_clear_tertiary),
        ]:
            row = QHBoxLayout()
            label = QLabel(f"{slot_name}: (none)")
            self.datum_slot_labels[slot_name] = label
            pick_btn = QPushButton(f"Pick {slot_name}")
            pick_btn.clicked.connect(arm_fn)
            clear_btn = QPushButton("Clear")
            clear_btn.clicked.connect(clear_fn)
            row.addWidget(label, stretch=1)
            row.addWidget(pick_btn)
            row.addWidget(clear_btn)
            datum_box_layout.addLayout(row)

        build_drf_btn = QPushButton("Build datum reference frame")
        build_drf_btn.setStyleSheet("font-weight: bold;")
        build_drf_btn.clicked.connect(self.build_datum_frame)
        datum_box_layout.addWidget(build_drf_btn)
        self.drf_status_label = QLabel("Datum reference frame not built yet.")
        self.drf_status_label.setWordWrap(True)
        self.drf_status_label.setStyleSheet("font-size: 11px; color: #555555;")
        datum_box_layout.addWidget(self.drf_status_label)
        gdt_layout.addWidget(datum_box)

        gdt_layout.addSpacing(8)
        pattern_btn_row = QHBoxLayout()
        pick_feature_btn = QPushButton("Pick feature for pattern")
        pick_feature_btn.clicked.connect(self.pattern_arm_pick)
        remove_feature_btn = QPushButton("Remove selected")
        remove_feature_btn.clicked.connect(self.pattern_remove_selected)
        pattern_btn_row.addWidget(pick_feature_btn)
        pattern_btn_row.addWidget(remove_feature_btn)
        gdt_layout.addLayout(pattern_btn_row)

        self.pattern_table = QTableWidget(0, len(PATTERN_COLUMNS))
        self.pattern_table.setHorizontalHeaderLabels(PATTERN_COLUMNS)
        self.pattern_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.pattern_table.horizontalHeader().setMinimumSectionSize(55)
        self.pattern_table.resizeColumnsToContents()
        self.pattern_table.setMinimumHeight(150)
        gdt_layout.addWidget(self.pattern_table)

        callout_box = QFrame()
        callout_box.setFrameShape(QFrame.StyledPanel)
        callout_layout = QGridLayout(callout_box)
        callout_layout.setHorizontalSpacing(12)
        callout_layout.setVerticalSpacing(4)

        def add_callout_field(row, col, label_text, widget):
            label = QLabel(label_text)
            label.setStyleSheet("font-size: 11px; color: #555555;")
            cell_layout = QVBoxLayout()
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(2)
            cell_layout.addWidget(label)
            cell_layout.addWidget(widget)
            callout_layout.addLayout(cell_layout, row, col)

        self.gdt_base_tolerance_input = QLineEdit("0.1")
        add_callout_field(0, 0, "\u2300T (position tolerance)", self.gdt_base_tolerance_input)

        self.gdt_modifier_combo = QComboBox()
        self.gdt_modifier_combo.addItems(["RFS", "MMC", "LMC"])
        add_callout_field(0, 1, "Modifier", self.gdt_modifier_combo)

        self.gdt_mmc_size_input = QLineEdit("0.0")
        add_callout_field(1, 0, "MMC size", self.gdt_mmc_size_input)

        self.gdt_lmc_size_input = QLineEdit("0.0")
        add_callout_field(1, 1, "LMC size", self.gdt_lmc_size_input)

        self.gdt_feature_kind_combo = QComboBox()
        self.gdt_feature_kind_combo.addItems(["hole", "pin"])
        add_callout_field(2, 0, "Feature kind", self.gdt_feature_kind_combo)
        gdt_layout.addWidget(callout_box)

        eval_row = QHBoxLayout()
        eval_row.addWidget(QLabel("Iterations:"))
        self.gdt_iterations_input = QSpinBox()
        self.gdt_iterations_input.setRange(100, 1000000)
        self.gdt_iterations_input.setSingleStep(1000)
        self.gdt_iterations_input.setValue(10000)
        eval_row.addWidget(self.gdt_iterations_input)
        eval_row.addWidget(QLabel("Default Cpk:"))
        self.gdt_default_cpk_input = QLineEdit()
        self.gdt_default_cpk_input.setPlaceholderText("uniform")
        self.gdt_default_cpk_input.setMaximumWidth(60)
        eval_row.addWidget(self.gdt_default_cpk_input)
        gdt_layout.addLayout(eval_row)

        eval_btn_row = QHBoxLayout()
        eval_nominal_btn = QPushButton("Evaluate (as-modeled)")
        eval_nominal_btn.clicked.connect(self.evaluate_pattern_deterministic)
        eval_mc_btn = QPushButton("Run Monte Carlo")
        eval_mc_btn.setStyleSheet("font-weight: bold;")
        eval_mc_btn.clicked.connect(self.run_pattern_monte_carlo_analysis)
        eval_btn_row.addWidget(eval_nominal_btn)
        eval_btn_row.addWidget(eval_mc_btn)
        gdt_layout.addLayout(eval_btn_row)

        gdt_results_box = QFrame()
        gdt_results_box.setFrameShape(QFrame.StyledPanel)
        gdt_results_layout = QVBoxLayout(gdt_results_box)
        self.gdt_result_labels = {}
        for key, caption in [
            ("nominal", "As-modeled:"), ("pattern_fail_rate", "Pattern fail rate:"),
            ("per_feature", "Per-feature fail rate:"),
        ]:
            row = QHBoxLayout()
            caption_label = QLabel(caption)
            caption_label.setStyleSheet("font-weight: bold;")
            value_label = QLabel("-")
            value_label.setWordWrap(True)
            self.gdt_result_labels[key] = value_label
            row.addWidget(caption_label)
            row.addWidget(value_label, stretch=1)
            gdt_results_layout.addLayout(row)
        gdt_layout.addWidget(gdt_results_box)

        self.gdt_figure = Figure(figsize=(4, 3))
        self.gdt_canvas = FigureCanvasQTAgg(self.gdt_figure)
        self.gdt_canvas.setMinimumHeight(240)
        self.gdt_canvas.setVisible(False)
        gdt_layout.addWidget(self.gdt_canvas, stretch=1)

        gdt_layout.addStretch(1)

        gdt_scroll = QScrollArea()
        gdt_scroll.setWidgetResizable(True)
        gdt_scroll.setWidget(gdt_tab)
        gdt_scroll.setFrameShape(QFrame.NoFrame)
        sidebar.addTab(gdt_scroll, "GD&T Position")

        root_layout.addWidget(sidebar, stretch=0)

        # ==================================================================
        # Right/main column: 3D STEP viewport is the main widget, with an
        # always-visible analysis toolbar docked above it and a slim
        # status/legend strip docked below it - mirrors a slicer's plater.
        # ==================================================================
        viewport_column = QVBoxLayout()
        viewport_column.setContentsMargins(8, 8, 8, 8)
        viewport_column.setSpacing(6)

        # --- Always-visible analysis toolbar (above the viewport) ---
        toolbar = QFrame()
        toolbar.setFrameShape(QFrame.StyledPanel)
        toolbar.setStyleSheet(
            "QFrame { background-color: #222222; border: 1px solid #d0d3d7; border-radius: 4px; }"
        )
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(8, 6, 8, 6)

        self.method_combo = QComboBox()
        self.method_combo.addItems(["worst_case", "rss", "monte_carlo"])
        toolbar_layout.addWidget(self.method_combo)

        toolbar_layout.addWidget(QLabel("Global Cpk:"))
        self.default_cpk_input = QLineEdit()
        self.default_cpk_input.setPlaceholderText("empty = uniform")
        self.default_cpk_input.setMaximumWidth(90)
        toolbar_layout.addWidget(self.default_cpk_input)

        toolbar_layout.addWidget(QLabel("Iterations:"))
        self.iterations_input = QSpinBox()
        self.iterations_input.setRange(100, 1000000)
        self.iterations_input.setSingleStep(1000)
        self.iterations_input.setValue(10000)
        self.iterations_input.setMaximumWidth(120)
        toolbar_layout.addWidget(self.iterations_input)

        toolbar_layout.addWidget(QLabel("Range min:"))
        self.range_min_input = QDoubleSpinBox()
        self.range_min_input.setRange(-1e12, 1e12)
        self.range_min_input.setDecimals(4)
        self.range_min_input.setValue(0.0)
        self.range_min_input.setMaximumWidth(110)
        toolbar_layout.addWidget(self.range_min_input)

        toolbar_layout.addWidget(QLabel("Range max:"))
        self.range_max_input = QDoubleSpinBox()
        self.range_max_input.setRange(-1e12, 1e12)
        self.range_max_input.setDecimals(4)
        self.range_max_input.setValue(0.0)
        self.range_max_input.setMaximumWidth(110)
        toolbar_layout.addWidget(self.range_max_input)

        self.range_min_input.valueChanged.connect(self._sync_interval_from_inputs)
        self.range_max_input.valueChanged.connect(self._sync_interval_from_inputs)

        toolbar_layout.addStretch(1)

        toolbar_layout.addWidget(QLabel("Mesh quality:"))
        self.step_deflection_input = QDoubleSpinBox()
        self.step_deflection_input.setRange(0.01, 5.0)
        self.step_deflection_input.setSingleStep(0.05)
        self.step_deflection_input.setDecimals(2)
        self.step_deflection_input.setValue(0.3)
        self.step_deflection_input.setMaximumWidth(80)
        self.step_deflection_input.setToolTip(
            "Tessellation deflection: lower = finer mesh / slower, "
            "higher = coarser mesh / faster. Raise this for large "
            "assemblies with many parts."
        )
        toolbar_layout.addWidget(self.step_deflection_input)

        toolbar_layout.addWidget(QLabel("Select:"))
        self.pick_filter_combo = QComboBox()
        self.pick_filter_combo.addItems(["Any", "Vertices", "Edges", "Faces", "Solids"])
        self.pick_filter_combo.setToolTip(
            "Restricts what a click in the viewport can select. 'Solids' "
            "selects a whole body (via its faces) at once - useful for "
            "picking a whole part in an assembly rather than one face."
        )
        self.pick_filter_combo.currentTextChanged.connect(self.set_pick_filter)
        toolbar_layout.addWidget(self.pick_filter_combo)

        load_step_btn = QPushButton("Load STEP")
        load_step_btn.clicked.connect(self.load_step_file)
        toolbar_layout.addWidget(load_step_btn)
        clear_step_btn = QPushButton("Clear")
        clear_step_btn.clicked.connect(self.clear_step_preview)
        toolbar_layout.addWidget(clear_step_btn)

        run_btn = QPushButton("Calculate")
        run_btn.setStyleSheet("font-weight: bold;")
        run_btn.clicked.connect(self.run_analysis)
        toolbar_layout.addWidget(run_btn)

        viewport_column.addWidget(toolbar)

        # --- Main widget: the 3D STEP viewport itself ---
        self.step_preview_container = QWidget()
        self.step_preview_container.setMinimumHeight(240)
        self.step_preview_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.step_preview_container.setStyleSheet(
            "border: 1px solid #cccccc; border-radius: 4px; background-color: #f8f8f8;"
        )
        self.step_preview_layout = QVBoxLayout(self.step_preview_container)
        self.step_preview_layout.setContentsMargins(6, 6, 6, 6)
        self._init_step_preview_renderer()
        viewport_column.addWidget(self.step_preview_container, stretch=1)

        # --- Slim status strip (below the viewport) ---
        status_strip = QFrame()
        status_strip.setStyleSheet(
            "QFrame { border-top: 1px solid #d0d3d7; }"
        )
        status_strip.setMaximumHeight(28)
        status_strip_layout = QHBoxLayout(status_strip)
        status_strip_layout.setContentsMargins(4, 2, 4, 2)
        self.step_status_label = QLabel("No STEP file loaded yet.")
        self.step_status_label.setWordWrap(False)
        self.step_status_label.setStyleSheet("font-size: 11px; color: #555555;")
        status_strip_layout.addWidget(self.step_status_label, stretch=1)
        viewport_column.addWidget(status_strip)

        root_layout.addLayout(viewport_column, stretch=1)

        # Seed example row + bank so the GUI doesn't start empty
        self._seed_example()
        self._seed_bank()

    def closeEvent(self, event):
        # Without this, closing the window while a large-assembly STEP
        # load is still running on its background QThread prints Qt's
        # "QThread: Destroyed while thread is still running" warning (and
        # can occasionally hang on exit) - give it a moment to wind down
        # cleanly first.
        self._cancel_step_load_for_shutdown()
        super().closeEvent(event)


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
