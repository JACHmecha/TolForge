"""Invalid Eclipse runs clear visible previous results before returning."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

from gui import eclipse_mixin


class TextWidget:
    def __init__(self, text):
        self.value = text

    def text(self):
        return self.value

    def setText(self, text):
        self.value = text


class EclipseHarness(eclipse_mixin.EclipseMixin):
    def __init__(self):
        for prefix, nominal in (("handle", "4"), ("sticker", "3"), ("offset_x", "0.7"), ("offset_y", "0")):
            for field, value in (("nominal", nominal), ("tol_plus", "0.1"), ("tol_minus", "0.1"), ("cpk", "")):
                setattr(self, f"eclipse_{prefix}_{field}_input", TextWidget(value))
        self.eclipse_threshold_input = TextWidget("20")
        self.eclipse_iterations_input = SimpleNamespace(value=lambda: 10)
        self.eclipse_result_labels = {name: TextWidget("old result") for name in ("mean", "std", "mc_range", "worst_case", "probability")}
        self.visible = True
        self.cleared = False
        self.plotted_samples = None
        self.eclipse_figure = SimpleNamespace(clear=self._clear)
        self.eclipse_canvas = SimpleNamespace(setVisible=self._set_visible, draw_idle=lambda: None)

    def _clear(self):
        self.cleared = True

    def _set_visible(self, visible):
        self.visible = visible

    def _eclipse_plot_histogram(self, samples):
        self.plotted_samples = samples
        self.visible = True


@pytest.mark.parametrize("threshold", ["nonsense", "nan", "inf", "-1", "101", ""])
def test_invalid_threshold_rejected_before_sampling_and_clears_results(monkeypatch, threshold):
    messages = []
    monkeypatch.setattr(eclipse_mixin.QMessageBox, "warning", lambda *args: messages.append(args))
    monkeypatch.setattr(eclipse_mixin, "run_monte_carlo", lambda *args, **kwargs: pytest.fail("Invalid threshold must be rejected before sampling"))
    harness = EclipseHarness()
    harness.eclipse_threshold_input.setText(threshold)
    harness.run_eclipse_analysis()
    assert harness.cleared and not harness.visible
    assert harness.plotted_samples is None
    assert all(label.text() == "Invalid input" for label in harness.eclipse_result_labels.values())
    assert len(messages) == 1
    assert "threshold" in messages[0][2]


@pytest.mark.parametrize("field,value", [("handle_cpk", "nan"), ("handle_tol_minus", "-1"), ("handle_nominal", "0"), ("offset_y_nominal", "inf")])
def test_invalid_numeric_input_clears_all_previous_results(monkeypatch, field, value):
    messages = []
    monkeypatch.setattr(eclipse_mixin.QMessageBox, "warning", lambda *args: messages.append(args))
    harness = EclipseHarness()
    getattr(harness, f"eclipse_{field}_input").setText(value)
    harness.run_eclipse_analysis()
    assert harness.cleared and not harness.visible
    assert all(label.text() == "Invalid input" for label in harness.eclipse_result_labels.values())
    assert len(messages) == 1


def test_worst_case_failure_does_not_display_partial_monte_carlo_result(monkeypatch):
    monkeypatch.setattr(eclipse_mixin.QMessageBox, "warning", lambda *args: None)

    def invalid_worst_case(inputs):
        raise ValueError("Invalid tolerance geometry")

    monkeypatch.setattr(eclipse_mixin, "worst_case", invalid_worst_case)
    harness = EclipseHarness()
    harness.run_eclipse_analysis()
    assert not harness.visible
    assert all(label.text() == "Invalid input" for label in harness.eclipse_result_labels.values())


@pytest.mark.parametrize("threshold", ["0", "20", "100"])
def test_valid_threshold_updates_results_and_histogram(monkeypatch, threshold):
    monkeypatch.setattr(eclipse_mixin.QMessageBox, "warning", lambda *args: pytest.fail("Valid inputs produced a warning"))
    harness = EclipseHarness()
    harness.eclipse_threshold_input.setText(threshold)
    harness.run_eclipse_analysis()
    assert harness.visible
    assert harness.plotted_samples.shape == (10,)
    assert "chance of losing more than" in harness.eclipse_result_labels["probability"].text()
    assert "Invalid" not in harness.eclipse_result_labels["mean"].text()


def test_measured_circle_and_offset_transfers_preserve_full_precision():
    from contextlib import nullcontext

    harness = EclipseHarness()
    radius, offset = 1.000000123456789, 0.000040000123456
    harness._measure_slot = {"A": {"circle": {"radius": radius, "center": [0, 0, 0], "normal": [0, 0, 1]}},
                             "B": {"circle": {"radius": 1, "center": [offset, 0, 2], "normal": [0, 0, 1]}}}
    harness.eclipse_reference_axis_combo = SimpleNamespace(currentText=lambda: "X")
    harness._eclipse_widget_update = nullcontext
    harness._measure_last = {"circle_center_distance": offset}
    harness.use_measured_a_for_handle()
    harness.use_measured_offset()
    assert float(harness.eclipse_handle_nominal_input.text()) == radius * 2
    assert float(harness.eclipse_offset_x_nominal_input.text()) == offset
