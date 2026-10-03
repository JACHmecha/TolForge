"""Report identities bind the exact evaluated inputs and retained source evidence."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

from tolstack import Dimension, PartDefinition, Project, Stack
from tolstack.analysis import AnalysisSettings, analyze_stack, update_report_limits
from tolstack import reporting
from tolstack.reporting import build_report_evidence, input_digest, project_report_context


def test_evidence_canonical_digest_covers_inputs_settings_metadata_units_and_scope(tmp_path):
    source = tmp_path / "inspection.csv"
    source.write_bytes(b"name,x\nH1,1\n")
    inputs = {"measurement": {"x": 1.234567890123, "y": .00004}}
    settings = {"seed": 42, "method": "monte_carlo"}
    project = Project("Plate", id="project-1", study={"objective": "Drawing A"})
    context = project_report_context(project, sources=[{"kind": "inspection_csv", "path": str(source)}])
    evidence = build_report_evidence("inspection", inputs, settings=settings, units={"length": "mm"},
                                     context=context, scope=["single-segment position"])
    original = evidence.to_dict()
    inputs["measurement"]["x"] = 0
    settings["seed"] = 99
    context["study"]["metadata"]["objective"] = "Other drawing"
    source.write_bytes(b"changed after evaluation")
    exported = evidence.to_dict()
    assert exported == original
    snapshot = exported["input_snapshot"]
    assert snapshot["inputs"]["measurement"]["x"] == 1.234567890123
    assert snapshot["source_evidence"][0]["sha256"] == hashlib.sha256(b"name,x\nH1,1\n").hexdigest()
    assert exported["input_digest"]["value"] == input_digest(snapshot)
    assert exported["created_at"].endswith("+00:00")
    assert exported["report_schema"] == "tolforge.engineering-report"
    assert exported["report_version"] == exported["evidence_version"] == 1
    assert exported["solver"]["version"]
    assert exported["runtime"]["python"]
    assert exported["software"]["version"]
    # Export dictionaries are detached from the envelope too.
    exported["input_snapshot"]["inputs"].clear()
    assert evidence.to_dict() == original
    assert input_digest({"a": 1, "b": [2, 3]}) == input_digest({"b": [2, 3], "a": 1})
    for section in ("inputs", "settings", "context", "units", "scope"):
        edited = json.loads(json.dumps(snapshot))
        edited[section] = {"edited": True}
        assert input_digest(edited) != original["input_digest"]["value"]


def test_source_digests_cannot_be_claimed_from_missing_files_or_free_text(tmp_path):
    sources = [
        {"kind": "drawing", "reference": "drawing A rev2"},
        {"kind": "cad", "path": str(tmp_path / "missing.step"), "sha256": "invented"},
        {"kind": "directory", "path": str(tmp_path)},
    ]
    payload = build_report_evidence("inspection", {}, context={"sources": sources}).to_dict()
    assert payload["source_evidence_status"] == "partial_or_unavailable"
    entries = payload["input_snapshot"]["source_evidence"]
    assert [entry["unavailable_reason"] for entry in entries] == ["no_file_path_supplied", "missing", "unreadable"]
    assert all(entry["sha256"] is None and entry["hash_status"] == "unavailable" for entry in entries)
    assert entries[1]["loaded_geometry_revision_status"] == "unverified"


def test_modified_csv_is_distinguished_from_bytes_actually_imported(tmp_path):
    source = tmp_path / "inspection.csv"
    imported = hashlib.sha256(b"original inspection export").hexdigest()
    source.write_bytes(b"revised export")
    payload = build_report_evidence("inspection", {}, context={"sources": [
        {"kind": "inspection_csv", "path": str(source), "import_sha256": imported},
    ]}).to_dict()
    entry = payload["input_snapshot"]["source_evidence"][0]
    assert entry["import_sha256"] == imported
    assert entry["sha256"] == hashlib.sha256(b"revised export").hexdigest()
    assert entry["matches_recorded_hash"] is False


def test_reusing_source_descriptors_recomputes_all_derived_fields(tmp_path):
    source = tmp_path / "inspection.csv"
    original_hash = hashlib.sha256(b"original").hexdigest()
    stale = {"kind": "cad", "path": str(source), "import_sha256": original_hash,
             "hash_status": "available", "unavailable_reason": "missing", "sha256": "old",
             "size_bytes": 99, "matches_recorded_hash": True,
             "loaded_geometry_revision_status": "verified", "capture_basis": "old_export"}
    unavailable = build_report_evidence("inspection", {}, context={"sources": [stale]}).to_dict()["input_snapshot"]["source_evidence"][0]
    assert unavailable["hash_status"] == "unavailable"
    assert unavailable["sha256"] is None
    assert unavailable["unavailable_reason"] == "missing"
    assert "size_bytes" not in unavailable
    assert "matches_recorded_hash" not in unavailable
    assert unavailable["loaded_geometry_revision_status"] == "unverified"
    source.write_bytes(b"new")
    available = build_report_evidence("inspection", {}, context={"sources": [unavailable]}).to_dict()["input_snapshot"]["source_evidence"][0]
    assert available["hash_status"] == "available"
    assert "unavailable_reason" not in available
    assert available["size_bytes"] == 3
    assert available["matches_recorded_hash"] is False
    assert available["capture_basis"] == "referenced_file_at_evaluation"
    assert available["import_sha256"] == original_hash
    source.unlink()
    missing_again = build_report_evidence("inspection", {}, context={"sources": [available]}).to_dict()["input_snapshot"]["source_evidence"][0]
    assert missing_again["sha256"] is None
    assert "matches_recorded_hash" not in missing_again
    assert "size_bytes" not in missing_again


def test_stable_project_study_ids_and_no_invented_plain_api_context():
    project = Project("Study", id="project-A")
    first = project_report_context(project)
    second = project_report_context(project)
    assert first["study"]["id"] == second["study"]["id"] == "project-A:study"
    assert first["study"]["id_origin"] == "derived_single_project_study"
    project.study["study_id"] = "explicit-study-id"
    assert project_report_context(project)["study"]["id"] == "explicit-study-id"
    standalone = build_report_evidence("scalar", {}).to_dict()
    assert standalone["input_snapshot"]["context"] == {"project": None, "study": None}
    assert standalone["input_snapshot"]["units"] == {"status": "unspecified"}
    assert standalone["source_evidence_status"] == "no_sources_supplied"


def test_scalar_context_and_source_hash_are_captured_before_numerical_execution(tmp_path, monkeypatch):
    source = tmp_path / "part.step"
    source.write_bytes(b"input source")
    context = {"project": {"id": "before"}, "sources": [source]}
    solver = Stack.monte_carlo

    def evaluate(stack, *args, **kwargs):
        source.write_bytes(b"later source")
        context["project"]["id"] = "after"
        return solver(stack, *args, **kwargs)

    monkeypatch.setattr(Stack, "monte_carlo", evaluate)
    report = analyze_stack(Stack([Dimension("A", 1, .1, .2)]),
                           AnalysisSettings(method="monte_carlo", iterations=20, seed=3), report_context=context)
    snapshot = report.to_dict()["evidence"]["input_snapshot"]
    assert snapshot["context"]["project"]["id"] == "before"
    assert snapshot["source_evidence"][0]["sha256"] == hashlib.sha256(b"input source").hexdigest()


def test_solver_manifest_distinguishes_source_changes_and_marks_missing_frozen_source(tmp_path, monkeypatch):
    directory = tmp_path / "tolstack"
    directory.mkdir()
    implementation = directory / "stack.py"
    implementation.write_text("first numerical implementation", encoding="utf-8")
    monkeypatch.setattr(reporting, "__file__", str(directory / "reporting.py"))
    original = reporting._implementation_manifest()
    implementation.write_text("changed numerical implementation", encoding="utf-8")
    changed = reporting._implementation_manifest()
    assert original["sha256"] != changed["sha256"]
    assert original["files"][0]["module"] == "tolstack.stack"
    assert original["files"][0]["sha256"] == hashlib.sha256(b"first numerical implementation").hexdigest()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    unavailable = reporting._implementation_manifest()
    assert unavailable["status"] == "unavailable"
    assert unavailable["sha256"] is None
    assert unavailable["files"] == []


def test_limit_and_assumption_reassessment_creates_new_snapshot_without_rehashing_sources(tmp_path, monkeypatch):
    source = tmp_path / "part.step"
    source.write_bytes(b"evaluated cad source")
    project = Project("Study", id="project-A")
    project.add_part(PartDefinition("Plate", str(source)))
    report = analyze_stack(Stack([Dimension("Clearance", 1, .1, .1)]),
                           AnalysisSettings(lower_limit=.8, upper_limit=1.2),
                           report_context=project_report_context(project))
    old_payload = report.to_dict()
    source.write_bytes(b"changed source")
    monkeypatch.setattr(reporting, "_source_evidence", lambda value: pytest.fail("A reassessment must not reread sources"))
    revised = update_report_limits(report, .95, 1.05, assumptions=["Reviewed assumption"])
    assert revised.result is report.result
    evidence = revised.to_dict()["evidence"]
    original = old_payload["evidence"]
    assert evidence["report_id"] != original["report_id"]
    assert evidence["input_snapshot_id"] != original["input_snapshot_id"]
    assert evidence["input_digest"]["value"] != original["input_digest"]["value"]
    assert evidence["derived_from_report_id"] == original["report_id"]
    assert evidence["result_evaluated_at"] == original["result_evaluated_at"]
    assert evidence["input_snapshot"]["source_evidence"] == original["input_snapshot"]["source_evidence"]
    assert evidence["input_snapshot"]["settings"]["lower_limit"] == .95
    assert evidence["input_snapshot"]["scope"] == ["Reviewed assumption"]
    assert report.to_dict() == old_payload
    assert update_report_limits(revised, .95, 1.05) is revised


@pytest.mark.parametrize("method", ["worst_case", "rss", "monte_carlo"])
def test_scalar_exports_keep_the_evaluated_input_snapshot(method):
    report = analyze_stack(Stack([Dimension("A", 1, .1, .2)]), AnalysisSettings(method=method, iterations=20, seed=3))
    before = report.to_dict()
    report.dimensions[0].nominal = 200
    after = report.to_dict()
    assert after == before
    assert after["dimensions"] == after["evidence"]["input_snapshot"]["inputs"]["dimensions"]
    assert after["settings"] == after["evidence"]["input_snapshot"]["settings"]


@pytest.mark.parametrize("method", ["worst_case", "monte_carlo"])
def test_scalar_export_result_fit_and_contributors_cannot_change_under_the_same_identity(method):
    report = analyze_stack(Stack([Dimension("A", 1, .1, .2)]),
                           AnalysisSettings(method=method, iterations=20, seed=3, lower_limit=.8, upper_limit=1.2))
    snapshot = report.to_dict()
    if method == "worst_case":
        report.result.nominal = 200
        report.result.upper_limit = 300
    else:
        report.result.mean = 200
        report.result.samples[:] = 100
    report.fit_at_zero.verdict = "changed after evaluation"
    object.__setattr__(report.contributions[0], "expected_source_value", 100)
    assert report.to_dict() == snapshot
    edited_copy = report.to_dict()
    edited_copy["result"].clear()
    assert report.to_dict() == snapshot


@pytest.mark.parametrize("method", ["worst_case", "rss", "monte_carlo"])
def test_reassessment_uses_original_values_after_public_report_objects_are_mutated(method):
    report = analyze_stack(Stack([Dimension("A", 1, .1, .2)]), AnalysisSettings(
        method=method, iterations=20, seed=3, lower_limit=.8, upper_limit=1.2,
    ))
    original = report.to_dict()
    expected = update_report_limits(report, .95, 1.05).to_dict()
    report.dimensions[0].nominal = 200
    if method == "monte_carlo":
        report.result.samples[:] = 100
        report.result.mean = 100
        report.result.minimum = 100
        report.result.maximum = 100
    else:
        report.result.nominal = 100
        report.result.lower_limit = 99
        report.result.upper_limit = 101
    report.fit_at_zero.verdict = "caller edit"
    object.__setattr__(report.contributions[0], "expected_source_value", 100)
    revised = update_report_limits(report, .95, 1.05)
    payload = revised.to_dict()
    for key in ("settings", "dimensions", "result", "acceptance", "fit_at_zero",
                "contributions", "expected_response", "expected_variance", "assumptions"):
        assert payload[key] == expected[key]
    assert revised.result is not report.result
    assert payload["evidence"]["input_digest"] == expected["evidence"]["input_digest"]
    assert payload["evidence"]["report_id"] != original["evidence"]["report_id"]
    assert report.to_dict() == original
    if method == "monte_carlo":
        with pytest.raises(ValueError):
            revised.result.samples[0] = 100
        # A second reassessment retains the original numeric result too.
        second = update_report_limits(revised, .9, 1.1)
        assert second.to_dict()["result"] == original["result"]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), object()])
def test_evidence_rejects_invalid_input_snapshot(bad):
    with pytest.raises(ValueError):
        build_report_evidence("scalar", {"numeric_input": bad})
