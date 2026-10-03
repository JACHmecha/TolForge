"""CAD reports bind the displayed frame/settings before numerical execution."""

import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QLineEdit, QSpinBox, QTableWidget
from matplotlib.figure import Figure

from gui.analysis_mixin import AnalysisMixin
from gui.gdt_mixin import GdtMixin
from gui import gdt_mixin
from tolstack import PartDefinition, Project
from tolstack.gdt import PatternFeature, PatternPositionControl


class CadHarness(GdtMixin, AnalysisMixin):
    def __init__(self, source):
        self.project = Project("Plate study", id="stable-project")
        self.project.add_part(PartDefinition("Plate", str(source)))
        self._current_drf = SimpleNamespace(origin=np.array([1., 2., 3.]),
                                          x_axis=np.array([1., 0., 0.]),
                                          y_axis=np.array([0., 1., 0.]),
                                          z_axis=np.array([0., 0., 1.]))
        self._datum_slot = {"Primary": {"feature_id": "datum-A", "kind": "plane"},
                            "Secondary": None, "Tertiary": None}
        self.pattern_table = QTableWidget(1, 10)
        self.control = PatternPositionControl([
            PatternFeature("H1", 0, 0, .02, .01, 10.1, .1, .1,
                           position_tol_plus_x=.05, position_tol_minus_x=.05,
                           position_tol_plus_y=.05, position_tol_minus_y=.05),
        ], .08, "MMC", 10., 10.2, "hole")
        self.gdt_result_labels = {key: QLabel() for key in
                                 ("nominal", "virtual_condition", "pattern_fail_rate", "per_feature")}
        self.gdt_iterations_input = QSpinBox()
        self.gdt_iterations_input.setRange(1, 100000)
        self.gdt_iterations_input.setValue(120)
        self.gdt_default_cpk_input = QLineEdit("1.33")
        self.seed_input = QLineEdit("42")
        self.study_objective_input = QLineEdit("Drawing A rev2")
        self.study_assumptions_input = QLineEdit("Externally reviewed assumptions")
        self.gdt_figure = Figure()
        self.gdt_canvas = SimpleNamespace(setVisible=lambda value: None, draw=lambda: None)
        self.exports = []

    def _project_build_pattern_control(self):
        return self.control

    def _save_report(self, payload, filename):
        self.exports.append(payload)


@pytest.fixture
def harness(tmp_path):
    application = QApplication.instance() or QApplication([])
    source = tmp_path / "plate.step"
    source.write_bytes(b"source bytes at evaluation")
    instance = CadHarness(source)
    yield instance, source
    instance.pattern_table.deleteLater()
    application.processEvents()


def test_cad_as_modeled_report_retains_control_frame_context_and_source_at_evaluation(harness):
    gui, source = harness
    gui.evaluate_pattern_deterministic()
    report = gui._last_gdt_report
    evidence = report["evidence"]
    snapshot = evidence["input_snapshot"]
    assert snapshot["settings"] == {"method": "as_modeled"}
    assert snapshot["inputs"]["datum_frame"]["origin"] == [1., 2., 3.]
    assert snapshot["inputs"]["control"]["base_tolerance_diameter"] == .08
    assert snapshot["inputs"]["datum_assignments"] == [{"slot": "Primary", "feature_id": "datum-A", "kind": "plane"}]
    assert snapshot["context"]["project"]["id"] == "stable-project"
    assert snapshot["context"]["study"]["metadata"]["requirement"] == "Drawing A rev2"
    assert snapshot["source_evidence"][0]["loaded_geometry_revision_status"] == "unverified"
    assert any("loaded geometry revision" in limitation for limitation in report["limitations"])
    source.write_bytes(b"edited source after evaluation")
    gui._current_drf.origin[0] = 100
    gui.control.features[0].actual_x = 200
    gui.project.name = "Edited project name"
    gui._export_gdt_report()
    exported = gui.exports[0]
    assert exported["datum_frame"]["origin"] == [1., 2., 3.]
    assert exported["control"]["features"][0]["actual_x"] == .02
    assert exported["evidence"]["input_snapshot"]["context"]["project"]["name"] == "Plate study"
    assert exported["evidence"]["input_snapshot"]["source_evidence"][0]["sha256"] == hashlib.sha256(b"source bytes at evaluation").hexdigest()


def test_cad_monte_carlo_evidence_is_captured_before_solver_with_effective_settings(harness, monkeypatch):
    gui, source = harness
    solver = gdt_mixin.run_pattern_monte_carlo

    def evaluate(control, **kwargs):
        source.write_bytes(b"changed while solver runs")
        return solver(control, **kwargs)

    monkeypatch.setattr(gdt_mixin, "run_pattern_monte_carlo", evaluate)
    gui.run_pattern_monte_carlo_analysis()
    report = gui._last_gdt_report
    assert report["method"] == "monte_carlo"
    snapshot = report["evidence"]["input_snapshot"]
    assert snapshot["settings"] == {"method": "monte_carlo", "iterations": 120, "seed": 42, "default_cpk": 1.33}
    assert snapshot["source_evidence"][0]["sha256"] == hashlib.sha256(b"source bytes at evaluation").hexdigest()
    assert snapshot["units"] == {"length": "mm", "angle": "deg"}
    assert report["pattern_fail_rate"] >= 0


def test_stored_expected_hash_does_not_suppress_unverified_loaded_revision_limitation(harness):
    gui, source = harness
    next(iter(gui.project.parts.values())).source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    gui.evaluate_pattern_deterministic()
    report = gui._last_gdt_report
    entry = report["evidence"]["input_snapshot"]["source_evidence"][0]
    assert entry["matches_recorded_hash"] is True
    assert entry["loaded_geometry_revision_status"] == "unverified"
    assert any("loaded geometry revision" in limitation for limitation in report["limitations"])
