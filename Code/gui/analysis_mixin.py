"""Mixin providing tolerance stack analysis (worst-case/RSS/Monte Carlo) and
the interactive histogram (draggable interval lines) for TolstackWindow.
"""

from PySide6.QtWidgets import QMessageBox

from tolstack import Stack
from tolstack.analysis import (
    AnalysisSettings, analyze_stack, build_stack, parse_optional_cpk,
    parse_seed, update_report_limits,
)
from gui.theme import COLORS, style_axes


class AnalysisMixin:
    """Expects the host class (TolstackWindow) to provide, from its own
    __init__: self.table, self.method_combo, self.default_cpk_input,
    self.iterations_input, self.range_min_input, self.range_max_input,
    self.result_label, self.figure, self.canvas, self.interval_min_value,
    self.interval_max_value, self._histogram_ax, self._interval_lines,
    self._dragged_line, self._dragged_line_index, self._last_samples,
    self._last_monte_carlo_payload.
    """

    # ------------------------------------------------------------------
    # Stack construction from the table
    # ------------------------------------------------------------------

    def _build_stack(self) -> Stack:
        rows = []
        for r in range(self.table.rowCount()):
            def text(column):
                item = self.table.item(r, column)
                return item.text().strip() if item else ""
            rows.append({
                "name": text(0), "nominal": text(1), "tol_plus": text(2),
                "tol_minus": text(3), "sign": self._get_sign_from_row(r), "cpk": text(5),
            })
        return build_stack(rows)

    def _get_default_cpk(self) -> float | None:
        """Reads the global Cpk field. Empty -> None (no default, falls back to uniform)."""
        return parse_optional_cpk(self.default_cpk_input.text(), "Global Cpk")

    def _get_iterations(self) -> int:
        return int(self.iterations_input.value())

    def _get_range_bounds(self) -> tuple[float, float]:
        lower = float(self.range_min_input.value())
        upper = float(self.range_max_input.value())
        if lower > upper:
            raise ValueError("Range minimum cannot be greater than range maximum.")
        return lower, upper

    def _sync_interval_from_inputs(self):
        try:
            lower, upper = self._get_range_bounds()
        except ValueError:
            self._last_analysis_report = None
            self._last_samples = None
            self._last_monte_carlo_payload = None
            self.canvas.setVisible(False)
            self.result_label.setText("Functional limits are invalid. Correct the limits and run analysis again.")
            return

        self.interval_min_value = lower
        self.interval_max_value = upper
        self._update_interval_lines()
        report = getattr(self, "_last_analysis_report", None)
        if report is not None and report.settings.method != "monte_carlo":
            self._last_analysis_report = update_report_limits(report, lower, upper)
            self._show_stack_result(report.result, report.fit_at_zero)
        else:
            self._refresh_interval_summary(self._last_samples)
        self.figure.canvas.draw_idle()

    def _update_interval_lines(self):
        if self._histogram_ax is None:
            return
        if not self._interval_lines:
            return
        self._interval_lines[0].set_xdata([self.interval_min_value, self.interval_min_value])
        self._interval_lines[1].set_xdata([self.interval_max_value, self.interval_max_value])
        self._histogram_ax.figure.canvas.draw_idle()

    def _refresh_interval_summary(self, samples):
        if samples is None or self._last_monte_carlo_payload is None:
            return

        try:
            lower, upper = self._get_range_bounds()
        except ValueError:
            return

        report = update_report_limits(self._last_monte_carlo_payload["report"], lower, upper)
        self._last_monte_carlo_payload["report"] = report
        self._last_analysis_report = report
        result = report.result
        seed = report.settings.seed

        self.result_label.setText(
            f"{report.settings.response_name}\n"
            f"Monte Carlo ({len(samples):,} samples; seed: {seed if seed is not None else 'random'})\n"
            f"{'-' * 30}\n"
            f"Mean       : {result.mean:.4f}\n"
            f"Std Dev    : {result.std_dev:.4f}\n"
            + self._acceptance_text(report) + "\n"
            + self._contribution_text(report) + "\n"
            + self._fit_text(report.fit_at_zero)
        )

    def _get_interval_stats(self, samples, lower: float, upper: float):
        inside_mask = (samples >= lower) & (samples <= upper)
        inside_count = int(sum(inside_mask))
        total = int(len(samples))
        outside_count = total - inside_count
        inside_percentage = (inside_count / total * 100.0) if total else 0.0
        outside_percentage = (outside_count / total * 100.0) if total else 0.0
        return inside_count, outside_count, inside_percentage, outside_percentage

    def _on_histogram_click(self, event):
        if event.inaxes is None or event.inaxes is not self._histogram_ax or event.button != 1:
            return

        for index, line in enumerate(self._interval_lines):
            x_value = line.get_xdata()[0]
            if x_value is None:
                continue
            if abs(event.xdata - x_value) <= 0.03 * max(abs(self._histogram_ax.get_xlim()[1] - self._histogram_ax.get_xlim()[0]), 1.0):
                self._dragged_line = line
                self._dragged_line_index = index
                return

    def _on_histogram_move(self, event):
        if self._dragged_line is None or event.inaxes is not self._histogram_ax or event.xdata is None:
            return

        if self._dragged_line_index == 0:
            self.interval_min_value = float(event.xdata)
            if self.interval_min_value > self.interval_max_value:
                self.interval_max_value = self.interval_min_value
        else:
            self.interval_max_value = float(event.xdata)
            if self.interval_max_value < self.interval_min_value:
                self.interval_min_value = self.interval_max_value

        self._sync_interval_inputs_from_values()
        self._update_interval_lines()
        self._refresh_interval_summary(self._last_samples)
        self.figure.canvas.draw_idle()

    def _on_histogram_release(self, event):
        self._dragged_line = None
        self._dragged_line_index = None

    def _sync_interval_inputs_from_values(self):
        self.range_min_input.blockSignals(True)
        self.range_max_input.blockSignals(True)
        self.range_min_input.setValue(self.interval_min_value)
        self.range_max_input.setValue(self.interval_max_value)
        self.range_min_input.blockSignals(False)
        self.range_max_input.blockSignals(False)

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def run_analysis(self):
        self._last_analysis_report = None
        self._last_samples = None
        self._last_monte_carlo_payload = None
        try:
            stack = self._build_stack()
            lower, upper = self._get_range_bounds()
            seed_widget = getattr(self, "seed_input", None)
            response_widget = getattr(self, "response_name_input", None)
            settings = AnalysisSettings(
                method=self.method_combo.currentText(), lower_limit=lower, upper_limit=upper,
                iterations=self._get_iterations(), default_cpk=self._get_default_cpk(),
                seed=parse_seed(seed_widget.text()) if seed_widget is not None else None,
                response_name=response_widget.text() if response_widget is not None else "Functional response",
            )
            report = analyze_stack(stack, settings)
        except ValueError as e:
            self.canvas.setVisible(False)
            self.result_label.setText("Analysis needs valid inputs. Correct the reported issue and run again.")
            QMessageBox.warning(self, "Invalid data", str(e))
            return

        self._last_analysis_report = report
        if settings.method != "monte_carlo":
            self._show_stack_result(report.result, report.fit_at_zero)
            self.canvas.setVisible(False)
        else:
            self._last_samples = report.result.samples
            self._last_monte_carlo_payload = {"report": report, "result": report.result, "fit": report.fit_at_zero}
            self._plot_histogram(report.result.samples)
            self._refresh_interval_summary(report.result.samples)
            self.canvas.setVisible(True)

    def _acceptance_text(self, report) -> str:
        acceptance = report.acceptance
        lower = f"{acceptance.lower_limit:.4f}" if acceptance.lower_limit is not None else "unbounded"
        upper = f"{acceptance.upper_limit:.4f}" if acceptance.upper_limit is not None else "unbounded"
        lines = [f"Functional limits: [{lower}, {upper}]"]
        if acceptance.rejected_count is not None:
            accepted = acceptance.sample_count - acceptance.rejected_count
            lines += [
                f"Sample yield: {100 * (1 - acceptance.rejection_probability):.2f}% ({accepted:,}/{acceptance.sample_count:,})",
                f"Rejects: {acceptance.rejected_count:,} ({acceptance.rejection_ppm:.1f} observed PPM)",
                "Finite sample estimate; zero rejects does not establish six sigma.",
            ]
        else:
            basis = "RSS estimated band" if report.settings.method == "rss" else "Worst-case band"
            lines.append(f"{basis}: {acceptance.status.replace('_', ' ')}")
            if report.settings.method == "rss":
                lines.append("RSS does not predict a calibrated yield.")
        return "\n".join(lines)

    def _contribution_text(self, report) -> str:
        lines = [f"{'-' * 30}", "Variance contributors (independent scalar model):"]
        if not any(item.response_variance for item in report.contributions):
            lines.append("  No modeled variation.")
        for item in report.contributions:
            model = "uniform" if item.cpk is None else f"Cpk assumption {item.cpk:g}"
            lines.append(f"  {item.name}: {item.variance_fraction * 100:.1f}% (sensitivity {item.sensitivity:+d}; {model})")
        return "\n".join(lines)

    def _fit_text(self, fit) -> str:
        lines = [
            f"{'-' * 30}",
            "Separate zero-clearance fit check:",
            f"Fit          : {fit.verdict.upper()}",
            f"Margin (min) : {fit.margin_min:+.4f}",
            f"Margin (max) : {fit.margin_max:+.4f}",
        ]
        if fit.interference_probability is not None:
            lines.append(f"P(interference): {fit.interference_probability * 100:.2f}%")
        return "\n".join(lines)

    def _show_stack_result(self, result, fit):
        report = getattr(self, "_last_analysis_report", None)
        self.result_label.setText(
            (f"{report.settings.response_name}\n" if report is not None else "")
            + f"{'-' * 30}\n"
            f"Nominal : {result.nominal:.4f}\n"
            f"Maximum : {result.upper_limit:.4f}\n"
            f"Minimum : {result.lower_limit:.4f}\n"
            f"+Tol    : {result.upper_limit - result.nominal:.4f}\n"
            f"-Tol    : {result.nominal - result.lower_limit:.4f}\n"
            + (self._acceptance_text(report) + "\n" + self._contribution_text(report) + "\n" if report is not None else "")
            + self._fit_text(fit)
        )

    def _plot_histogram(self, samples):
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.hist(samples, bins=50, color=COLORS["accent"], edgecolor=COLORS["panel"])
        ax.set_title("Monte Carlo distribution")
        ax.set_xlabel("Value")
        ax.set_ylabel("Frequency")
        self._histogram_ax = ax
        self._interval_lines = [
            ax.axvline(self.interval_min_value, color=COLORS["accent"], linestyle="--", linewidth=1.8),
            ax.axvline(self.interval_max_value, color=COLORS["selection"], linestyle="--", linewidth=1.8),
        ]
        style_axes(ax)
        self.figure.tight_layout()
        self.canvas.draw()
