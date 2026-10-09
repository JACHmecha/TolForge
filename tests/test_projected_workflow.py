"""Integrated CAD projection, units, repeatable runs and preview behavior."""

import math

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from gui.app import TolstackWindow
from tolstack.project import Project


@pytest.fixture
def window(monkeypatch):
    app = QApplication.instance() or QApplication([])
    result = TolstackWindow()
    result.eclipse_iterations_input.setValue(300)
    result._warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: result._warnings.append(args))
    yield result
    result.close()
    app.processEvents()


def cad_pair(window, offset=(0, 1, 3), normal_b=(0, 0, -1)):
    window._measure_slot = {
        "A": {"circle": {"radius": 2, "center": [0, 0, 0], "normal": [0, 0, 1]}},
        "B": {"circle": {"radius": 1, "center": list(offset), "normal": list(normal_b)}},
    }


def test_signed_cad_xy_preserves_anisotropic_tolerance_bounds(window):
    cad_pair(window)
    window.eclipse_mode_combo.setCurrentIndex(1)
    window.use_measured_offset()
    assert not window._warnings
    assert window.eclipse_offset_x_nominal_input.text() == "0.0"
    assert window.eclipse_offset_y_nominal_input.text() == "1.0"
    window.eclipse_offset_x_tol_plus_input.setText(".2")
    window.eclipse_offset_x_tol_minus_input.setText(".2")
    window.run_eclipse_analysis()
    assert not window._warnings
    expected = 1 - math.hypot(.2, 1)
    assert f"{expected:+.6g} - +0 mm" in window.eclipse_result_labels["clearance_bounds"].text()
    assert window.eclipse_preview.valid
    assert window._eclipse_projection_frame["axial_separation"] == 3
    assert window._project_is_dirty()


def test_rejected_tilt_preserves_values_and_prior_projection(window):
    cad_pair(window)
    window.use_measured_offset()
    before = window._eclipse_save_settings()
    cad_pair(window, normal_b=(.02, 0, 1))
    window.use_measured_offset()
    assert window._warnings
    assert window._eclipse_save_settings() == before


def test_reference_axis_selection_and_displayed_fallback(window):
    cad_pair(window, offset=(-.5, .3, 2))
    window.eclipse_reference_axis_combo.setCurrentText("Z")
    window.use_measured_offset()
    assert "fallback" in window.eclipse_projection_label.text()
    assert float(window.eclipse_offset_x_nominal_input.text()) == -.5
    assert float(window.eclipse_offset_y_nominal_input.text()) == .3
    window.eclipse_reference_axis_combo.setCurrentText("Y")
    assert window._eclipse_projection_frame is None
    window.use_measured_offset()
    assert float(window.eclipse_offset_x_nominal_input.text()) == .3
    assert float(window.eclipse_offset_y_nominal_input.text()) == .5


def test_units_convert_every_length_and_preserve_dimensionless_parameters(window):
    cad_pair(window, offset=(.5, -.3, 2))
    window.use_measured_offset()
    window.eclipse_handle_tol_plus_input.setText(".2")
    window.eclipse_sticker_tol_minus_input.setText(".1")
    window.eclipse_offset_x_tol_plus_input.setText(".4")
    window.eclipse_handle_cpk_input.setText("1.3")
    window.eclipse_seed_input.setText("123")
    before = window._eclipse_save_settings()
    window.eclipse_units_combo.setCurrentText("in")
    after = window._eclipse_save_settings()
    for prefix, values in before["inputs"].items():
        for key in ("nominal", "tol_plus", "tol_minus"):
            assert after["inputs"][prefix][key] == pytest.approx(values[key] / 25.4)
        assert after["inputs"][prefix]["cpk"] == values["cpk"]
    for key in ("seed", "threshold", "iterations", "projection"):
        assert after[key] == before[key]
    assert "(in)" in window.eclipse_handle_caption.text()
    assert " in" in window.eclipse_preview.summary.text()
    assert window.eclipse_handle_nominal_input.cursorPosition() == 0
    assert window.eclipse_handle_nominal_input.toolTip() == window.eclipse_handle_nominal_input.text()
    window.eclipse_units_combo.setCurrentText("mm")
    restored = window._eclipse_save_settings()
    for prefix, values in before["inputs"].items():
        for key in ("nominal", "tol_plus", "tol_minus"):
            assert restored["inputs"][prefix][key] == pytest.approx(values[key])


@pytest.mark.parametrize("bad", ["unfinished", "nan", "inf", "1e309"])
def test_unit_conversion_failure_is_atomic(window, bad):
    cad_pair(window)
    window.use_measured_offset()
    window.eclipse_offset_y_tol_plus_input.setText(bad)
    before = [getattr(window, f"eclipse_{prefix}_{field}_input").text()
              for prefix in ("handle", "sticker", "offset_x", "offset_y")
              for field in ("nominal", "tol_plus", "tol_minus")]
    window.eclipse_units_combo.setCurrentText("in")
    after = [getattr(window, f"eclipse_{prefix}_{field}_input").text()
             for prefix in ("handle", "sticker", "offset_x", "offset_y")
             for field in ("nominal", "tol_plus", "tol_minus")]
    assert window._warnings
    assert before == after
    assert window._eclipse_length_unit() == window.eclipse_units_combo.currentText() == "mm"


def test_cad_transfers_convert_to_inches_without_relabeling_raw_mm_snapshot(window):
    window.eclipse_units_combo.setCurrentText("in")
    cad_pair(window, offset=(-2.54, 5.08, 10))
    window.use_measured_a_for_handle()
    window.use_measured_b_for_sticker()
    assert float(window.eclipse_handle_nominal_input.text()) == pytest.approx(4 / 25.4)
    window.use_measured_offset()
    assert float(window.eclipse_offset_x_nominal_input.text()) == pytest.approx(-.1)
    assert float(window.eclipse_offset_y_nominal_input.text()) == pytest.approx(.2)
    snapshot = window._eclipse_projection_snapshot()
    assert snapshot["source_units"] == "mm"
    assert snapshot["frame"]["offset_x"] == -2.54


@pytest.mark.parametrize("hole,pin", [(10, 9), (10, 9.5), (10, 9.999)])
def test_contact_disposition_survives_mm_in_conversion(window, hole, pin):
    window.eclipse_mode_combo.setCurrentIndex(1)
    window.eclipse_handle_nominal_input.setText(str(hole))
    window.eclipse_sticker_nominal_input.setText(str(pin))
    window.eclipse_offset_x_nominal_input.setText(repr((hole - pin) / 2))
    window.eclipse_threshold_input.setText("0")
    for unit in ("mm", "in", "mm"):
        window.eclipse_units_combo.setCurrentText(unit)
        window.run_eclipse_analysis()
        assert window.eclipse_result_labels["interference"].text().startswith("0.00 %")
        assert window.eclipse_result_labels["probability"].text().startswith("0.00 %")
        assert "(contact)" in window.eclipse_preview.summary.text()
    assert not window._warnings


@pytest.mark.parametrize("mode", [0, 1])
def test_seeded_gui_runs_reproduce_across_save_and_reopen(window, tmp_path, mode):
    cad_pair(window, offset=(.5, .5, 0))
    window.use_measured_offset()
    window.eclipse_mode_combo.setCurrentIndex(mode)
    window.eclipse_handle_tol_plus_input.setText(".2")
    window.eclipse_sticker_tol_plus_input.setText(".3")
    window.eclipse_offset_x_tol_minus_input.setText(".2")
    window.eclipse_offset_y_tol_plus_input.setText(".3")
    window.eclipse_seed_input.setText("42")
    samples = []
    original_plot = window._eclipse_plot_histogram
    def capture(values):
        samples.append(values.copy())
        original_plot(values)
    window._eclipse_plot_histogram = capture
    np.random.seed(987)
    global_before = np.random.get_state()
    window.run_eclipse_analysis()
    window.run_eclipse_analysis()
    np.testing.assert_array_equal(samples[0], samples[1])
    global_after = np.random.get_state()
    assert global_before[0] == global_after[0]
    np.testing.assert_array_equal(global_before[1], global_after[1])
    assert global_before[2:] == global_after[2:]
    path = tmp_path / "projected.tolforge.json"
    assert window._project_save_to(path)
    window.eclipse_seed_input.setText("11")
    window.run_eclipse_analysis()
    assert not np.array_equal(samples[0], samples[2])
    assert window._project_open_from(path)
    assert not window.eclipse_figure.axes
    window.run_eclipse_analysis()
    np.testing.assert_array_equal(samples[0], samples[3])
    assert not window._warnings


def test_seed_and_unit_changes_clear_results_but_keep_live_nominal_preview(window):
    cad_pair(window, offset=(.5, .2, 1))
    window.use_measured_offset()
    window.run_eclipse_analysis()
    assert window.eclipse_figure.axes
    window.eclipse_seed_input.setText("7")
    assert not window.eclipse_figure.axes
    assert window.eclipse_preview.valid
    window.eclipse_units_combo.setCurrentText("in")
    assert window.eclipse_preview.valid
    assert " in" in window.eclipse_preview.summary.text()
    window.eclipse_sticker_nominal_input.setText("unfinished")
    assert not window.eclipse_preview.valid
    assert window._eclipse_projection_frame is None


def test_valid_optional_null_projection_opens_with_default_reference(window, tmp_path):
    cad_pair(window)
    window.use_measured_offset()
    settings = window._eclipse_save_settings()
    settings["projection"] = None
    project = Project("Optional projection", study={"projected_interference": settings})
    path = tmp_path / "optional-projection.tolforge.json"
    project.save(path)
    assert window._project_open_from(path)
    assert window.eclipse_reference_axis_combo.currentText() == "X"
    assert window._eclipse_projection_frame is None
    assert window.eclipse_preview.valid
    assert not window._warnings


@pytest.mark.parametrize("text", ["", "unfinished"])
def test_incomplete_iteration_edit_immediately_invalidates_results(window, text):
    cad_pair(window)
    window.use_measured_offset()
    window.run_eclipse_analysis()
    assert window.eclipse_figure.axes
    window.eclipse_iterations_input.lineEdit().setText(text)
    assert not window.eclipse_iterations_input.hasAcceptableInput()
    assert not window.eclipse_figure.axes
    assert window.eclipse_canvas.isHidden()
    assert all(label.text() == "—" for label in window.eclipse_result_labels.values())


@pytest.mark.parametrize("seed", ["-1", "1.2", "4294967296", "invalid"])
def test_invalid_gui_seed_rejected_and_clears_results(window, seed):
    cad_pair(window)
    window.use_measured_offset()
    window.run_eclipse_analysis()
    window.eclipse_seed_input.setText(seed)
    window.run_eclipse_analysis()
    assert window._warnings
    assert window.eclipse_canvas.isHidden()
    assert all(label.text() == "Invalid input" for label in window.eclipse_result_labels.values())
