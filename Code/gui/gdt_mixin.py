"""Mixin for the 'GD&T Position' tab: datum reference frame construction
from picked faces/circular edges, pattern-of-features management via a
table, and nominal + Monte Carlo position tolerance evaluation.

Reuses MeasurementMixin's own circle/plane fitting (_fit_circle,
_fit_normal_or_direction) to turn a picked face or circular edge into a
(point, direction) datum feature or a (center, diameter) pattern feature
- no new geometry-fitting code, just new interpretation of the same
fits.
"""

import numpy as np
from PySide6.QtWidgets import QMessageBox, QInputDialog, QTableWidgetItem

from tolstack.gdt import (
    DatumFeature, build_datum_reference_frame,
    PatternFeature, PatternPositionControl,
    evaluate_pattern_nominal, run_pattern_monte_carlo,
)

# Column layout for self.pattern_table - kept short since this table lives
# in a ~350-450px sidebar; the full meaning of each is in the tab's own
# intro label and in the Pick-feature dialog, not in the header text.
PATTERN_COLUMNS = [
    "Name", "Basic X", "Basic Y", "Actual X", "Actual Y", "\u2300",
    "PosTol\u00b1X", "PosTol\u00b1Y", "SizeTol\u00b1", "Status",
]


class GdtMixin:
    """Expects the host class (TolstackWindow) to provide, from its own
    __init__: self._step_entity_info, self.step_status_label, plus the
    GD&T-tab widgets built in app.py: self.datum_slot_labels (dict for
    "Primary"/"Secondary"/"Tertiary"), self.drf_status_label,
    self.pattern_table (QTableWidget with PATTERN_COLUMNS),
    self.gdt_base_tolerance_input, self.gdt_modifier_combo,
    self.gdt_mmc_size_input, self.gdt_lmc_size_input,
    self.gdt_feature_kind_combo, self.gdt_iterations_input,
    self.gdt_default_cpk_input, self.gdt_result_labels (dict),
    self.gdt_figure / self.gdt_canvas.
    """

    def _gdt_init_state(self):
        self._datum_slot = {"Primary": None, "Secondary": None, "Tertiary": None}
        self._datum_arm = None
        self._current_drf = None
        self._pattern_arm = False

    # ------------------------------------------------------------------
    # Datum picking
    # ------------------------------------------------------------------

    def datum_arm_primary(self):
        self._datum_arm_slot("Primary")

    def datum_arm_secondary(self):
        self._datum_arm_slot("Secondary")

    def datum_arm_tertiary(self):
        self._datum_arm_slot("Tertiary")

    def _datum_arm_slot(self, slot: str):
        self._datum_arm = slot
        self.step_status_label.setText(
            f"Click a face or a circular edge/hole in the viewport to set it as the {slot} datum."
        )

    def datum_clear_primary(self):
        self._datum_clear_slot("Primary")

    def datum_clear_secondary(self):
        self._datum_clear_slot("Secondary")

    def datum_clear_tertiary(self):
        self._datum_clear_slot("Tertiary")

    def _datum_clear_slot(self, slot: str):
        self._datum_slot[slot] = None
        self._current_drf = None
        self._update_datum_labels()
        self.drf_status_label.setText("Datum reference frame not built yet.")

    def _datum_on_pick(self, obj) -> bool:
        """Called from StepViewerMixin._on_step_entity_picked. Returns
        True if this pick was consumed for a datum slot."""
        if not self._pattern_arm and self._datum_arm is None:
            return False

        info = self._step_entity_info.get(id(obj)) if obj is not None else None
        if info is None:
            self.step_status_label.setText("No entity under that click - still waiting.")
            return True

        if self._pattern_arm:
            self._pattern_consume_pick(info)
            self._pattern_arm = False
            return True

        point, direction, description = self._gdt_extract_datum_geometry(info)
        if point is None:
            QMessageBox.warning(
                self, "Can't use this as a datum",
                "A datum needs a face (uses its best-fit plane) or a circular "
                "edge/hole (uses its fitted center + axis) - a vertex or a "
                "clearly non-circular edge doesn't define an orientation."
            )
            return True

        slot = self._datum_arm
        self._datum_slot[slot] = {"point": point, "direction": direction, "description": description}
        self._datum_arm = None
        self._update_datum_labels()
        return True

    def _gdt_extract_datum_geometry(self, info: dict):
        """Returns (point, direction, description) for a face or circular
        edge, or (None, None, None) if the entity can't serve as a datum
        feature (vertex, or an edge that doesn't fit a circle)."""
        points = np.asarray(info["points"], dtype=float)

        if info["type"] == "face":
            centroid, normal = self._fit_normal_or_direction(points, "face")
            if normal is None:
                return None, None, None
            return centroid, normal, f"Face #{info['index']}"

        if info["type"] == "edge":
            self._measure_ensure_circle_fit(info)
            circle = info.get("circle")
            if circle is None:
                return None, None, None
            return circle["center"], circle["normal"], f"Edge #{info['index']} (circle center)"

        return None, None, None

    def _update_datum_labels(self):
        for slot, label_widget in self.datum_slot_labels.items():
            entry = self._datum_slot[slot]
            label_widget.setText(f"{slot}: (none)" if entry is None else f"{slot}: {entry['description']}")

    def build_datum_frame(self):
        if any(self._datum_slot[s] is None for s in ("Primary", "Secondary", "Tertiary")):
            QMessageBox.warning(self, "Missing datums", "Pick a Primary, Secondary, and Tertiary datum first.")
            return

        try:
            def to_datum_feature(entry):
                return DatumFeature(point=entry["point"], direction=entry["direction"])

            primary = to_datum_feature(self._datum_slot["Primary"])
            secondary = to_datum_feature(self._datum_slot["Secondary"])
            tertiary = to_datum_feature(self._datum_slot["Tertiary"])
            self._current_drf = build_datum_reference_frame(primary, secondary, tertiary)
        except ValueError as exc:
            QMessageBox.warning(self, "Could not build datum frame", str(exc))
            return

        origin = self._current_drf.origin
        self.drf_status_label.setText(
            f"DRF built. Origin: ({origin[0]:.4f}, {origin[1]:.4f}, {origin[2]:.4f})  "
            "Ready to pick pattern features."
        )

    # ------------------------------------------------------------------
    # Pattern feature management
    # ------------------------------------------------------------------

    def pattern_arm_pick(self):
        if self._current_drf is None:
            QMessageBox.warning(self, "No datum frame", "Build the datum reference frame first.")
            return
        self._pattern_arm = True
        self.step_status_label.setText("Click a circular hole/feature in the viewport to add it to the pattern.")

    def _pattern_consume_pick(self, info: dict):
        self._measure_ensure_circle_fit(info)
        circle = info.get("circle")
        if circle is None:
            QMessageBox.warning(
                self, "Not a circular feature",
                "Pattern features need to be circular (a hole's edge or face) so a diameter can be fit."
            )
            return

        name, ok = QInputDialog.getText(self, "Feature name", "Name:", text=f"Feature{self.pattern_table.rowCount() + 1}")
        if not ok or not name.strip():
            return
        name = name.strip()

        x_local, y_local = self._current_drf.to_local_xy(circle["center"])
        basic_x, ok = QInputDialog.getDouble(self, "Basic X", "Basic (theoretical exact) X, per the drawing:", x_local, -1e6, 1e6, 4)
        if not ok:
            return
        basic_y, ok = QInputDialog.getDouble(self, "Basic Y", "Basic (theoretical exact) Y, per the drawing:", y_local, -1e6, 1e6, 4)
        if not ok:
            return

        self._pattern_add_row(name, basic_x, basic_y, x_local, y_local, circle["radius"] * 2)

    def _pattern_add_row(self, name, basic_x, basic_y, actual_x, actual_y, diameter):
        table = self.pattern_table
        row = table.rowCount()
        table.insertRow(row)

        table.setItem(row, 0, QTableWidgetItem(name))
        table.setItem(row, 1, QTableWidgetItem(f"{basic_x:.4f}"))
        table.setItem(row, 2, QTableWidgetItem(f"{basic_y:.4f}"))
        table.setItem(row, 3, QTableWidgetItem(f"{actual_x:.4f}"))
        table.setItem(row, 4, QTableWidgetItem(f"{actual_y:.4f}"))
        table.setItem(row, 5, QTableWidgetItem(f"{diameter:.4f}"))
        table.setItem(row, 6, QTableWidgetItem("0.0"))
        table.setItem(row, 7, QTableWidgetItem("0.0"))
        table.setItem(row, 8, QTableWidgetItem("0.0"))
        table.setItem(row, 9, QTableWidgetItem("-"))
        table.resizeColumnsToContents()

    def pattern_remove_selected(self):
        rows = sorted({idx.row() for idx in self.pattern_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.pattern_table.removeRow(row)

    # ------------------------------------------------------------------
    # Reading the table into tolstack.gdt objects
    # ------------------------------------------------------------------

    def _pattern_read_features(self) -> list:
        table = self.pattern_table
        features = []
        for row in range(table.rowCount()):
            def cell(col):
                item = table.item(row, col)
                return item.text() if item is not None else ""

            features.append(PatternFeature(
                name=cell(0),
                basic_x=float(cell(1)), basic_y=float(cell(2)),
                actual_x=float(cell(3)), actual_y=float(cell(4)),
                size_nominal=float(cell(5)), size_tol_plus=float(cell(8) or 0.0), size_tol_minus=float(cell(8) or 0.0),
                position_tol_plus_x=float(cell(6) or 0.0), position_tol_minus_x=float(cell(6) or 0.0),
                position_tol_plus_y=float(cell(7) or 0.0), position_tol_minus_y=float(cell(7) or 0.0),
            ))
        return features

    def _pattern_read_control(self) -> PatternPositionControl:
        try:
            base_tol = float(self.gdt_base_tolerance_input.text() or 0.0)
            mmc_size = float(self.gdt_mmc_size_input.text() or 0.0)
            lmc_size = float(self.gdt_lmc_size_input.text() or 0.0)
        except ValueError as exc:
            raise ValueError("Base tolerance, MMC size, and LMC size must all be numbers.") from exc

        return PatternPositionControl(
            features=self._pattern_read_features(),
            base_tolerance_diameter=base_tol,
            modifier=self.gdt_modifier_combo.currentText(),
            mmc_size=mmc_size,
            lmc_size=lmc_size,
            feature_kind=self.gdt_feature_kind_combo.currentText(),
        )

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate_pattern_deterministic(self):
        if self.pattern_table.rowCount() == 0:
            QMessageBox.warning(self, "No features", "Add at least one feature to the pattern first.")
            return
        try:
            control = self._pattern_read_control()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid input", str(exc))
            return

        results = evaluate_pattern_nominal(control)
        for row, (name, evaluation) in enumerate(results):
            status = "PASS" if evaluation.passes else "FAIL"
            text = f"{status} margin {evaluation.margin:+.3f} (bonus {evaluation.bonus_tolerance:.3f})"
            self.pattern_table.setItem(row, 9, QTableWidgetItem(text))
        self.pattern_table.resizeColumnsToContents()

        n_fail = sum(1 for _, ev in results if not ev.passes)
        self.gdt_result_labels["nominal"].setText(
            f"{len(results) - n_fail}/{len(results)} features pass (as-modeled/as-measured, no statistical variation)."
        )

    def run_pattern_monte_carlo_analysis(self):
        if self.pattern_table.rowCount() == 0:
            QMessageBox.warning(self, "No features", "Add at least one feature to the pattern first.")
            return
        try:
            control = self._pattern_read_control()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid input", str(exc))
            return

        iterations = self.gdt_iterations_input.value()
        default_cpk_text = self.gdt_default_cpk_input.text().strip()
        default_cpk = float(default_cpk_text) if default_cpk_text else None

        try:
            mc = run_pattern_monte_carlo(control, iterations=iterations, default_cpk=default_cpk)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Cpk", str(exc))
            return

        labels = self.gdt_result_labels
        labels["pattern_fail_rate"].setText(f"{mc.pattern_fail_rate * 100:.2f} % of samples have >=1 feature out of tolerance")
        per_feature_text = ", ".join(f"{name}: {rate*100:.2f}%" for name, rate in mc.per_feature_fail_rate.items())
        labels["per_feature"].setText(per_feature_text)

        self.gdt_figure.clear()
        ax = self.gdt_figure.add_subplot(111)
        ax.hist(mc.worst_feature_margin, bins=40, color="#e45756", edgecolor="white")
        ax.axvline(0, color="black", linewidth=1, linestyle="--")
        ax.set_xlabel("Worst-feature margin (allowed - error; <0 = pattern fails)")
        ax.set_ylabel("Samples")
        ax.set_title("Pattern position tolerance - worst-feature margin distribution")
        self.gdt_figure.tight_layout()
        self.gdt_canvas.setVisible(True)
        self.gdt_canvas.draw()
