"""Presentation must retain report meaning as limits and input validity change."""

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from gui.analysis_mixin import AnalysisMixin
from gui.analysis_summary import AnalysisSummary
from gui.theme import apply_window_theme
from tolstack import Dimension, Stack
from tolstack.analysis import AnalysisSettings, analyze_stack


@pytest.fixture
def summary():
    application = QApplication.instance() or QApplication([])
    widget = AnalysisSummary()
    apply_window_theme(widget)
    yield widget
    widget.close()
    widget.deleteLater()
    application.processEvents()


def displayed_text(widget):
    """Read only the currently attached cards, excluding retired Qt objects."""
    parts = []
    for index in range(widget.layout().count()):
        child = widget.layout().itemAt(index).widget()
        if isinstance(child, QLabel):
            parts.append(child.text())
        else:
            parts.extend(label.text() for label in child.findChildren(QLabel))
    return "\n".join(parts)


def report(method="worst_case", **settings):
    return analyze_stack(
        Stack([Dimension("Outer case", 1, 0.1, 0.1, cpk=1.33)]),
        AnalysisSettings(method=method, response_name="Functional gap", **settings),
    )


def test_stale_message_removes_result_cards_and_preserves_plain_text(summary):
    original = report(lower_limit=0.8, upper_limit=1.2)
    summary.set_report(original, "Exact legacy summary")
    assert summary.text() == "Exact legacy summary"
    assert "Functional gap" in displayed_text(summary)
    assert "Separate zero-clearance fit check" in displayed_text(summary)

    summary.setText("Inputs changed — run analysis to refresh results.")
    assert summary._report is None
    assert displayed_text(summary) == summary.text()
    assert "Functional acceptance" not in displayed_text(summary)
    assert "1.0000" not in displayed_text(summary)


def test_rss_unbounded_limits_and_sampling_assumptions_stay_explicit(summary):
    # The arbitrary plain text deliberately contains no display data to parse.
    summary.set_report(report("rss", upper_limit=1.2), "Legacy copy text")
    text = displayed_text(summary)
    assert "unbounded" in text
    assert "RSS does not predict a calibrated yield." in text
    assert "Sensitivity +1 · Cpk assumption 1.33" in text
    assert "Sample yield" not in text
    assert summary.text() == "Legacy copy text"


class SummaryHarness(AnalysisMixin):
    def __init__(self, widget, analysis_report, lower, upper):
        self.result_label = widget
        self._last_analysis_report = analysis_report
        self._last_samples = analysis_report.result.samples
        self._last_monte_carlo_payload = {"report": analysis_report}
        self.range_min_input = SimpleNamespace(value=lambda: lower)
        self.range_max_input = SimpleNamespace(value=lambda: upper)
        self._histogram_ax = None
        self.visible = True
        self.canvas = SimpleNamespace(setVisible=lambda value: setattr(self, "visible", value))
        self.figure = SimpleNamespace(canvas=SimpleNamespace(draw_idle=lambda: None))


def test_limit_edits_update_monte_carlo_cards_without_resampling(summary):
    original = report("monte_carlo", lower_limit=0.5, upper_limit=1.5, iterations=100, seed=7)
    harness = SummaryHarness(summary, original, 0.99, 1.01)
    harness._refresh_interval_summary(harness._last_samples)
    revised = harness._last_analysis_report
    assert revised.result is original.result
    assert revised.acceptance.rejected_count > original.acceptance.rejected_count
    assert summary._report is revised
    text = displayed_text(summary)
    assert "0.9900" in text and "1.0100" in text
    assert f"{revised.acceptance.rejected_count:,}" in text
    assert f"{100 * (1 - revised.acceptance.rejection_probability):.2f}%" in text
    assert "Finite sample estimate; zero rejects does not establish six sigma." in text
    assert "Separate zero-clearance fit check" in text
    assert f"{original.fit_at_zero.margin_min:+.4f}" in text
    assert "100 samples; seed: 7" in summary.text()

    # Invalid bounds clear both the evaluated report and the visible cards.
    harness.range_min_input = SimpleNamespace(value=lambda: 2)
    harness.range_max_input = SimpleNamespace(value=lambda: 1)
    harness._sync_interval_from_inputs()
    assert harness._last_analysis_report is None
    assert summary._report is None
    assert not harness.visible
    assert "invalid" in displayed_text(summary)
    assert "Sample yield" not in displayed_text(summary)


def test_long_details_wrap_within_narrow_results_pane(summary):
    long_report = analyze_stack(
        Stack([Dimension("An extended source feature name with several measured references", 1, 0.1, 0.1)]),
        AnalysisSettings(response_name="A longer functional response name that needs multiple lines"),
    )
    summary.set_report(long_report, "Copy text")
    summary.resize(340, summary.heightForWidth(340))
    summary.show()
    QApplication.processEvents()
    assert summary.minimumSizeHint().width() <= 340
    for label in summary.findChildren(QLabel):
        if label.isVisible():
            assert label.hasHeightForWidth()
            assert label.height() >= label.heightForWidth(label.width())
