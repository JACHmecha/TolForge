"""Explicit field mapping and review for externally aligned CSV measurements."""
import csv
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from tolstack.inspection import INSPECTION_FIELDS
from tolstack.inspection_import import default_mapping, parse_csv_bytes, preview_import
from gui.table_presentation import configure_table, fit_table_columns


class ImportAlignedCsvDialog(QDialog):
    def __init__(self, source, parent=None, *, dataset_units="mm", existing_names=(),
                 existing_ids=(), existing_units=(), existing_frames=(), datum_frame=""):
        super().__init__(parent)
        self.setWindowTitle("Review aligned CSV measurements")
        self.resize(1050, 820)
        self.source = source
        self._existing = dict(dataset_units=dataset_units, existing_names=tuple(existing_names),
                              existing_ids=tuple(existing_ids), existing_units=tuple(existing_units),
                              existing_frames=tuple(existing_frames))
        self._building = True
        self._accepted_import = None
        self._delimiter_error = None
        self.preview = None
        layout = QVBoxLayout(self)
        intro = QLabel("Map each field to a CSV column or a constant, then review the rows. "
                       "Coordinates must already share the recorded datum frame. "
                       "No coordinate fitting or unit conversion is performed.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.source_label = QLabel(f"{source.path}\nCaptured SHA-256: {source.sha256}")
        self.source_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.source_label)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        content = QVBoxLayout(body)
        form = QFormLayout()
        self.delimiter_combo = QComboBox()
        for title, value in (("Comma", ","), ("Semicolon", ";"), ("Tab", "\t")):
            self.delimiter_combo.addItem(title, value)
        self.delimiter_combo.setCurrentIndex(self.delimiter_combo.findData(source.delimiter))
        form.addRow("CSV delimiter", self.delimiter_combo)
        self.units_combo = QComboBox()
        self.units_combo.addItems(["mm", "in"])
        self.units_combo.setCurrentText(dataset_units)
        form.addRow("Source measurement units", self.units_combo)
        self.datum_frame_input = QLineEdit(datum_frame)
        form.addRow("External datum frame", self.datum_frame_input)
        self.alignment_method_input = QLineEdit()
        self.alignment_method_input.setPlaceholderText("Source alignment procedure / CMM program")
        form.addRow("External alignment method", self.alignment_method_input)
        self.fitting_method_input = QLineEdit("Not recorded by source")
        form.addRow("Source feature fitting method", self.fitting_method_input)
        self.source_id_combo = QComboBox()
        self.source_id_combo.addItem("No source identifier column", None)
        for header in source.headers:
            self.source_id_combo.addItem(header, header)
        form.addRow("Source feature identifier", self.source_id_combo)
        content.addLayout(form)
        self.mapping_table = QTableWidget(len(INSPECTION_FIELDS), 3)
        self.mapping_table.setHorizontalHeaderLabels(["Measurement field", "CSV column / constant", "Constant value"])
        configure_table(self.mapping_table, text_columns=(0, 1, 2))
        self.mapping_table.setMinimumHeight(330)
        self.mapping_inputs = {}
        mapping = default_mapping(source)
        for row, field in enumerate(INSPECTION_FIELDS):
            label = QTableWidgetItem(field.replace("_", " "))
            label.setFlags(label.flags() & ~Qt.ItemIsEditable)
            self.mapping_table.setItem(row, 0, label)
            combo = QComboBox()
            combo.addItem("Use constant", None)
            for header in source.headers:
                combo.addItem(header, header)
            definition = mapping[field]
            combo.setCurrentIndex(combo.findData(definition.get("column")))
            constant = QLineEdit(definition.get("constant", ""))
            constant.setEnabled(combo.currentData() is None)
            self.mapping_table.setCellWidget(row, 1, combo)
            self.mapping_table.setCellWidget(row, 2, constant)
            self.mapping_inputs[field] = (combo, constant)
            combo.currentIndexChanged.connect(lambda index, control=constant, selection=combo:
                                             control.setEnabled(selection.currentData() is None))
            combo.currentIndexChanged.connect(self.refresh_preview)
            constant.textChanged.connect(self.refresh_preview)
        fit_table_columns(self.mapping_table)
        content.addWidget(self.mapping_table)
        self.alignment_check = QCheckBox("I confirm the source measurements and basic coordinates are externally aligned "
                                        "to this datum frame and use the selected units")
        content.addWidget(self.alignment_check)
        content.addWidget(QLabel("Source preview (first 20 rows; validation checks every row)"))
        self.source_preview = QTableWidget()
        configure_table(self.source_preview)
        self.source_preview.setMinimumHeight(150)
        content.addWidget(self.source_preview)
        content.addWidget(QLabel("Mapped measurements (first 20 rows)"))
        self.mapped_preview = QTableWidget()
        configure_table(self.mapped_preview, numeric_columns=range(1, 9), text_columns=(0, 9, 10))
        self.mapped_preview.setMinimumHeight(150)
        content.addWidget(self.mapped_preview)
        self.errors_label = QLabel()
        self.errors_label.setWordWrap(True)
        self.errors_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        content.addWidget(self.errors_label)
        scroll.setWidget(body)
        layout.addWidget(scroll)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Import reviewed measurements")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.delimiter_combo.currentIndexChanged.connect(self._delimiter_changed)
        self.units_combo.currentTextChanged.connect(self.refresh_preview)
        self.source_id_combo.currentIndexChanged.connect(self.refresh_preview)
        self.alignment_check.toggled.connect(self.refresh_preview)
        for widget in (self.datum_frame_input, self.alignment_method_input, self.fitting_method_input):
            widget.textChanged.connect(self.refresh_preview)
        self._building = False
        self.refresh_preview()

    def mapping(self):
        return {field: ({"column": combo.currentData()} if combo.currentData() is not None
                        else {"constant": constant.text()})
                for field, (combo, constant) in self.mapping_inputs.items()}

    def options(self):
        return dict(mapping=self.mapping(), units=self.units_combo.currentText(),
                    external_alignment={"confirmed": self.alignment_check.isChecked(),
                                        "datum_frame": self.datum_frame_input.text(),
                                        "method": self.alignment_method_input.text()},
                    fitting_method=self.fitting_method_input.text(),
                    source_feature_id_column=self.source_id_combo.currentData())

    @staticmethod
    def _fill_table(table, headers, rows):
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(list(headers))
        table.setRowCount(min(20, len(rows)))
        for row, values in enumerate(rows[:20]):
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                table.setItem(row, column, item)
        fit_table_columns(table)

    def _delimiter_changed(self):
        if self._building:
            return
        try:
            candidate = parse_csv_bytes(self.source.contents, self.source.path,
                                        delimiter=self.delimiter_combo.currentData())
        except (ValueError, UnicodeError, csv.Error) as exc:
            # csv.Error and decode failures are shown while leaving the captured source intact.
            self.preview = None
            self._delimiter_error = str(exc)
            self.errors_label.setText(str(exc))
            self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
            return
        self._building = True
        self._delimiter_error = None
        self.source = candidate
        for combo, _ in self.mapping_inputs.values():
            selected = combo.currentData()
            combo.clear()
            combo.addItem("Use constant", None)
            for header in candidate.headers:
                combo.addItem(header, header)
            combo.setCurrentIndex(max(0, combo.findData(selected)))
        selected = self.source_id_combo.currentData()
        self.source_id_combo.clear()
        self.source_id_combo.addItem("No source identifier column", None)
        for header in candidate.headers:
            self.source_id_combo.addItem(header, header)
        self.source_id_combo.setCurrentIndex(max(0, self.source_id_combo.findData(selected)))
        self._building = False
        self.refresh_preview()

    def refresh_preview(self, *args):
        if self._building:
            return
        if self._delimiter_error:
            self.preview = None
            self.errors_label.setText(self._delimiter_error)
            self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
            return
        options = self.options()
        numeric_source_columns = {
            options["mapping"][field].get("column") for field in INSPECTION_FIELDS[1:9]
        }
        text_source_columns = {
            options["mapping"][field].get("column")
            for field in (INSPECTION_FIELDS[0], *INSPECTION_FIELDS[9:])
        }
        configure_table(
            self.source_preview,
            numeric_columns=tuple(index for index, header in enumerate(self.source.headers)
                                  if header in numeric_source_columns - text_source_columns),
            text_columns=tuple(index for index, header in enumerate(self.source.headers)
                               if header not in numeric_source_columns - text_source_columns),
        )
        self._fill_table(self.source_preview, self.source.headers, [record for _, record in self.source.records])
        # Display mapping before confirmation, while acceptance remains gated by the real checkbox.
        display = dict(options)
        display["external_alignment"] = dict(options["external_alignment"], confirmed=True)
        if not display["external_alignment"]["datum_frame"].strip():
            display["external_alignment"]["datum_frame"] = "Preview only"
        if not display["external_alignment"]["method"].strip():
            display["external_alignment"]["method"] = "Preview only"
        mapped = preview_import(self.source, **display).to_dict()["rows"]
        self._fill_table(self.mapped_preview, INSPECTION_FIELDS,
                         [[row[key] for key in INSPECTION_FIELDS] for row in mapped])
        self.preview = preview_import(self.source, **options, **self._existing)
        self.errors_label.setText("\n".join(map(str, self.preview.errors)) if self.preview.errors else
                                  f"All {len(self.source.records)} measurement rows are valid. Review the mapping before import.")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(self.preview.valid)

    def accept(self):
        self.refresh_preview()
        if self.preview is None or not self.preview.valid:
            return
        self._accepted_import = self.preview.accepted()
        super().accept()

    def accepted_import(self):
        from copy import deepcopy
        return deepcopy(self._accepted_import)
