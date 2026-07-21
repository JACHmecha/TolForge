"""Mixin providing tolerance stack analysis (worst-case/RSS/Monte Carlo) and
the interactive histogram (draggable interval lines) for TolstackWindow.
"""

from PySide6.QtWidgets import QMessageBox

from tolstack import Stack, Dimension


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
        stack = Stack()
        for r in range(self.table.rowCount()):
            try:
                name = self.table.item(r, 0).text().strip()
                nominal = float(self.table.item(r, 1).text())
                tol_plus = float(self.table.item(r, 2).text())
                tol_minus = float(self.table.item(r, 3).text())
                sign = self._get_sign_from_row(r)
            except (AttributeError, ValueError):
                raise ValueError(f"Row {r + 1} has invalid or incomplete data.")

            if sign not in {"+", "-"}:
                raise ValueError(f"Row {r + 1}: sign must be '+' or '-', not {sign}.")

            # Cpk column is optional: empty or missing cell -> None (uniform)
            cpk_item = self.table.item(r, 5)
            cpk_text = cpk_item.text().strip() if cpk_item else ""
            if cpk_text == "":
                cpk = None
            else:
                try:
                    cpk = float(cpk_text)
                except ValueError:
                    raise ValueError(f"Row {r + 1}: Cpk '{cpk_text}' is not a valid number.")
                if cpk <= 0:
                    raise ValueError(f"Row {r + 1}: Cpk must be greater than 0, not {cpk}.")

            stack.add_dimension(Dimension(
                name=name, nominal=nominal,
                tol_plus=tol_plus, tol_minus=tol_minus, sign=sign, cpk=cpk
            ))
        return stack

    def _get_default_cpk(self) -> float | None:
        """Reads the global Cpk field. Empty -> None (no default, falls back to uniform)."""
        text = self.default_cpk_input.text().strip()
        if text == "":
            return None
        try:
            value = float(text)
        except ValueError:
            raise ValueError(f"Global Cpk '{text}' is not a valid number.")
        if value <= 0:
            raise ValueError(f"Global Cpk must be greater than 0, not {value}.")
        return value

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
            return

        self.interval_min_value = lower
        self.interval_max_value = upper
        self._update_interval_lines()
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

        inside_count, outside_count, inside_percentage, outside_percentage = self._get_interval_stats(samples, lower, upper)
        model_lines = self._last_monte_carlo_payload["model_lines"]
        result = self._last_monte_carlo_payload["result"]
        fit = self._last_monte_carlo_payload["fit"]

        self.result_label.setText(
            f"Monte Carlo ({len(samples):,} iterations)\n"
            + "\n".join(model_lines) + "\n"
            f"{'-' * 30}\n"
            f"Mean       : {result.mean:.4f}\n"
            f"Std Dev    : {result.std_dev:.4f}\n"
            f"Range      : [{lower:.4f}, {upper:.4f}]\n"
            f"In range   : {inside_count:,}/{len(samples):,} ({inside_percentage:.2f}%)\n"
            f"Out of range: {outside_count:,}/{len(samples):,} ({outside_percentage:.2f}%)\n"
            + self._fit_text(fit)
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
        try:
            stack = self._build_stack()
            lower, upper = self._get_range_bounds()
        except ValueError as e:
            QMessageBox.warning(self, "Invalid data", str(e))
            return

        if not stack.dimensions:
            QMessageBox.warning(self, "No data", "Add at least one dimension.")
            return

        method = self.method_combo.currentText()

        if method == "worst_case":
            result = stack.worst_case()
            fit = stack.assess_fit(result, target=0.0)
            self._show_stack_result(result, fit)
            self.canvas.setVisible(False)

        elif method == "rss":
            result = stack.rss()
            fit = stack.assess_fit(result, target=0.0)
            self._show_stack_result(result, fit)
            self.canvas.setVisible(False)

        elif method == "monte_carlo":
            try:
                default_cpk = self._get_default_cpk()
            except ValueError as e:
                QMessageBox.warning(self, "Invalid global Cpk", str(e))
                return

            iterations = self._get_iterations()
            result = stack.monte_carlo(iterations=iterations, default_cpk=default_cpk)
            fit = stack.assess_fit(result, target=0.0)

            model_lines = []
            for d in stack.dimensions:
                cpk = d.cpk if d.cpk is not None else default_cpk
                model = f"Cpk={cpk}" if cpk is not None else "uniform"
                model_lines.append(f"  {d.name}: {model}")

            self._last_samples = result.samples
            self._last_monte_carlo_payload = {"model_lines": model_lines, "result": result, "fit": fit}
            self._plot_histogram(result.samples)
            self._refresh_interval_summary(result.samples)
            self.canvas.setVisible(True)

    def _fit_text(self, fit) -> str:
        lines = [
            f"{'-' * 30}",
            f"Verdict      : {fit.verdict.upper()}",
            f"Margin (min) : {fit.margin_min:+.4f}",
            f"Margin (max) : {fit.margin_max:+.4f}",
        ]
        if fit.interference_probability is not None:
            lines.append(f"P(interference): {fit.interference_probability * 100:.2f}%")
        return "\n".join(lines)

    def _show_stack_result(self, result, fit):
        self.result_label.setText(
            f"{'-' * 30}\n"
            f"Nominal : {result.nominal:.4f}\n"
            f"Maximum : {result.upper_limit:.4f}\n"
            f"Minimum : {result.lower_limit:.4f}\n"
            f"+Tol    : {result.upper_limit - result.nominal:.4f}\n"
            f"-Tol    : {result.nominal - result.lower_limit:.4f}\n"
            + self._fit_text(fit)
        )

    def _plot_histogram(self, samples):
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.hist(samples, bins=50)
        ax.set_title("Monte Carlo distribution")
        ax.set_xlabel("Value")
        ax.set_ylabel("Frequency")
        self._histogram_ax = ax
        self._interval_lines = [
            ax.axvline(self.interval_min_value, color="#1f77b4", linestyle="--", linewidth=1.8),
            ax.axvline(self.interval_max_value, color="#ff7f0e", linestyle="--", linewidth=1.8),
        ]
        self.figure.tight_layout()
        self.canvas.draw()
