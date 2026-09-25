"""Regressions for visible analysis state after editing functional limits."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

from gui.analysis_mixin import AnalysisMixin
from tolstack import Dimension, Stack
from tolstack.analysis import AnalysisSettings, analyze_stack


class AnalysisHarness(AnalysisMixin):
    def __init__(self, lower, upper):
        self.range_min_input = SimpleNamespace(value=lambda: lower)
        self.range_max_input = SimpleNamespace(value=lambda: upper)
        self._last_analysis_report = analyze_stack(
            Stack([Dimension("A", 1, 0.1, 0.1)]),
            AnalysisSettings(lower_limit=0.8, upper_limit=1.2),
        )
        self._last_samples = [1]
        self._last_monte_carlo_payload = {"report": self._last_analysis_report}
        self.canvas = SimpleNamespace(setVisible=self._set_visible)
        self.result_label = SimpleNamespace(setText=self._set_text)
        self.figure = SimpleNamespace(canvas=SimpleNamespace(draw_idle=lambda: None))
        self._histogram_ax = None
        self.visible = True
        self.text = "old result"

    def _set_visible(self, value):
        self.visible = value

    def _set_text(self, value):
        self.text = value


def test_invalid_limit_edit_clears_report_and_visible_old_result():
    harness = AnalysisHarness(lower=2, upper=1)
    harness._sync_interval_from_inputs()
    assert harness._last_analysis_report is None
    assert harness._last_samples is None
    assert harness._last_monte_carlo_payload is None
    assert not harness.visible
    assert "invalid" in harness.text


def test_valid_limit_edit_reassesses_same_result_without_sampling():
    harness = AnalysisHarness(lower=0.95, upper=1.05)
    old_result = harness._last_analysis_report.result
    harness._sync_interval_from_inputs()
    assert harness._last_analysis_report.result is old_result
    assert harness._last_analysis_report.acceptance.status == "overlaps_limits"
    assert "0.9500" in harness.text
