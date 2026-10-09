"""Mixin for projected circular aperture loss and hole/pin interference.

Wires the widgets (built in app.py) to the pure-math functions in
tolstack.eclipse and tolstack.projected_interference. Pulls nominal diameter
and center-offset values directly from whatever circles are currently
fit in the Measure tab, instead of retyping numbers that were already
just measured from the STEP geometry.
"""

from contextlib import contextmanager
from copy import deepcopy

import numpy as np
from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QMessageBox

from tolstack.eclipse import ToleranceInput, EclipseInputs, run_monte_carlo, worst_case
from tolstack.models import finite_number
from tolstack.analysis import parse_seed
from tolstack.length_units import convert_length
from tolstack.projected_geometry import projection_from_circles
from tolstack.projected_interference import (
    PinHoleInputs, run_pin_hole_monte_carlo, radial_clearance_bounds,
)
from gui.theme import COLORS, style_axes


class EclipseMixin:
    """Expects the host class (TolstackWindow) to provide, from its own
    __init__: self.bank (unused here directly, but MeasurementMixin's
    slots are read from self._measure_slot), plus the projected-interference widgets
    built in app.py: for each of "handle", "sticker", "offset_x",
    "offset_y" - self.eclipse_<name>_nominal_input, _tol_plus_input,
    _tol_minus_input, _cpk_input (all QLineEdit); self.eclipse_iterations_input
    (QSpinBox); self.eclipse_threshold_input (QLineEdit); self.eclipse_result_labels
    (area and clearance statistics, full-zone bounds and probabilities);
    self.eclipse_figure / self.eclipse_canvas (matplotlib).
    """

    # ------------------------------------------------------------------
    # Reading inputs
    # ------------------------------------------------------------------

    def _eclipse_is_pin_mode(self):
        combo = getattr(self, "eclipse_mode_combo", None)
        return combo is not None and combo.currentIndex() == 1

    def _eclipse_length_unit(self):
        return getattr(self, "_eclipse_units", "mm")

    @staticmethod
    def _eclipse_set_text(widget, text):
        widget.setText(text)
        # Programmatic full-precision values should show their sign/leading
        # digits rather than scrolling narrow editors to the trailing digits.
        if hasattr(widget, "setCursorPosition"):
            widget.setCursorPosition(0)
            widget.setToolTip(text)

    @contextmanager
    def _eclipse_widget_update(self):
        widgets = [getattr(self, f"eclipse_{prefix}_{field}_input")
                   for prefix in ("handle", "sticker", "offset_x", "offset_y")
                   for field in ("nominal", "tol_plus", "tol_minus", "cpk")]
        widgets += [self.eclipse_units_combo, self.eclipse_mode_combo,
                    self.eclipse_reference_axis_combo, self.eclipse_seed_input,
                    self.eclipse_iterations_input, self.eclipse_threshold_input]
        blockers = [QSignalBlocker(widget) for widget in widgets]
        was_restoring = getattr(self, "_eclipse_restoring", False)
        self._eclipse_restoring = True
        try:
            yield
        finally:
            blockers.clear()
            self._eclipse_restoring = was_restoring

    def _eclipse_units_changed(self, target):
        if getattr(self, "_eclipse_restoring", False):
            return
        source = self._eclipse_length_unit()
        if source == target:
            return
        converted = []
        try:
            for prefix in ("handle", "sticker", "offset_x", "offset_y"):
                for field in ("nominal", "tol_plus", "tol_minus"):
                    widget = getattr(self, f"eclipse_{prefix}_{field}_input")
                    raw = widget.text()
                    converted.append((widget, repr(convert_length(raw, source, target)) if raw.strip() else raw))
        except ValueError as exc:
            with QSignalBlocker(self.eclipse_units_combo):
                self.eclipse_units_combo.setCurrentText(source)
            QMessageBox.warning(self, "Could not change length units", f"Complete finite length values before converting units. {exc}")
            return
        with self._eclipse_widget_update():
            for widget, text in converted:
                self._eclipse_set_text(widget, text)
            self._eclipse_units = target
        self._eclipse_mode_changed()
        self._eclipse_show_projection()

    def _eclipse_reference_axis_changed(self, *_):
        if getattr(self, "_eclipse_restoring", False):
            return
        self._eclipse_projection_frame = None
        self._eclipse_show_projection()
        self._eclipse_clear_results()

    def _eclipse_nominal_changed(self, *_):
        if getattr(self, "_eclipse_restoring", False):
            return
        self._eclipse_projection_frame = None
        self._eclipse_show_projection()

    def _eclipse_projection_snapshot(self):
        return {"reference_axis": self.eclipse_reference_axis_combo.currentText(),
                "source_units": "mm", "frame": deepcopy(getattr(self, "_eclipse_projection_frame", None))}

    def _eclipse_restore_projection(self, projection):
        self._eclipse_units = self.eclipse_units_combo.currentText()
        self._eclipse_projection_frame = deepcopy((projection or {}).get("frame"))
        self._eclipse_show_projection()
        self._eclipse_clear_results()

    def _eclipse_show_projection(self):
        label = getattr(self, "eclipse_projection_label", None)
        if label is None:
            return
        frame = getattr(self, "_eclipse_projection_frame", None)
        if frame is None:
            label.setText("Manual inputs · CAD reference selection applies on the next measured-pair transfer. Tilt limit: 0.1°.")
            return
        vector = lambda key: "(" + ", ".join(f"{v:.3g}" for v in frame[key]) + ")"
        fallback = " (fallback)" if frame["reference_axis"] != frame["requested_reference_axis"] else ""
        label.setText(f"CAD plane at A · Reference {frame['reference_axis']}{fallback} · "
                      f"X direction {vector('x_axis')}, Y direction {vector('y_axis')} · "
                      f"Axis mismatch {frame['axis_angle_deg']:.4g}° (limit 0.1°) · CAD lengths converted from mm.")

    def _eclipse_save_settings(self):
        inputs = self._eclipse_read_all_inputs()
        seed = parse_seed(self.eclipse_seed_input.text())
        threshold = finite_number(self.eclipse_threshold_input.text(), "Projected interference threshold (%)")
        if not 0 <= threshold <= 100:
            raise ValueError("Projected interference threshold must be from 0 to 100%.")
        settings = {
            "mode": "hole-pin" if self._eclipse_is_pin_mode() else "hole-hole",
            "units": self._eclipse_length_unit(), "seed": seed,
            "iterations": self._eclipse_read_iterations(), "threshold": threshold,
            "inputs": {prefix: {key: getattr(value, key) for key in ("nominal", "tol_plus", "tol_minus", "cpk")}
                       for prefix, value in zip(("handle", "sticker", "offset_x", "offset_y"),
                                                (inputs.handle_diameter, inputs.sticker_diameter, inputs.offset_x, inputs.offset_y))},
            "projection": self._eclipse_projection_snapshot(),
        }
        untouched = (settings["mode"] == "hole-hole" and settings["units"] == "mm" and seed is None
                     and settings["iterations"] == 10000 and threshold == 20
                     and settings["projection"]["reference_axis"] == "X" and settings["projection"]["frame"] is None
                     and all(v["nominal"] == v["tol_plus"] == v["tol_minus"] == 0 and v["cpk"] is None
                             for v in settings["inputs"].values()))
        if untouched:
            return None
        inputs.validate()
        return settings

    def _eclipse_restore_settings(self, settings):
        settings = settings or {}
        projection = settings.get("projection") or {}
        with self._eclipse_widget_update():
            self._eclipse_units = settings.get("units", "mm")
            self.eclipse_units_combo.setCurrentText(self._eclipse_units)
            self.eclipse_mode_combo.setCurrentIndex(1 if settings.get("mode") == "hole-pin" else 0)
            self.eclipse_reference_axis_combo.setCurrentText(projection.get("reference_axis", "X"))
            seed = settings.get("seed")
            self.eclipse_seed_input.setText("" if seed is None else str(seed))
            self.eclipse_iterations_input.setValue(settings.get("iterations", 10000))
            self.eclipse_threshold_input.setText(str(settings.get("threshold", 20.0)))
            for prefix in ("handle", "sticker", "offset_x", "offset_y"):
                values = settings.get("inputs", {}).get(prefix, {})
                for field in ("nominal", "tol_plus", "tol_minus", "cpk"):
                    value = values.get(field, None if field == "cpk" else 0.0)
                    self._eclipse_set_text(getattr(self, f"eclipse_{prefix}_{field}_input"), "" if value is None else repr(float(value)))
            self._eclipse_projection_frame = deepcopy(projection.get("frame"))
        self._eclipse_mode_changed()
        self._eclipse_show_projection()

    def _eclipse_update_preview(self):
        preview = getattr(self, "eclipse_preview", None)
        if preview is None:
            return
        try:
            values = [finite_number(getattr(self, f"eclipse_{prefix}_nominal_input").text(), "Nominal length")
                      for prefix in ("handle", "sticker", "offset_x", "offset_y")]
        except ValueError:
            preview.clear()
            return
        preview.set_geometry(*values, "hole-pin" if self._eclipse_is_pin_mode() else "hole-hole", self._eclipse_length_unit())

    def _eclipse_read_iterations(self):
        widget = self.eclipse_iterations_input
        if hasattr(widget, "hasAcceptableInput"):
            if not widget.hasAcceptableInput():
                raise ValueError("Iterations must be a complete integer from 100 to 1000000.")
            widget.interpretText()
        return widget.value()

    def _eclipse_mode_changed(self, *_):
        pin_mode = self._eclipse_is_pin_mode()
        self.eclipse_canvas.setMinimumHeight(400 if pin_mode else 240)
        units = self._eclipse_length_unit()
        self.eclipse_handle_caption.setText(("Hole diameter" if pin_mode else "Hole A diameter") + f" ({units})")
        self.eclipse_sticker_caption.setText(("Pin diameter" if pin_mode else "Hole B diameter") + f" ({units})")
        self.eclipse_offset_x_caption.setText(f"Position offset X ({units})")
        self.eclipse_offset_y_caption.setText(f"Position offset Y ({units})")
        description = (
            "Area of the pin outside the hole and minimum radial clearance. "
            "Positive clearance = gap; zero = contact; negative = interference. "
            "Measured A is the hole; measured B is the pin."
            if pin_mode else
            "Loss of common opening area relative to the smaller hole, "
            "given diameter and relative position tolerances."
        )
        self.eclipse_intro.setText(description + " Circular features are projected into a common plane "
                                   "perpendicular to the insertion axis; tilt, depth and deformation are not modeled.")
        self.eclipse_result_captions["mean"].setText("Mean pin area outside:" if pin_mode else "Mean aperture loss:")
        for key, widgets in self.eclipse_result_rows.items():
            if key == "worst_case":
                visible = not pin_mode
            elif key.startswith("clearance_") or key == "interference":
                visible = pin_mode
            else:
                visible = True
            for widget in widgets:
                widget.setVisible(visible)
        self._eclipse_clear_results()

    def _eclipse_read_input(self, prefix: str) -> ToleranceInput:
        nominal_widget = getattr(self, f"eclipse_{prefix}_nominal_input")
        tol_plus_widget = getattr(self, f"eclipse_{prefix}_tol_plus_input")
        tol_minus_widget = getattr(self, f"eclipse_{prefix}_tol_minus_input")
        cpk_widget = getattr(self, f"eclipse_{prefix}_cpk_input")

        nominal = float(nominal_widget.text() or 0.0)
        tol_plus = float(tol_plus_widget.text() or 0.0)
        tol_minus = float(tol_minus_widget.text() or 0.0)
        cpk_text = cpk_widget.text().strip()
        cpk = float(cpk_text) if cpk_text else None

        names = {"handle": "Hole" if self._eclipse_is_pin_mode() else "Hole A",
                 "sticker": "Pin" if self._eclipse_is_pin_mode() else "Hole B",
                 "offset_x": "Position offset X", "offset_y": "Position offset Y"}
        return ToleranceInput(
            name=names[prefix], nominal=nominal, tol_plus=tol_plus, tol_minus=tol_minus, cpk=cpk
        )

    def _eclipse_read_all_inputs(self) -> EclipseInputs:
        return EclipseInputs(
            handle_diameter=self._eclipse_read_input("handle"),
            sticker_diameter=self._eclipse_read_input("sticker"),
            offset_x=self._eclipse_read_input("offset_x"),
            offset_y=self._eclipse_read_input("offset_y"),
        )

    # ------------------------------------------------------------------
    # Pull values from the Measure tab
    # ------------------------------------------------------------------

    def use_measured_a_for_handle(self):
        self._eclipse_fill_diameter_from_slot("A", "handle")

    def use_measured_b_for_sticker(self):
        self._eclipse_fill_diameter_from_slot("B", "sticker")

    def _eclipse_fill_diameter_from_slot(self, slot: str, prefix: str):
        info = self._measure_slot.get(slot) if hasattr(self, "_measure_slot") else None
        if info is None or info.get("circle") is None:
            QMessageBox.warning(
                self, "No circle measured",
                f"Point {slot} in the Measure tab isn't set, or wasn't recognized as a "
                "circular feature - pick a circular edge/face there first."
            )
            return
        try:
            diameter = convert_length(finite_number(info["circle"]["radius"], "Measured radius") * 2, "mm", self._eclipse_length_unit())
            if diameter <= 0:
                raise ValueError("Measured circle diameter must be positive.")
        except (ValueError, KeyError) as exc:
            QMessageBox.warning(self, "Invalid measured circle", str(exc))
            return
        self._eclipse_set_text(getattr(self, f"eclipse_{prefix}_nominal_input"), repr(diameter))

    def use_measured_offset(self):
        """Transfer an aligned CAD pair atomically, retaining a stable signed XY basis."""
        slots = getattr(self, "_measure_slot", {})
        try:
            first = (slots.get("A") or {}).get("circle")
            second = (slots.get("B") or {}).get("circle")
            if first is None or second is None:
                raise ValueError("Measure two circular features (A and B) in the Measure tab first.")
            reference = self.eclipse_reference_axis_combo.currentText()
            projection = projection_from_circles(first, second, reference_axis=reference)
            values = {"handle": projection.diameter_a, "sticker": projection.diameter_b,
                      "offset_x": projection.offset_x, "offset_y": projection.offset_y}
            converted = {prefix: convert_length(value, "mm", self._eclipse_length_unit())
                         for prefix, value in values.items()}
        except (ValueError, KeyError, TypeError) as exc:
            QMessageBox.warning(self, "Could not project measured circles", str(exc))
            return
        with self._eclipse_widget_update():
            for prefix, value in converted.items():
                self._eclipse_set_text(getattr(self, f"eclipse_{prefix}_nominal_input"), repr(value))
            self._eclipse_projection_frame = projection.to_dict()
        self._eclipse_show_projection()
        self._eclipse_clear_results()
        # Atomic signal blocking above needs one explicit dirty notification.
        if hasattr(self, "_project_note_change"):
            self._project_note_change()

    # ------------------------------------------------------------------
    # Run the analysis
    # ------------------------------------------------------------------

    def run_eclipse_analysis(self):
        # A failed new run must not leave a previous probability or histogram
        # looking like the result for the inputs currently on screen.
        self._eclipse_clear_results()
        try:
            inputs = self._eclipse_read_all_inputs()
            threshold_pct = finite_number(self.eclipse_threshold_input.text(), "Projected interference threshold (%)")
            if not 0 <= threshold_pct <= 100:
                raise ValueError("Projected interference threshold must be from 0 to 100%.")
            iterations = self._eclipse_read_iterations()
            seed_widget = getattr(self, "eclipse_seed_input", None)
            seed = parse_seed(seed_widget.text() if seed_widget is not None else "")
            rng = np.random.default_rng(seed)
            pin_mode = self._eclipse_is_pin_mode()
            if pin_mode:
                pin_inputs = PinHoleInputs(inputs.handle_diameter, inputs.sticker_diameter,
                                          inputs.offset_x, inputs.offset_y)
                pin_result = run_pin_hole_monte_carlo(pin_inputs, iterations=iterations, rng=rng)
                clearance_min, clearance_max = radial_clearance_bounds(pin_inputs)
                mc_result = pin_result.area
                probability = pin_result.probability_above(threshold_pct / 100.0)
            else:
                mc_result = run_monte_carlo(inputs, iterations=iterations, rng=rng)
                exact_min, exact_max = worst_case(inputs)
                probability = mc_result.probability_above(threshold_pct / 100.0)
        except ValueError as exc:
            for label in self.eclipse_result_labels.values():
                label.setText("Invalid input")
            QMessageBox.warning(self, "Invalid projected interference analysis", str(exc).replace("Eclipse", "Projected interference"))
            return

        labels = self.eclipse_result_labels
        labels["mean"].setText(f"{mc_result.mean * 100:.2f} %")
        labels["std"].setText(f"{mc_result.std_dev * 100:.2f} %")
        labels["mc_range"].setText(
            f"{mc_result.minimum * 100:.2f} % - {mc_result.maximum * 100:.2f} % (Monte Carlo, {iterations} samples)"
        )
        if pin_mode:
            clearance = pin_result.clearance
            units = self._eclipse_length_unit()
            labels["clearance_mean"].setText(f"{clearance.mean:+.6g} {units}")
            labels["clearance_std"].setText(f"{clearance.std_dev:.6g} {units}")
            labels["clearance_range"].setText(f"{clearance.minimum:+.6g} - {clearance.maximum:+.6g} {units} (Monte Carlo, {iterations} samples)")
            labels["clearance_bounds"].setText(f"{clearance_min:+.6g} - {clearance_max:+.6g} {units} (over full tolerance zone)")
            labels["interference"].setText(f"{pin_result.interference_probability * 100:.2f} % (radial clearance < 0; contact excluded)")
            labels["probability"].setText(f"{probability * 100:.2f} % chance of more than {threshold_pct:.1f} % of the pin area outside the hole")
            self._eclipse_clearance_samples = clearance.samples
        else:
            labels["worst_case"].setText(
                f"{exact_min * 100:.2f} % - {exact_max * 100:.2f} % (numerical, over full tolerance zone)"
            )
            labels["probability"].setText(
                f"{probability * 100:.2f} % chance of losing more than {threshold_pct:.1f} % of the aperture"
            )

        self._eclipse_plot_histogram(mc_result.samples)

    def _eclipse_clear_results(self, *_):
        self._eclipse_clearance_samples = None
        for label in self.eclipse_result_labels.values():
            label.setText("—")
        self.eclipse_figure.clear()
        self.eclipse_canvas.setVisible(False)
        self.eclipse_canvas.draw_idle()
        self._eclipse_update_preview()

    def _eclipse_plot_histogram(self, samples):
        self.eclipse_figure.clear()
        clearance = getattr(self, "_eclipse_clearance_samples", None)
        ax = self.eclipse_figure.add_subplot(211 if clearance is not None else 111)
        ax.hist(
            samples * 100, bins=40, color=COLORS["accent"],
            edgecolor=COLORS["panel"],
        )
        ax.set_xlabel("Pin area outside hole (%)" if self._eclipse_is_pin_mode() else "Aperture loss (%)")
        ax.set_ylabel("Samples")
        ax.set_title("Projected interference (Monte Carlo)")
        style_axes(ax)
        if clearance is not None:
            clearance_ax = self.eclipse_figure.add_subplot(212)
            clearance_ax.hist(clearance, bins=40, color=COLORS["accent"], edgecolor=COLORS["panel"])
            clearance_ax.axvline(0, color=COLORS["text"], linestyle="--")
            clearance_ax.set_xlabel(f"Radial clearance ({self._eclipse_length_unit()})")
            clearance_ax.set_ylabel("Samples")
            style_axes(clearance_ax)
        self.eclipse_figure.tight_layout()
        self.eclipse_canvas.setVisible(True)
        self.eclipse_canvas.draw()
