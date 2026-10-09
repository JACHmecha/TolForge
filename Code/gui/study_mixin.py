"""Guided drawing-conformance study and explicit report snapshots."""
import csv
from contextlib import nullcontext
from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLabel, QLineEdit, QFrame, QSizePolicy,
    QComboBox, QPushButton, QTableWidget, QTableWidgetItem, QFileDialog,
    QMessageBox, QScrollArea, QDialog,
)
from tolstack.inspection import INSPECTION_FIELDS, evaluate_inspection
from tolstack.characteristics import CONTROL_FIELDS, validate_drawing_controls
from tolstack.domain import new_id
from tolstack.reporting import project_report_context
from tolstack.workflow import study_readiness, validate_study
from tolstack.persistence import save_json
from tolstack.inspection_import import read_aligned_csv, preview_import, normalized_frame, validate_row_metadata
from gui.inspection_import_dialog import ImportAlignedCsvDialog
from gui.layout_presentation import WrappedCheckBox
from gui.table_presentation import configure_table, fit_table_columns


class StudyMixin:
    INSPECTION_MEASUREMENT_ROLE = Qt.UserRole + 221

    def _create_study_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        def wrapped_label(text, role="muted"):
            label = QLabel(text)
            label.setProperty("role", role)
            label.setWordWrap(True)
            label.setMinimumWidth(0)
            policy = QSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            policy.setHeightForWidth(True)
            label.setSizePolicy(policy)
            return label

        def section(title):
            card = QFrame()
            card.setProperty("surface", "card")
            contents = QVBoxLayout(card)
            contents.setContentsMargins(16, 16, 16, 16)
            contents.setSpacing(10)
            contents.addWidget(wrapped_label(title, "sectionHeading"))
            layout.addWidget(card)
            return contents

        def compact_form():
            form = QFormLayout()
            form.setContentsMargins(0, 0, 0, 0)
            form.setHorizontalSpacing(12)
            form.setVerticalSpacing(10)
            form.setRowWrapPolicy(QFormLayout.WrapLongRows)
            form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            return form

        def action_rows(contents, actions):
            form = compact_form()
            buttons = []
            for text, callback in actions:
                button = QPushButton(text)
                button.clicked.connect(callback)
                buttons.append(button)
            for index in range(0, len(buttons), 2):
                if index + 1 < len(buttons):
                    form.addRow(buttons[index], buttons[index + 1])
                else:
                    form.addRow(buttons[index])
            contents.addLayout(form)

        layout.addWidget(wrapped_label(
            "1 Define requirement → 2 Establish datum alignment → 3 Enter drawing controls and measurements "
            "→ 4 Validate → 5 Evaluate → 6 Review and report"
        ))

        references = section("References and requirement")
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
        references_form = compact_form()
        for caption, widget in (
            ("Requirement", self.study_objective_input), ("Assumptions", self.study_assumptions_input),
            ("Drawing reference", self.inspection_drawing_input), ("Measurement source", self.inspection_source_input),
        ):
            references_form.addRow(caption, widget)
        references.addLayout(references_form)

        alignment = section("Datum alignment and scope")
        self.inspection_units_combo = QComboBox()
        self.inspection_units_combo.addItems(["mm", "in"])
        alignment_form = compact_form()
        alignment_form.addRow("Measurement datum frame", self.inspection_datum_input)
        alignment_form.addRow("Inspection data units", self.inspection_units_combo)
        alignment.addLayout(alignment_form)
        self.inspection_alignment_check = WrappedCheckBox("Measurements and basic coordinates share this datum frame and units")
        self.inspection_scope_check = WrappedCheckBox("Single-segment position; axes parallel to datum Z; no datum mobility")
        self.study_units_check = WrappedCheckBox("CAD study inputs use project units: mm / deg")
        alignment.addWidget(self.inspection_alignment_check)
        alignment.addWidget(self.inspection_scope_check)
        alignment.addWidget(self.study_units_check)
        alignment.addWidget(wrapped_label(
            "Enter measured centers already aligned by your inspection system. CAD inspection and process prediction "
            "remain in GD&T. No datum fitting, form/orientation evaluation or uncertainty decision rule is applied here."
        ))

        drawing_controls = section("Drawing controls and coverage")
        drawing_controls.addWidget(wrapped_label(
            "Record every requested control, including unsupported characteristics. "
            "Position specification: diametral tolerance, e.g. 0.2. "
            "Size specification: minimum:maximum, e.g. 10:10.2. "
            "Use the measurement units and datum reference recorded above. "
            "Other callouts are retained for review and remain unevaluated."
        ))
        self.characteristic_table = QTableWidget(0, len(CONTROL_FIELDS) + 1)
        self.characteristic_table.setHorizontalHeaderLabels([
            "Control ID", "Balloon", "Drawing", "Revision", "Characteristic",
            "Specification", "Datum reference", "Measured feature", "Coverage / result",
        ])
        configure_table(self.characteristic_table, text_columns=tuple(range(len(CONTROL_FIELDS) + 1)))
        self.characteristic_table.setMinimumHeight(180)
        drawing_controls.addWidget(self.characteristic_table)
        action_rows(drawing_controls, (
            ("Add drawing control", self._drawing_control_add_row),
            ("Remove control", self._drawing_control_remove_rows),
        ))
        self.characteristic_coverage_label = wrapped_label("No drawing-control inventory recorded.")
        drawing_controls.addWidget(self.characteristic_coverage_label)

        measurements = section("Aligned feature measurements")
        self.inspection_table = QTableWidget(0, len(INSPECTION_FIELDS) + 1)
        self.inspection_table.setHorizontalHeaderLabels([
            "Feature", "Basic X", "Basic Y", "Measured X", "Measured Y", "Measured Ø",
            "Size min", "Size max", "Position ØT", "Modifier", "Hole/pin", "Result",
        ])
        configure_table(self.inspection_table, numeric_columns=tuple(range(1, 9)), text_columns=(0, 9, 10, 11))
        self.inspection_table.setMinimumHeight(220)
        measurements.addWidget(self.inspection_table)
        action_rows(measurements, (
            ("Add feature", self._inspection_add_row), ("Remove", self._inspection_remove_rows),
            ("Import CSV", self._inspection_import_csv),
        ))

        results = section("Results and readiness")
        results.addWidget(wrapped_label("Measured-part results", "sectionHeading"))
        self.inspection_result_label = wrapped_label("No measured-part result yet.", "status")
        results.addWidget(self.inspection_result_label)
        action_rows(results, (
            ("Evaluate measured part", self._evaluate_inspection), ("Export report", self._export_inspection),
        ))
        results.addWidget(wrapped_label("CAD position-study readiness", "sectionHeading"))
        self.study_advisor_label = wrapped_label("Validate the CAD model before analysis.")
        results.addWidget(self.study_advisor_label)
        action_rows(results, (
            ("Check CAD study", self._refresh_study_advisor),
            ("Open GD&T", lambda: self._show_workspace("gdt")),
            ("Open stack results", lambda: self._show_workspace("results")),
        ))
        layout.addStretch(1)
        self._last_inspection_report = None
        self._inspection_source_files = []
        self.inspection_table.itemChanged.connect(self._invalidate_inspection)
        self.inspection_table.itemChanged.connect(self._inspection_context_changed)
        self.characteristic_table.itemChanged.connect(self._invalidate_inspection)
        self.characteristic_table.itemChanged.connect(self._drawing_control_context_changed)
        for widget in (self.inspection_drawing_input, self.inspection_source_input, self.inspection_datum_input,
                       self.study_objective_input, self.study_assumptions_input):
            widget.textChanged.connect(self._invalidate_inspection)
        self.inspection_units_combo.currentTextChanged.connect(self._invalidate_inspection)
        self.inspection_alignment_check.toggled.connect(self._invalidate_inspection)
        self.inspection_scope_check.toggled.connect(self._invalidate_inspection)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        self.study_tab = scroll
        return scroll

    def _drawing_control_add_row(self, checked=False, values=None):
        table = self.characteristic_table
        row = table.rowCount()
        defaults = {
            "id": new_id(), "balloon": str(row + 1), "drawing": self.inspection_drawing_input.text(),
            "revision": "", "characteristic": "position", "specification": "",
            "datum_references": self.inspection_datum_input.text(), "feature_name": "",
        }
        if values is not None:
            defaults.update(values)
        previous = table.blockSignals(True)
        try:
            table.insertRow(row)
            for column, key in enumerate(CONTROL_FIELDS):
                item = QTableWidgetItem(str(defaults.get(key, "")))
                if key == "id":
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                table.setItem(row, column, item)
        finally:
            table.blockSignals(previous)
        fit_table_columns(table)
        self._invalidate_inspection()
        self._drawing_control_context_changed()

    def _drawing_control_remove_rows(self):
        for row in sorted({index.row() for index in self.characteristic_table.selectedIndexes()}, reverse=True):
            self.characteristic_table.removeRow(row)
        self._invalidate_inspection()
        self._drawing_control_context_changed()

    def _drawing_control_rows(self):
        table = self.characteristic_table
        return [
            {key: table.item(row, column).text() if table.item(row, column) else ""
             for column, key in enumerate(CONTROL_FIELDS)}
            for row in range(table.rowCount())
        ]

    def _drawing_control_context_changed(self, item=None):
        if item is not None and item.column() >= len(CONTROL_FIELDS):
            return
        callback = getattr(self, "_project_invalidate_context_reports", None)
        if callback is not None:
            callback()

    def _inspection_add_row(self, checked=False, values=None, metadata=None, *, notify=True):
        row = self.inspection_table.rowCount()
        values = values or {"name": f"Feature {row + 1}", "modifier": "RFS", "feature_kind": "hole"}
        identity = deepcopy(metadata) if metadata is not None else {
            "id": new_id(), "units": self.inspection_units_combo.currentText(),
        }
        identity.setdefault("units", self.inspection_units_combo.currentText())
        previous = self.inspection_table.blockSignals(True)
        try:
            self.inspection_table.insertRow(row)
            for col, key in enumerate(INSPECTION_FIELDS):
                item = QTableWidgetItem(str(values.get(key, "")))
                if key == "name":
                    item.setData(self.INSPECTION_MEASUREMENT_ROLE, identity)
                self.inspection_table.setItem(row, col, item)
        finally:
            self.inspection_table.blockSignals(previous)
        fit_table_columns(self.inspection_table)
        if notify:
            self._invalidate_inspection()
            self._inspection_context_changed()
            callback = getattr(self, "_project_note_change", None)
            if callback is not None:
                callback()

    def _inspection_remove_rows(self):
        for row in sorted({index.row() for index in self.inspection_table.selectedIndexes()}, reverse=True):
            self.inspection_table.removeRow(row)
        self._invalidate_inspection()
        self._inspection_context_changed()

    def _inspection_rows(self):
        return [{key: self.inspection_table.item(row, col).text() if self.inspection_table.item(row, col) else ""
                 for col, key in enumerate(INSPECTION_FIELDS)} for row in range(self.inspection_table.rowCount())]

    def _inspection_row_metadata(self):
        return [deepcopy(self.inspection_table.item(row, 0).data(self.INSPECTION_MEASUREMENT_ROLE))
                if self.inspection_table.item(row, 0) is not None else None
                for row in range(self.inspection_table.rowCount())]

    def _inspection_context_changed(self, item=None):
        if item is not None and item.column() >= len(INSPECTION_FIELDS):
            return
        self._drawing_control_context_changed()

    def _inspection_import_constraints(self):
        metadata = self._inspection_row_metadata()
        validate_row_metadata(metadata, self._inspection_rows())
        return dict(
            existing_names=[row["name"] for row in self._inspection_rows()],
            existing_ids=[item["id"] for item in metadata],
            existing_units=[item.get("units", self.inspection_units_combo.currentText()) for item in metadata],
            dataset_units=self.inspection_units_combo.currentText(),
            existing_frames=([self.inspection_datum_input.text()] if metadata else []) + [
                item.get("external_alignment", {}).get("datum_frame", "") for item in metadata],
        )

    def _inspection_import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import aligned inspection measurements", "", "CSV (*.csv)")
        if not path:
            return
        try:
            source = read_aligned_csv(path)
            dialog = ImportAlignedCsvDialog(source, self, **self._inspection_import_constraints(),
                                            datum_frame=self.inspection_datum_input.text())
            if dialog.exec() != QDialog.Accepted:
                return
            # Recheck current constraints before changing anything, including unit labels.
            accepted = preview_import(dialog.source, **dialog.options(),
                                      **self._inspection_import_constraints()).accepted()
            table = self.inspection_table
            original_count = table.rowCount()
            pause = self._project_suspend_changes() if hasattr(self, "_project_suspend_changes") else nullcontext()
            with pause:
                previous = table.blockSignals(True)
                try:
                    for row, metadata in zip(accepted["rows"], accepted["row_metadata"]):
                        self._inspection_add_row(values=row, metadata=metadata, notify=False)
                except Exception:
                    table.setRowCount(original_count)
                    raise
                finally:
                    table.blockSignals(previous)
            descriptor = accepted["source_descriptor"]
            self._inspection_source_files.append(deepcopy(descriptor))
            if not original_count:
                self.inspection_units_combo.setCurrentText(descriptor["units"])
                self.inspection_datum_input.setText(descriptor["external_alignment"]["datum_frame"])
                self.inspection_alignment_check.setChecked(True)
            self._invalidate_inspection()
            self._inspection_context_changed()
            callback = getattr(self, "_project_note_change", None)
            if callback is not None:
                callback()
        except (OSError, ValueError, UnicodeError, csv.Error) as exc:
            QMessageBox.warning(self, "Could not import measurements", str(exc))

    def _invalidate_inspection(self, *args):
        if args and hasattr(args[0], "column"):
            item = args[0]
            table = item.tableWidget()
            if ((table is self.inspection_table and item.column() == len(INSPECTION_FIELDS))
                    or (table is self.characteristic_table and item.column() == len(CONTROL_FIELDS))):
                return
        self._last_inspection_report = None
        self.inspection_result_label.setText("Inputs changed — evaluate measured part to refresh results.")
        table = self.inspection_table
        previous = table.blockSignals(True)
        for row in range(table.rowCount()):
            item = QTableWidgetItem("Not evaluated")
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            table.setItem(row, len(INSPECTION_FIELDS), item)
        table.blockSignals(previous)
        if hasattr(self, "characteristic_table"):
            table = self.characteristic_table
            previous = table.blockSignals(True)
            for row in range(table.rowCount()):
                item = QTableWidgetItem("Not evaluated")
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                table.setItem(row, len(CONTROL_FIELDS), item)
            table.blockSignals(previous)
            self.characteristic_coverage_label.setText(
                "Drawing controls changed or measurements updated — evaluate to refresh coverage."
                if table.rowCount() else "No drawing-control inventory recorded."
            )

    def _evaluate_inspection(self):
        self._invalidate_inspection()
        try:
            metadata = self._inspection_row_metadata()
            validate_row_metadata(metadata, self._inspection_rows())
            if any(item.get("units", self.inspection_units_combo.currentText()) != self.inspection_units_combo.currentText()
                   for item in metadata):
                raise ValueError("Measurement units differ from the dataset label; changing the label does not convert values.")
            frame = normalized_frame(self.inspection_datum_input.text())
            if any(item.get("external_alignment") and normalized_frame(item["external_alignment"]["datum_frame"]) != frame
                   for item in metadata):
                raise ValueError("Imported external alignment differs from the measurement datum frame; no coordinate transformation is performed.")
            controls = self._drawing_control_rows()
            context = project_report_context(
                self.project,
                study_metadata={
                    "requirement": self.study_objective_input.text(),
                    "assumptions": self.study_assumptions_input.text(),
                    "measurement_source_reference": self.inspection_source_input.text(),
                    "measurement_row_metadata": self._inspection_row_metadata(),
                },
                sources=deepcopy(self._inspection_source_files),
                cad_sources=self._project_report_sources() if hasattr(self, "_project_report_sources") else None,
            )
            report = evaluate_inspection(
                self._inspection_rows(), drawing=self.inspection_drawing_input.text(),
                measurement_source=self.inspection_source_input.text(), datum_frame=self.inspection_datum_input.text(),
                units=self.inspection_units_combo.currentText(), alignment_confirmed=self.inspection_alignment_check.isChecked(),
                scope_confirmed=self.inspection_scope_check.isChecked(),
                drawing_controls=controls, report_context=context,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Inspection is not ready", str(exc))
            return
        report.update(requirement=self.study_objective_input.text(), assumptions=self.study_assumptions_input.text(),
                      created_at=report["evidence"]["created_at"])
        self._last_inspection_report = report
        self.inspection_table.blockSignals(True)
        try:
            results_by_name = {}
            for result in report["features"]:
                results_by_name.setdefault(result["input"]["name"], []).append(result)
            for row, measured in enumerate(self._inspection_rows()):
                results = results_by_name.get(measured["name"].strip(), [])
                if controls:
                    text = "; ".join(
                        f"{result['characteristic']} {'PASS' if result['requested_control_passes'] else 'FAIL'} "
                        f"({result['control_id']})" for result in results
                    ) or "No evaluated requested control for this feature"
                elif results:
                    ev = results[0]["evaluation"]
                    text = (f"{'PASS' if ev['passes'] else 'FAIL'} supported checks; "
                            f"size margin {ev['size_margin']:+.6g}; position margin {ev['position_margin']:+.6g}")
                else:
                    text = "Not evaluated"
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.inspection_table.setItem(row, len(INSPECTION_FIELDS), item)
        finally:
            self.inspection_table.blockSignals(False)
        if controls:
            by_id = {control["id"]: control for control in report["drawing_controls"]}
            table = self.characteristic_table
            previous = table.blockSignals(True)
            try:
                for row, control in enumerate(controls):
                    result = by_id[control["id"].strip()]
                    text = result["status"].title()
                    if result["status"] == "evaluated":
                        text += " · PASS" if result["passes"] else " · FAIL"
                    if result.get("reason"):
                        text += " · " + result["reason"]
                    item = QTableWidgetItem(text)
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    table.setItem(row, len(CONTROL_FIELDS), item)
            finally:
                table.blockSignals(previous)
            coverage = report["coverage"]
            summary = (
                f"{coverage['evaluated']}/{coverage['requested']} requested controls evaluated; "
                f"{coverage['passed']} pass, {coverage['failed']} fail, "
                f"{coverage['unsupported']} unsupported, {coverage['unevaluated']} unevaluated."
            )
            self.characteristic_coverage_label.setText(summary)
            self.inspection_result_label.setText(
                summary + " Coverage applies to this recorded inventory. "
                "Review unevaluated controls and measurement uncertainty before disposition."
            )
        else:
            failed = sum(not result["evaluation"]["passes"] for result in report["features"])
            self.inspection_result_label.setText(
                f"{len(report['features']) - failed}/{len(report['features'])} pass supplied position/size checks. "
                "No drawing-control inventory was recorded; whole-drawing coverage is unknown."
            )

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
            save_json(path, report)
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
            drawing_controls=validate_drawing_controls(self._drawing_control_rows()),
            inspection={"drawing": self.inspection_drawing_input.text(), "source": self.inspection_source_input.text(),
                        "datum_frame": self.inspection_datum_input.text(), "units": self.inspection_units_combo.currentText(),
                        "alignment_confirmed": self.inspection_alignment_check.isChecked(),
                        "scope_confirmed": self.inspection_scope_check.isChecked(), "rows": self._inspection_rows(),
                        "row_metadata": self._inspection_row_metadata(),
                        "source_files": deepcopy(self._inspection_source_files)},
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
        metadata = inspection.get("row_metadata")
        for index, row in enumerate(inspection.get("rows", [])):
            self._inspection_add_row(values=row, metadata=metadata[index] if metadata is not None else None,
                                     notify=False)
        self._inspection_source_files = deepcopy(inspection.get("source_files", []))
        self.characteristic_table.setRowCount(0)
        for control in study.get("drawing_controls", []):
            self._drawing_control_add_row(values=control)
        self._invalidate_inspection()
        self._invalidate_stack_report()
        self._inspection_context_changed()

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
