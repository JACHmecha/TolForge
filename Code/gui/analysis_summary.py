"""Structured presentation of an existing scalar analysis report.

The plain summary remains available to callers through the QLabel-compatible
``setText``/``text`` interface. Presentation reads typed report fields; it does
not infer outcomes or numbers from that summary.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QSizePolicy, QVBoxLayout

from tolstack.analysis import AnalysisReport


class AnalysisSummary(QFrame):
    """Wrappable result cards that also support neutral and stale messages."""

    def __init__(self, text="No results yet.", parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self._plain_text = ""
        self._report = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(12)
        self._layout.setAlignment(Qt.AlignTop)
        self.setText(text)

    def text(self):
        """Return the unchanged legacy summary for copy/export consumers."""
        return self._plain_text

    def setText(self, text):
        """Replace every result card with a neutral, stale, or error message."""
        self._plain_text = text
        self._report = None
        self._clear()
        self._layout.addWidget(self._label(text, role="muted"))

    def set_report(self, report: AnalysisReport, plain_text: str):
        self._plain_text = plain_text
        self._report = report
        self._clear()
        self._layout.addWidget(self._label(report.settings.response_name, role="heading"))
        method = report.settings.method
        if method == "monte_carlo":
            seed = report.settings.seed
            description = (
                f"Monte Carlo · {len(report.result.samples):,} samples · "
                f"seed: {seed if seed is not None else 'random'}"
            )
        else:
            description = "RSS estimated band" if method == "rss" else "Worst-case analysis"
        self._layout.addWidget(self._label(description, role="muted"))
        self._show_acceptance(report)
        self._show_metrics(report)
        self._show_fit(report.fit_at_zero)
        self._show_contributors(report.contributions)

    def _clear(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # Hide immediately, including when event processing is deferred.
                widget.hide()
                widget.deleteLater()

    def _label(self, text, role=None, alignment=Qt.AlignLeft | Qt.AlignTop):
        label = QLabel(text, self)
        label.setTextFormat(Qt.PlainText)
        label.setAlignment(alignment)
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        if role is not None:
            label.setProperty("role", role)
        return label

    def _card(self, title):
        card = QFrame(self)
        card.setProperty("surface", "card")
        card.setMinimumWidth(0)
        grid = QGridLayout(card)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.addWidget(self._label(title, role="sectionHeading"), 0, 0, 1, 2)
        self._layout.addWidget(card)
        return grid

    def _row(self, grid, caption, value, *, role=None):
        row = grid.rowCount()
        grid.addWidget(self._label(caption, role="muted"), row, 0)
        grid.addWidget(self._label(value, role=role, alignment=Qt.AlignRight | Qt.AlignTop), row, 1)

    def _note(self, grid, text, *, role="muted"):
        grid.addWidget(self._label(text, role=role), grid.rowCount(), 0, 1, 2)

    def _show_acceptance(self, report):
        grid = self._card("Functional acceptance")
        acceptance = report.acceptance
        lower = f"{acceptance.lower_limit:.4f}" if acceptance.lower_limit is not None else "unbounded"
        upper = f"{acceptance.upper_limit:.4f}" if acceptance.upper_limit is not None else "unbounded"
        self._note(grid, acceptance.status.replace("_", " ").capitalize(), role="metric")
        self._row(grid, "Lower limit", lower)
        self._row(grid, "Upper limit", upper)
        if acceptance.rejected_count is not None:
            accepted = acceptance.sample_count - acceptance.rejected_count
            self._row(grid, "Sample yield", f"{100 * (1 - acceptance.rejection_probability):.2f}%", role="metric")
            self._row(grid, "Accepted samples", f"{accepted:,} / {acceptance.sample_count:,}")
            self._row(grid, "Rejects", f"{acceptance.rejected_count:,}")
            self._row(grid, "Observed PPM", f"{acceptance.rejection_ppm:.1f}")
            self._note(grid, "Finite sample estimate; zero rejects does not establish six sigma.")
        elif report.settings.method == "rss":
            self._note(grid, "RSS does not predict a calibrated yield.")

    def _show_metrics(self, report):
        result = report.result
        if report.settings.method == "monte_carlo":
            grid = self._card("Sample distribution")
            self._row(grid, "Mean", f"{result.mean:.4f}")
            self._row(grid, "Standard deviation", f"{result.std_dev:.4f}")
        else:
            grid = self._card("Response range")
            self._row(grid, "Nominal", f"{result.nominal:.4f}", role="metric")
            self._row(grid, "Minimum", f"{result.lower_limit:.4f}")
            self._row(grid, "Maximum", f"{result.upper_limit:.4f}")
            self._row(grid, "+Tolerance", f"{result.upper_limit - result.nominal:.4f}")
            self._row(grid, "−Tolerance", f"{result.nominal - result.lower_limit:.4f}")

    def _show_fit(self, fit):
        grid = self._card("Separate zero-clearance fit check")
        self._row(grid, "Fit", fit.verdict.upper())
        self._row(grid, "Minimum margin", f"{fit.margin_min:+.4f}")
        self._row(grid, "Maximum margin", f"{fit.margin_max:+.4f}")
        if fit.interference_probability is not None:
            self._row(grid, "P(interference)", f"{fit.interference_probability * 100:.2f}%")

    def _show_contributors(self, contributions):
        grid = self._card("Variance contributors")
        self._note(grid, "Independent scalar model")
        if not any(item.response_variance for item in contributions):
            self._note(grid, "No modeled variation.")
        for item in contributions:
            self._row(grid, item.name, f"{item.variance_fraction * 100:.1f}%", role="muted")
            model = "uniform" if item.cpk is None else f"Cpk assumption {item.cpk:g}"
            self._note(grid, f"Sensitivity {item.sensitivity:+d} · {model}")
