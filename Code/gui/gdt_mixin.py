"""GD&T workspace: datum construction, inspection, and position patterns.

Datum extraction uses analytic STEP plane/cylinder metadata where available,
validated planar fallback points, or validated circular-edge fits. Cylinders
supply axes rather than fitted plane normals. Supported plane/axis frames
and their restrictions are implemented in tolstack.gdt. DatumInspectionMixin
renders datum membership, labels, origin, and axes. Pattern evaluation adapts
project definitions into nominal and Monte Carlo position/size checks.
"""

import numpy as np
from dataclasses import asdict
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QInputDialog, QTableWidgetItem

from tolstack.gdt import (
    DatumFeature, build_datum_reference_frame,
    PatternFeature, PatternPositionControl,
    evaluate_pattern_nominal, run_pattern_monte_carlo, virtual_condition,
)
from gui.theme import COLORS, style_axes
from gui.datum_inspection import DatumInspectionMixin, DATUM_STYLES
from tolstack.analysis import parse_optional_cpk, parse_seed

# Column layout for self.pattern_table - kept short since this table lives
# in a ~350-450px sidebar; the full meaning of each is in the tab's own
# intro label and in the Pick-feature dialog, not in the header text.
PATTERN_COLUMNS = [
    "Name", "Basic X", "Basic Y", "Actual X", "Actual Y", "\u2300",
    "PosTol\u00b1X", "PosTol\u00b1Y", "SizeTol\u00b1", "Status",
]


class GdtMixin(DatumInspectionMixin):
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
        self._datum_visual_objects = []
        self._datum_original_colors = []

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
        self._pattern_arm = False
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

        slot = self._datum_arm
        self._datum_arm = None
        self._set_datum_from_info(slot, info)
        return True

    def _set_datum_from_info(self, slot: str, info: dict) -> bool:
        """Assign a picked feature directly; used by armed picks and context menus."""
        point, direction, description = self._gdt_extract_datum_geometry(info)
        if point is None:
            QMessageBox.warning(
                self, "Can't use this as a datum",
                "A datum needs a face (uses its best-fit plane) or a circular "
                "edge/hole. Only planar faces and analytically recognized cylindrical "
                "faces are supported; other curved faces cannot define this datum."
            )
            return False
        try:
            feature_id = self._project_register_feature(info, label=f"Datum {slot}")
        except ValueError as exc:
            QMessageBox.warning(self, "Could not register datum feature", str(exc))
            return False
        self._datum_slot[slot] = {
            "point": point, "direction": direction, "description": description,
            "feature_id": feature_id,
            "kind": self._gdt_datum_kind(info),
        }
        self._current_drf = None
        self._pattern_arm = False
        self.drf_status_label.setText("Datum assignment changed. Rebuild the reference frame to update its origin and axes.")
        if hasattr(self, "_update_selection_inspector"):
            self._update_selection_inspector(info)
        self._update_datum_labels()
        if hasattr(self, "_show_workspace"):
            self._show_workspace("gdt")
        return True

    def _gdt_extract_datum_geometry(self, info: dict):
        """Returns (point, direction, description) for a face or circular
        edge, or (None, None, None) if the entity can't serve as a datum
        feature (vertex, or an edge that doesn't fit a circle)."""
        points = np.asarray(info["points"], dtype=float)

        if info["type"] == "face":
            surface = info.get("surface")
            if surface is not None:
                kind = surface.get("kind")
                if kind in {"cylinder", "plane"}:
                    point = np.asarray(surface["point"], dtype=float)
                    normal = np.asarray(surface["direction"], dtype=float)
                    normal = normal / np.linalg.norm(normal)
                    # Put the display anchor near this trimmed face while
                    # preserving the exact underlying plane/axis location.
                    centroid = points.mean(axis=0)
                    if kind == "cylinder":
                        point = point + normal * np.dot(centroid - point, normal)
                        description = f"Cylindrical face #{info['index']} · axis · Ø{2 * surface['radius']:.4f}"
                    else:
                        point = centroid - normal * np.dot(centroid - point, normal)
                        description = f"Planar face #{info['index']}"
                    return point, normal, description
                return None, None, None
            centroid, normal = self._fit_normal_or_direction(points, "face")
            if normal is None:
                return None, None, None
            # Legacy/test geometry without CAD metadata: accept only points
            # lying in a plane, never infer a cylinder from an SVD normal.
            extent = max(np.linalg.norm(np.ptp(points, axis=0)), 1e-9)
            if np.max(np.abs((points - centroid) @ normal)) > extent * 1e-6:
                return None, None, None
            return centroid, normal, f"Face #{info['index']}"

        if info["type"] == "edge":
            if not self._context_is_circular_edge(info):
                return None, None, None
            self._measure_ensure_circle_fit(info)
            circle = info.get("circle")
            if circle is None:
                return None, None, None
            return circle["center"], circle["normal"], f"Edge #{info['index']} (circle center)"

        return None, None, None

    @staticmethod
    def _gdt_datum_kind(info):
        return "axis" if info["type"] == "edge" or (info.get("surface") or {}).get("kind") == "cylinder" else "plane"

    def _update_datum_labels(self):
        self._invalidate_gdt_results()
        for slot, label_widget in self.datum_slot_labels.items():
            entry = self._datum_slot[slot]
            letter, _color = DATUM_STYLES[slot]
            label_widget.setText(f"{letter} · {slot}: (none)" if entry is None else f"{letter} · {slot}: {entry['description']}")
        self._refresh_datum_inspection()
        self._update_inspected_datum_label()

    def build_datum_frame(self):
        self._current_drf = None
        if any(self._datum_slot[s] is None for s in ("Primary", "Secondary", "Tertiary")):
            self._refresh_datum_inspection()
            QMessageBox.warning(self, "Missing datums", "Pick a Primary, Secondary, and Tertiary datum first.")
            return

        try:
            def to_datum_feature(entry):
                return DatumFeature(point=entry["point"], direction=entry["direction"], kind=entry.get("kind", "plane"))

            primary = to_datum_feature(self._datum_slot["Primary"])
            secondary = to_datum_feature(self._datum_slot["Secondary"])
            tertiary = to_datum_feature(self._datum_slot["Tertiary"])
            self._current_drf = build_datum_reference_frame(primary, secondary, tertiary)
        except ValueError as exc:
            self.drf_status_label.setText("Datum frame could not be built. Check datum assignments.")
            self._refresh_datum_inspection()
            QMessageBox.warning(self, "Could not build datum frame", str(exc))
            return

        origin = self._current_drf.origin
        self._refresh_datum_inspection()
        self.drf_status_label.setText(
            f"DRF origin in model coordinates ({self.project.units.length}): "
            f"({origin[0]:.4f}, {origin[1]:.4f}, {origin[2]:.4f}). "
            "O marks local (0, 0, 0). Ready to pick pattern features."
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

        try:
            feature_id = self._project_register_feature(info, label=name)
        except ValueError as exc:
            QMessageBox.warning(self, "Could not register pattern feature", str(exc))
            return
        self._pattern_add_row(
            name, basic_x, basic_y, x_local, y_local, circle["radius"] * 2,
            feature_id=feature_id,
        )

    def _pattern_add_row(
        self, name, basic_x, basic_y, actual_x, actual_y, diameter,
        feature_id=None,
    ):
        table = self.pattern_table
        row = table.rowCount()
        table.insertRow(row)

        name_item = QTableWidgetItem(name)
        if feature_id and hasattr(self, "PATTERN_FEATURE_ID_ROLE"):
            name_item.setData(self.PATTERN_FEATURE_ID_ROLE, feature_id)
        table.setItem(row, 0, name_item)
        table.setItem(row, 1, QTableWidgetItem(f"{basic_x:.4f}"))
        table.setItem(row, 2, QTableWidgetItem(f"{basic_y:.4f}"))
        table.setItem(row, 3, QTableWidgetItem(f"{actual_x:.4f}"))
        table.setItem(row, 4, QTableWidgetItem(f"{actual_y:.4f}"))
        table.setItem(row, 5, QTableWidgetItem(f"{diameter:.4f}"))
        table.setItem(row, 6, QTableWidgetItem("0.0"))
        table.setItem(row, 7, QTableWidgetItem("0.0"))
        table.setItem(row, 8, QTableWidgetItem("0.0"))
        table.setItem(row, 9, QTableWidgetItem("-"))
        for column in (3, 4):
            item = table.item(row, column)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
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

    def _invalidate_gdt_results(self, *args):
        if args and hasattr(args[0], "column") and args[0].column() == 9:
            return
        self._last_gdt_report = None
        for label in getattr(self, "gdt_result_labels", {}).values():
            label.setText("Inputs changed — evaluate again.")
        if hasattr(self, "gdt_canvas"):
            self.gdt_canvas.setVisible(False)
        if hasattr(self, "pattern_table"):
            previous = self.pattern_table.blockSignals(True)
            for row in range(self.pattern_table.rowCount()):
                item = QTableWidgetItem("Not evaluated")
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.pattern_table.setItem(row, 9, item)
            self.pattern_table.blockSignals(previous)

    def _gdt_report_base(self, control):
        return {
            "report_type": "cad_position_prediction", "units": self.project.units.length,
            "control": asdict(control), "datum_frame": {
                name: getattr(self._current_drf, name).tolist()
                for name in ("origin", "x_axis", "y_axis", "z_axis")
            },
            "cad_sources": [part.source_file for part in self.project.parts.values()],
            "limitations": ["CAD positions are not manufactured-part measurements.",
                            "Single-segment position and size; parallel feature axes; no datum mobility, form or general orientation.",
                            "Independent XY/size process samples; no full assembly variation model."],
        }

    def _export_gdt_report(self):
        report = getattr(self, "_last_gdt_report", None)
        if report is None:
            QMessageBox.warning(self, "No current report", "Evaluate the current CAD pattern before exporting.")
            return
        self._save_report(report, "cad-position-report.json")

    def evaluate_pattern_deterministic(self):
        self._invalidate_gdt_results()
        if self.pattern_table.rowCount() == 0:
            QMessageBox.warning(self, "No features", "Add at least one feature to the pattern first.")
            return
        try:
            control = self._project_build_pattern_control()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid input", str(exc))
            return

        try:
            results = evaluate_pattern_nominal(control)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid GD&T definition", str(exc))
            return
        for row, (name, evaluation) in enumerate(results):
            if evaluation.passes:
                status = "PASS"
            elif not evaluation.size_conforming and not evaluation.position_conforming:
                status = "FAIL SIZE+POSITION"
            elif not evaluation.size_conforming:
                status = "FAIL SIZE"
            else:
                status = "FAIL POSITION"
            text = (
                f"{status} overall {evaluation.margin:+.3f}; "
                f"size {evaluation.size_margin:+.3f}, "
                f"position {evaluation.position_margin:+.3f} "
                f"(bonus {evaluation.bonus_tolerance:.3f})"
            )
            item = QTableWidgetItem(text)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.pattern_table.setItem(row, 9, item)
        self.pattern_table.resizeColumnsToContents()
        self._last_gdt_report = self._gdt_report_base(control)
        self._last_gdt_report.update(method="as_modeled", features=[
            {"name": name, "evaluation": asdict(evaluation)} for name, evaluation in results])

        n_fail = sum(1 for _, ev in results if not ev.passes)
        self.gdt_result_labels["nominal"].setText(
            f"{len(results) - n_fail}/{len(results)} features pass (as-modeled/as-measured, no statistical variation)."
        )
        if control.modifier == "MMC":
            boundary = virtual_condition(
                control.mmc_size, control.base_tolerance_diameter,
                control.feature_kind,
            )
            self.gdt_result_labels["virtual_condition"].setText(
                f"{control.feature_kind.title()} boundary: ⌀{boundary:.4f}"
            )
        else:
            self.gdt_result_labels["virtual_condition"].setText(
                "A fixed virtual-condition boundary requires an MMC modifier."
            )

    def run_pattern_monte_carlo_analysis(self):
        self._invalidate_gdt_results()
        if self.pattern_table.rowCount() == 0:
            QMessageBox.warning(self, "No features", "Add at least one feature to the pattern first.")
            return
        try:
            control = self._project_build_pattern_control()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid input", str(exc))
            return

        iterations = self.gdt_iterations_input.value()
        try:
            default_cpk = parse_optional_cpk(self.gdt_default_cpk_input.text(), "GD&T Cpk")
            seed_widget = getattr(self, "seed_input", None)
            seed = parse_seed(seed_widget.text()) if seed_widget is not None else None
            mc = run_pattern_monte_carlo(control, iterations=iterations, default_cpk=default_cpk, seed=seed)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Cpk", str(exc))
            return

        labels = self.gdt_result_labels
        self._last_gdt_report = self._gdt_report_base(control)
        self._last_gdt_report.update(
            method="monte_carlo", iterations=iterations, default_cpk=default_cpk, seed=seed,
            pattern_fail_rate=mc.pattern_fail_rate, per_feature_fail_rate=mc.per_feature_fail_rate,
            per_feature_size_fail_rate=mc.per_feature_size_fail_rate,
            per_feature_position_fail_rate=mc.per_feature_position_fail_rate,
        )
        labels["pattern_fail_rate"].setText(f"{mc.pattern_fail_rate * 100:.2f} % of samples have >=1 feature out of tolerance")
        per_feature_text = ", ".join(
            f"{name}: total {rate*100:.2f}% "
            f"(size {mc.per_feature_size_fail_rate[name]*100:.2f}%, "
            f"position {mc.per_feature_position_fail_rate[name]*100:.2f}%)"
            for name, rate in mc.per_feature_fail_rate.items()
        )
        labels["per_feature"].setText(per_feature_text)

        self.gdt_figure.clear()
        ax = self.gdt_figure.add_subplot(111)
        ax.hist(
            mc.worst_feature_margin, bins=40, color=COLORS["negative"],
            edgecolor=COLORS["panel"],
        )
        ax.axvline(0, color=COLORS["selection"], linewidth=1.4, linestyle="--")
        ax.set_xlabel("Worst-feature margin (allowed - error; <0 = pattern fails)")
        ax.set_ylabel("Samples")
        ax.set_title("Pattern position tolerance - worst-feature margin distribution")
        style_axes(ax)
        self.gdt_figure.tight_layout()
        self.gdt_canvas.setVisible(True)
        self.gdt_canvas.draw()
