"""Presentation must retain report meaning as limits and input validity change."""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

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


@pytest.mark.parametrize("unit", ["mm", "in"])
def test_length_cards_preserve_snapshot_units_and_full_precision(summary, unit):
    evaluated = analyze_stack(
        Stack([Dimension("Small gap", 0.000004123456789, 0.0000001, 0.0000002)]),
        AnalysisSettings(lower_limit=0, upper_limit=0.00001),
        report_context={"units": {"length": unit, "angle": "deg"}},
    )
    exported_before = evaluated.to_dict()
    summary.set_report(evaluated, "Unchanged legacy text")
    assert f"Length units: {unit}" in displayed_text(summary)
    assert f"4.12346e-06 {unit}" in displayed_text(summary)
    label = next(label for label in summary.findChildren(QLabel)
                 if label.text() == f"4.12346e-06 {unit}")
    assert label.toolTip() == f"Full precision: 4.123456789e-06 {unit}"
    details = summary.findChild(QLabel, "fullPrecisionValues")
    assert details.isHidden()
    toggle = next(button for button in summary.findChildren(QPushButton)
                  if button.text() == "Full precision values")
    toggle.setChecked(True)
    assert not details.isHidden()
    assert f"Nominal: 4.123456789e-06 {unit}" in details.text()
    assert details.textInteractionFlags() & Qt.TextSelectableByKeyboard
    assert summary.text() == "Unchanged legacy text"
    assert evaluated.to_dict() == exported_before


def test_unspecified_units_remain_explicit_and_counts_are_unitless(summary):
    evaluated = report("monte_carlo", iterations=100, seed=7, lower_limit=0, upper_limit=2)
    summary.set_report(evaluated, "Legacy text")
    assert "Length units: unspecified" in displayed_text(summary)
    captions = {label.text(): label for label in summary.findChildren(QLabel)}
    assert "100 / 100" in captions
    assert "100.00%" in captions
    assert "0.0" in captions  # observed PPM
    assert "mm" not in summary.findChild(QLabel, "fullPrecisionValues").text()
