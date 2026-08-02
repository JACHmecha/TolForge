"""Mixin for the 'Eclipse' tab: LED-hole vs. sticker-hole occlusion
analysis.

Wires the Eclipse tab's widgets (built in app.py) to the pure-math
functions in tolstack.eclipse. Also lets the user pull nominal diameter
and center-offset values directly from whatever circles are currently
fit in the Measure tab, instead of retyping numbers that were already
just measured from the STEP geometry.
"""

from PySide6.QtWidgets import QMessageBox

from tolstack.eclipse import ToleranceInput, EclipseInputs, run_monte_carlo, worst_case


class EclipseMixin:
    """Expects the host class (TolstackWindow) to provide, from its own
    __init__: self.bank (unused here directly, but MeasurementMixin's
    slots are read from self._measure_slot), plus the Eclipse-tab widgets
    built in app.py: for each of "handle", "sticker", "offset_x",
    "offset_y" - self.eclipse_<name>_nominal_input, _tol_plus_input,
    _tol_minus_input, _cpk_input (all QLineEdit); self.eclipse_iterations_input
    (QSpinBox); self.eclipse_threshold_input (QLineEdit); self.eclipse_result_labels
    (dict with keys "mean", "std", "mc_range", "worst_case", "probability");
    self.eclipse_figure / self.eclipse_canvas (matplotlib).
    """

    # ------------------------------------------------------------------
    # Reading inputs
    # ------------------------------------------------------------------

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

        return ToleranceInput(
            name=prefix, nominal=nominal, tol_plus=tol_plus, tol_minus=tol_minus, cpk=cpk
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
                "circular feature - pick a hole edge/face there first."
            )
            return
        diameter = info["circle"]["radius"] * 2
        getattr(self, f"eclipse_{prefix}_nominal_input").setText(f"{diameter:.4f}")

    def use_measured_offset(self):
        """Pulls the circle-center distance from the Measure tab (A vs B)
        into offset X, leaving offset Y at 0 - eclipse_fraction only
        depends on the combined radial magnitude sqrt(dx^2+dy^2), so a
        single measured radial offset is equivalent to putting the whole
        thing on one axis."""
        last = getattr(self, "_measure_last", None)
        if last is None or last.get("circle_center_distance") is None:
            QMessageBox.warning(
                self, "No circle-center measurement",
                "Measure two circular features (A and B) in the Measure tab first."
            )
            return
        self.eclipse_offset_x_nominal_input.setText(f"{last['circle_center_distance']:.4f}")
        self.eclipse_offset_y_nominal_input.setText("0.0")

    # ------------------------------------------------------------------
    # Run the analysis
    # ------------------------------------------------------------------

    def run_eclipse_analysis(self):
        try:
            inputs = self._eclipse_read_all_inputs()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid input", str(exc))
            return

        iterations = self.eclipse_iterations_input.value()
        try:
            mc_result = run_monte_carlo(inputs, iterations=iterations)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Cpk", str(exc))
            return

        exact_min, exact_max = worst_case(inputs)

        labels = self.eclipse_result_labels
        labels["mean"].setText(f"{mc_result.mean * 100:.2f} %")
        labels["std"].setText(f"{mc_result.std_dev * 100:.2f} %")
        labels["mc_range"].setText(
            f"{mc_result.minimum * 100:.2f} % - {mc_result.maximum * 100:.2f} % (Monte Carlo, {iterations} samples)"
        )
        labels["worst_case"].setText(
            f"{exact_min * 100:.2f} % - {exact_max * 100:.2f} % (exact, over full tolerance zone)"
        )

        try:
            threshold_pct = float(self.eclipse_threshold_input.text() or 0.0)
        except ValueError:
            threshold_pct = 0.0
        probability = mc_result.probability_above(threshold_pct / 100.0)
        labels["probability"].setText(
            f"{probability * 100:.2f} % chance of losing more than {threshold_pct:.1f} % of the aperture"
        )

        self._eclipse_plot_histogram(mc_result.samples)

    def _eclipse_plot_histogram(self, samples):
        self.eclipse_figure.clear()
        ax = self.eclipse_figure.add_subplot(111)
        ax.hist(samples * 100, bins=40, color="#4c78a8", edgecolor="white")
        ax.set_xlabel("Eclipse fraction (%)")
        ax.set_ylabel("Samples")
        ax.set_title("Eclipse fraction distribution (Monte Carlo)")
        self.eclipse_figure.tight_layout()
        self.eclipse_canvas.setVisible(True)
        self.eclipse_canvas.draw()
