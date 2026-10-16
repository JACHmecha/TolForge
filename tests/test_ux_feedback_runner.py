"""Infrastructure faults must leave evidence and must never masquerade as UX success."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import types

import pytest


@pytest.fixture
def runner(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("ux_feedback_cli_under_test", scripts / "run_ux_feedback.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_timed_out_window_is_a_runner_fault_with_logs(runner, tmp_path, monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(runner.subprocess, "run", timeout)
    result = runner.run_configuration(tmp_path, (1300, 800), timeout=10)
    assert result["status"] == "runner_error"
    assert result["findings"][0]["classification"] == "runner_error"
    assert all(item["status"] == "not_run" for item in result["scenarios"])
    assert (tmp_path / "stdout.log").is_file()
    assert (tmp_path / "stderr.log").is_file()


def test_process_without_result_cannot_pass(runner, tmp_path, monkeypatch):
    monkeypatch.setattr(runner.subprocess, "run", lambda *args, **kwargs: types.SimpleNamespace(returncode=0))
    result = runner.run_configuration(tmp_path, (1300, 800), timeout=10)
    assert result["status"] == "runner_error"
    assert "result.json" in result["findings"][0]["description"]


def test_empty_or_incomplete_worker_success_is_rejected(runner, tmp_path):
    result = {"status": "pass", "steps": [], "scenarios": [], "findings": []}
    with pytest.raises(ValueError, match="U01"):
        runner.validate_configuration(result, "window", (1300, 800), tmp_path)


def test_screenshot_cannot_escape_its_configuration(runner, tmp_path):
    result = {
        "status": "product_failure", "scenarios": [], "findings": [],
        "steps": [{"screenshot": "../another-study.png"}],
    }
    with pytest.raises(ValueError, match="unsafe screenshot"):
        runner.validate_configuration(result, "window", (1300, 800), tmp_path)


@pytest.mark.parametrize("field", ["steps", "scenarios", "findings"])
def test_malformed_worker_entries_are_classified_without_aborting(runner, tmp_path, monkeypatch, field):
    result = {"status": "pass", "steps": [], "scenarios": [], "findings": []}
    result[field] = ["not a structured entry"]
    (tmp_path / "result.json").write_text(json.dumps(result), encoding="utf-8")
    monkeypatch.setattr(runner.subprocess, "run", lambda *args, **kwargs: types.SimpleNamespace(returncode=0))
    observed = runner.run_configuration(tmp_path, (1300, 800), timeout=10)
    assert observed["status"] == "runner_error"
    assert "malformed evidence" in observed["findings"][0]["description"]


def test_source_changes_invalidate_an_otherwise_passing_matrix(runner):
    report = {"status": "pass", "source": {"revision": "revision", "files": {"Code/gui/app.py": "before"}},
              "configurations": [{"status": "pass", "findings": []}]}
    runner.reconcile_source(report, {"revision": "revision", "files": {"Code/gui/app.py": "after"}})
    assert report["status"] == "runner_error"
    assert report["source_validation"]["changed_files"] == ["Code/gui/app.py"]
    assert report["configurations"][0]["findings"][0]["classification"] == "runner_error"


def test_consistent_source_preserves_the_matrix_result(runner):
    source = {"revision": "revision", "files": {"Code/gui/app.py": "same"}}
    report = {"status": "pass", "source": source, "configurations": []}
    runner.reconcile_source(report, source)
    assert report["status"] == "pass"
    assert report["source_validation"]["consistent"]


def test_missing_gui_environment_is_reported_as_infrastructure(runner, tmp_path, monkeypatch):
    journey = types.ModuleType("ux_feedback.journey")

    def missing_environment(*args, **kwargs):
        raise ImportError("synthetic missing Qt dependency")

    journey.run_journey = missing_environment
    monkeypatch.setitem(sys.modules, "ux_feedback.journey", journey)
    assert runner.worker(tmp_path, (1300, 800)) == 2
    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "infrastructure_unavailable"
    assert result["findings"][0]["classification"] == "infrastructure"


def test_matrix_with_missing_coverage_cannot_be_approved(runner):
    assert runner.aggregate_status([]) == "runner_error"
    assert runner.aggregate_status([{"status": "pass"}, {"status": "infrastructure_unavailable"}]) == "infrastructure_unavailable"
    assert runner.aggregate_status([{"status": "pass"}, {"status": "product_failure"}]) == "product_failure"
