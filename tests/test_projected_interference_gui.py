"""Exercise both modes, real Qt signals, measurement transfers and charts."""

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from gui.app import TolstackWindow


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    instance = TolstackWindow()
    instance.workspace_buttons["eclipse"].click()
    for prefix, value in (("handle", "2"), ("sticker", "4"), ("offset_x", "0"), ("offset_y", "0")):
        getattr(instance, f"eclipse_{prefix}_nominal_input").setText(value)
    instance.eclipse_iterations_input.setValue(100)
    yield instance
    instance.close()
    app.processEvents()


def test_default_mode_preserves_hole_aperture_model_and_new_navigation(window):
    assert window.workspace_buttons["eclipse"].text() == "Projected interference"
    assert window.workspace_title.text() == "Projected interference"
    assert window.eclipse_mode_combo.currentIndex() == 0
    assert window.eclipse_handle_caption.text() == "Hole A diameter (mm)"
    assert window.eclipse_sticker_caption.text() == "Hole B diameter (mm)"
    window.run_eclipse_analysis()
    assert window.eclipse_result_labels["mean"].text() == "0.00 %"
    assert "full tolerance zone" in window.eclipse_result_labels["worst_case"].text()
    assert window.eclipse_result_labels["clearance_mean"].isHidden()
    assert len(window.eclipse_figure.axes) == 1
    assert window.eclipse_figure.axes[0].get_xlabel() == "Aperture loss (%)"


def test_pin_mode_reports_oversize_area_clearance_and_two_histograms(window):
    window.eclipse_mode_combo.setCurrentIndex(1)
    assert window.eclipse_handle_caption.text() == "Hole diameter (mm)"
    assert window.eclipse_sticker_caption.text() == "Pin diameter (mm)"
    window.run_eclipse_analysis()
    labels = window.eclipse_result_labels
    assert labels["mean"].text() == "75.00 %"
    assert labels["clearance_mean"].text() == "-1 mm"
    assert labels["clearance_std"].text() == "0 mm"
    assert "100.00 %" in labels["interference"].text()
    assert "pin area outside" in labels["probability"].text()
    assert "Monte Carlo, 100 samples" in labels["mc_range"].text()
    assert labels["worst_case"].isHidden()
    assert not labels["clearance_bounds"].isHidden()
    assert len(window.eclipse_figure.axes) == 2
    assert window.eclipse_figure.axes[0].get_xlabel() == "Pin area outside hole (%)"
    assert "Radial clearance" in window.eclipse_figure.axes[1].get_xlabel()


@pytest.mark.parametrize("widget,value", [
    ("eclipse_handle_nominal_input", "3"), ("eclipse_sticker_tol_plus_input", ".1"),
    ("eclipse_offset_x_nominal_input", ".5"), ("eclipse_offset_y_tol_minus_input", ".2"),
    ("eclipse_handle_cpk_input", "1.2"), ("eclipse_threshold_input", "10"),
    ("eclipse_iterations_input", 200), ("eclipse_mode_combo", 0),
])
def test_edits_clear_all_results_and_charts(window, widget, value):
    window.eclipse_mode_combo.setCurrentIndex(1)
    window.run_eclipse_analysis()
    control = getattr(window, widget)
    if widget.endswith("combo"):
        control.setCurrentIndex(value)
    elif isinstance(value, int):
        control.setValue(value)
    else:
        control.setText(value)
    assert all(label.text() == "—" for label in window.eclipse_result_labels.values())
    assert window.eclipse_canvas.isHidden()
    assert not window.eclipse_figure.axes
    assert window._eclipse_clearance_samples is None


def test_measurement_transfers_preserve_precision_and_pin_roles(window):
    window.eclipse_mode_combo.setCurrentIndex(1)
    hole_radius, pin_radius = 1.123456789012345, .987654321098765
    offset = .1234567890123456
    window._measure_slot = {"A": {"circle": {"radius": hole_radius, "center": [0, 0, 0], "normal": [0, 0, 1]}},
                            "B": {"circle": {"radius": pin_radius, "center": [offset, 0, 5], "normal": [0, 0, -1]}}}
    window._measure_last = {"circle_center_distance": offset}
    window.use_measured_a_for_handle()
    window.use_measured_b_for_sticker()
    window.use_measured_offset()
    assert float(window.eclipse_handle_nominal_input.text()) == 2 * hole_radius
    assert float(window.eclipse_sticker_nominal_input.text()) == 2 * pin_radius
    assert float(window.eclipse_offset_x_nominal_input.text()) == offset
    assert window.eclipse_offset_y_nominal_input.text() == "0.0"
    window.run_eclipse_analysis()
    np.testing.assert_allclose(window._eclipse_clearance_samples, hole_radius - pin_radius - offset)


@pytest.mark.parametrize("widget,value", [("eclipse_threshold_input", "101"),
                                         ("eclipse_sticker_nominal_input", "0"),
                                         ("eclipse_handle_cpk_input", "nan")])
def test_invalid_pin_runs_clear_old_results_and_report_english_error(window, monkeypatch, widget, value):
    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: messages.append(args))
    window.eclipse_mode_combo.setCurrentIndex(1)
    window.run_eclipse_analysis()
    getattr(window, widget).setText(value)
    window.run_eclipse_analysis()
    assert all(label.text() == "Invalid input" for label in window.eclipse_result_labels.values())
    assert window.eclipse_canvas.isHidden()
    assert messages[0][1] == "Invalid projected interference analysis"


def test_switching_back_restores_hole_results_and_single_chart(window):
    window.eclipse_mode_combo.setCurrentIndex(1)
    window.run_eclipse_analysis()
    window.eclipse_mode_combo.setCurrentIndex(0)
    window.run_eclipse_analysis()
    assert window.eclipse_result_labels["mean"].text() == "0.00 %"
    assert not window.eclipse_result_labels["worst_case"].isHidden()
    assert len(window.eclipse_figure.axes) == 1
