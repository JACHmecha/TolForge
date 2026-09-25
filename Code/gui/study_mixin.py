"""Guided drawing-conformance study and explicit report snapshots."""
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QCheckBox,
    QComboBox, QPushButton, QTableWidget, QTableWidgetItem, QFileDialog,
    QMessageBox, QScrollArea,
)
from tolstack.inspection import INSPECTION_FIELDS, evaluate_inspection
from tolstack.workflow import study_readiness, validate_study


class StudyMixin:
    def _create_study_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        intro = QLabel("1 Define requirement → 2 Establish datum alignment → 3 Enter drawing controls and measurements → 4 Validate → 5 Evaluate → 6 Review and report")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.study_objective_input = QLineEdit()
        self.study_objective_input.setPlaceholderText("Functional requirement / drawing characteristic")
        self.study_assumptions_input = QLineEdit()
        self.study_assumptions_input.setPlaceholderText("Assumptions and exclusions")
        self.inspection_drawing_input = QLineEdit()
        self.inspection_drawing_input.setPlaceholderText("Drawing number, revision and governing standard")
        self.inspection_source_input = QLineEdit()
        self.inspection_source_input.setPlaceholderText("Part/serial ID and CMM or inspection record")
        self.inspection_datum_input = QLineEdit()
        self.inspection_datum_input.setPlaceholderText("Datum order/alignment, e.g. A | B | C, RFS")
        for caption, widget in (
            ("Requirement", self.study_objective_input), ("Assumptions", self.study_assumptions_input),
            ("Drawing reference", self.inspection_drawing_input), ("Measurement source", self.inspection_source_input),
            ("Measurement datum frame", self.inspection_datum_input),
        ):
            layout.addWidget(QLabel(caption))
            layout.addWidget(widget)
        self.inspection_units_combo = QComboBox()
        self.inspection_units_combo.addItems(["mm", "in"])
        units_row = QHBoxLayout()
        units_row.addWidget(QLabel("Inspection data units"))
        units_row.addWidget(self.inspection_units_combo)
        layout.addLayout(units_row)
        self.inspection_alignment_check = QCheckBox("Measurements and basic coordinates share this datum frame and units")
        self.inspection_scope_check = QCheckBox("Single-segment position; axes parallel to datum Z; no datum mobility")
        self.study_units_check = QCheckBox("CAD study inputs use project units: mm / deg")
        layout.addWidget(self.inspection_alignment_check)
        layout.addWidget(self.inspection_scope_check)
        layout.addWidget(self.study_units_check)
        hint = QLabel("Enter measured centers already aligned by your inspection system. CAD inspection and process prediction remain in GD&T. No datum fitting, form/orientation evaluation or uncertainty decision rule is applied here.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.inspection_table = QTableWidget(0, len(INSPECTION_FIELDS) + 1)
        self.inspection_table.setHorizontalHeaderLabels([
            "Feature", "Basic X", "Basic Y", "Measured X", "Measured Y", "Measured Ø",
            "Size min", "Size max", "Position ØT", "Modifier", "Hole/pin", "Result",
        ])
        self.inspection_table.setMinimumHeight(220)
        layout.addWidget(self.inspection_table)
        actions = QHBoxLayout()
        for text, callback in (("Add feature", self._inspection_add_row), ("Remove", self._inspection_remove_rows),
                               ("Import CSV", self._inspection_import_csv)):
            button = QPushButton(text)
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        actions = QHBoxLayout()
        for text, callback in (("Evaluate measured part", self._evaluate_inspection),
                               ("Export report", self._export_inspection)):
            button = QPushButton(text)
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        self.inspection_result_label = QLabel("No measured-part result yet.")
        self.inspection_result_label.setWordWrap(True)
        layout.addWidget(self.inspection_result_label)
        layout.addWidget(QLabel("CAD position-study readiness"))
        self.study_advisor_label = QLabel("Validate the CAD model before analysis.")
        self.study_advisor_label.setWordWrap(True)
        layout.addWidget(self.study_advisor_label)
        actions = QHBoxLayout()
        for text, callback in (("Check CAD study", self._refresh_study_advisor),
                               ("Open GD&T", lambda: self._show_workspace("gdt")),
                               ("Open stack results", lambda: self._show_workspace("results"))):
            button = QPushButton(text)
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        layout.addStretch(1)
        self._last_inspection_report = None
        self.inspection_table.itemChanged.connect(self._invalidate_inspection)
        for widget in (self.inspection_drawing_input, self.inspection_source_input, self.inspection_datum_input,
                       self.study_objective_input, self.study_assumptions_input):
            widget.textChanged.connect(self._invalidate_inspection)
        self.inspection_units_combo.currentTextChanged.connect(self._invalidate_inspection)
        self.inspection_alignment_check.toggled.connect(self._invalidate_inspection)
        self.inspection_scope_check.toggled.connect(self._invalidate_inspection)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        self.study_tab = scroll
        return scroll

    def _inspection_add_row(self, checked=False, values=None):
        row = self.inspection_table.rowCount()
        self.inspection_table.insertRow(row)
        values = values or {"name": f"Feature {row + 1}", "modifier": "RFS", "feature_kind": "hole"}
        for col, key in enumerate(INSPECTION_FIELDS):
            self.inspection_table.setItem(row, col, QTableWidgetItem(str(values.get(key, ""))))
        self.inspection_table.resizeColumnsToContents()
        self._invalidate_inspection()

    def _inspection_remove_rows(self):
        for row in sorted({index.row() for index in self.inspection_table.selectedIndexes()}, reverse=True):
            self.inspection_table.removeRow(row)
        self._invalidate_inspection()

    def _inspection_rows(self):
        return [{key: self.inspection_table.item(row, col).text() if self.inspection_table.item(row, col) else ""
                 for col, key in enumerate(INSPECTION_FIELDS)} for row in range(self.inspection_table.rowCount())]

    def _inspection_import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import aligned inspection measurements", "", "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8-sig", newline="") as file:
                reader = csv.DictReader(file)
                if not set(INSPECTION_FIELDS).issubset(reader.fieldnames or []):
                    raise ValueError("CSV headers required: " + ", ".join(INSPECTION_FIELDS))
                rows = list(reader)
            # Validate numeric input before adding any rows. Existing rows are preserved.
            from tolstack.inspection import InspectionFeature
            for row in rows:
                InspectionFeature.from_row(row)
            names = [row["name"].strip() for row in self._inspection_rows() + rows]
            if len(names) != len(set(names)):
                raise ValueError("Imported names must be unique, including existing rows.")
            for row in rows:
                self._inspection_add_row(values=row)
        except (OSError, ValueError, csv.Error) as exc:
            QMessageBox.warning(self, "Could not import measurements", str(exc))

    def _invalidate_inspection(self, *args):
        self._last_inspection_report = None
        self.inspection_result_label.setText("Inputs changed — evaluate measured part to refresh results.")
        table = self.inspection_table
        previous = table.blockSignals(True)
        for row in range(table.rowCount()):
            table.setItem(row, len(INSPECTION_FIELDS), QTableWidgetItem("Not evaluated"))
        table.blockSignals(previous)

    def _evaluate_inspection(self):
        try:
            report = evaluate_inspection(
                self._inspection_rows(), drawing=self.inspection_drawing_input.text(),
                measurement_source=self.inspection_source_input.text(), datum_frame=self.inspection_datum_input.text(),
                units=self.inspection_units_combo.currentText(), alignment_confirmed=self.inspection_alignment_check.isChecked(),
                scope_confirmed=self.inspection_scope_check.isChecked(),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Inspection is not ready", str(exc))
            return
        report.update(requirement=self.study_objective_input.text(), assumptions=self.study_assumptions_input.text(),
                      created_at=datetime.now(timezone.utc).isoformat())
        self._last_inspection_report = report
        self.inspection_table.blockSignals(True)
        try:
            for row, result in enumerate(report["features"]):
                ev = result["evaluation"]
                text = (f"{'PASS' if ev['passes'] else 'FAIL'} supported checks; "
                        f"size margin {ev['size_margin']:+.6g}; position margin {ev['position_margin']:+.6g}")
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.inspection_table.setItem(row, len(INSPECTION_FIELDS), item)
        finally:
            self.inspection_table.blockSignals(False)
        failed = sum(not result["evaluation"]["passes"] for result in report["features"])
        self.inspection_result_label.setText(
            f"{len(report['features']) - failed}/{len(report['features'])} pass supplied position/size checks. "
            "Review margins and inspection uncertainty before disposition. Other drawing controls are outside this result.")

    def _export_inspection(self):
        if self._last_inspection_report is None:
            QMessageBox.warning(self, "No current report", "Evaluate the current measured inputs before exporting.")
            return
        self._save_report(self._last_inspection_report, "inspection-report.json")

    def _save_report(self, report, filename):
        path, _ = QFileDialog.getSaveFileName(self, "Export analysis report", filename, "JSON (*.json)")
        if not path:
            return
        try:
            Path(path).write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Could not export report", str(exc))

    def _export_stack_report(self):
        report = getattr(self, "_last_analysis_report", None)
        if report is None:
            QMessageBox.warning(self, "No current report", "Run the current stack analysis before exporting.")
            return
        self._save_report(report.to_dict(), "stack-report.json")

    def _study_capture(self):
        study = dict(self.project.study)
        study.update(
            response_name=self.response_name_input.text(), objective=self.study_objective_input.text(),
            assumptions=self.study_assumptions_input.text(), seed=self.seed_input.text(),
            method=self.method_combo.currentText(), default_cpk=self.default_cpk_input.text(),
            iterations=self.iterations_input.value(), lower_limit=self.range_min_input.value(),
            upper_limit=self.range_max_input.value(), units_confirmed=self.study_units_check.isChecked(),
            gdt_iterations=self.gdt_iterations_input.value(), gdt_default_cpk=self.gdt_default_cpk_input.text(),
            inspection={"drawing": self.inspection_drawing_input.text(), "source": self.inspection_source_input.text(),
                        "datum_frame": self.inspection_datum_input.text(), "units": self.inspection_units_combo.currentText(),
                        "alignment_confirmed": self.inspection_alignment_check.isChecked(),
                        "scope_confirmed": self.inspection_scope_check.isChecked(), "rows": self._inspection_rows()},
        )
        validate_study(study)
        self.project.study = study

    def _study_restore(self):
        study = self.project.study
        for widget, key, default in (
            (self.response_name_input, "response_name", "Functional response"),
            (self.study_objective_input, "objective", ""), (self.study_assumptions_input, "assumptions", ""),
            (self.seed_input, "seed", ""), (self.default_cpk_input, "default_cpk", ""),
            (self.gdt_default_cpk_input, "gdt_default_cpk", ""),
        ):
            widget.setText(study.get(key, default))
        self.method_combo.setCurrentText(study.get("method", "worst_case"))
        self.iterations_input.setValue(study.get("iterations", 10000))
        self.gdt_iterations_input.setValue(study.get("gdt_iterations", 10000))
        self.range_min_input.setValue(study.get("lower_limit", 0.0))
        self.range_max_input.setValue(study.get("upper_limit", 0.0))
        self.study_units_check.setChecked(study.get("units_confirmed", False))
        self.study_units_check.setText(f"CAD study inputs use project units: {self.project.units.length} / {self.project.units.angle}")
        inspection = study.get("inspection", {})
        for widget, key in ((self.inspection_drawing_input, "drawing"), (self.inspection_source_input, "source"),
                            (self.inspection_datum_input, "datum_frame")):
            widget.setText(inspection.get(key, ""))
        self.inspection_units_combo.setCurrentText(inspection.get("units", "mm"))
        self.inspection_alignment_check.setChecked(inspection.get("alignment_confirmed", False))
        self.inspection_scope_check.setChecked(inspection.get("scope_confirmed", False))
        self.inspection_table.setRowCount(0)
        for row in inspection.get("rows", []):
            self._inspection_add_row(values=row)
        self._invalidate_inspection()
        self._invalidate_stack_report()

    def _invalidate_stack_report(self, *args):
        self._last_analysis_report = None
        self._last_samples = None
        self._last_monte_carlo_payload = None
        self.result_label.setText("Inputs changed — run analysis to refresh results.")
        self.canvas.setVisible(False)

    def _refresh_study_advisor(self):
        error = None
        try:
            self._study_capture()
            if self.pattern_table.rowCount():
                from tolstack.gdt import validate_pattern_control
                validate_pattern_control(self._pattern_read_control())
        except ValueError as exc:
            error = str(exc)
        unresolved = sum(feature_id not in self._entity_by_feature_id for feature_id in self.project.features)
        findings = study_readiness(
            self.project, datum_count=sum(value is not None for value in self._datum_slot.values()),
            frame_ready=self._current_drf is not None, pattern_count=self.pattern_table.rowCount(),
            unresolved_count=unresolved, input_error=error,
        )
        self.study_advisor_label.setText("\n".join(f"{item.severity.upper()} · {item.stage}: {item.message}" for item in findings))
