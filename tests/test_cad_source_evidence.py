"""Loaded geometry evidence stays distinct from declared and later file revisions."""

from copy import deepcopy
import hashlib

import pytest

from tolstack import PartDefinition, Project
from tolstack.reporting import build_report_evidence, project_report_context


def _hash(contents):
    return hashlib.sha256(contents).hexdigest()


def _capture(source, **changes):
    descriptor = {
        "kind": "cad", "path": str(source), "loaded_sha256": _hash(b"loaded CAD"),
        "loaded_hash_status": "verified", "loaded_capture_basis": "verified_geometry_source_bytes",
        "expected_sha256": _hash(b"loaded CAD"), "revision_accepted": True,
    }
    descriptor.update(changes)
    return build_report_evidence("cad_position", {"coordinates": [0.00004]},
                                 context={"sources": [descriptor]}).to_dict()


def test_matching_load_digest_establishes_geometry_file_equivalence_at_evaluation(tmp_path):
    source = tmp_path / "plate.step"
    source.write_bytes(b"loaded CAD")
    original = _capture(source)
    entry = original["input_snapshot"]["source_evidence"][0]
    assert entry["loaded_geometry_revision_status"] == "matches_loaded_geometry"
    assert entry["matches_recorded_hash"] is True
    source.write_bytes(b"revised CAD after evaluation")
    later = _capture(source)
    changed = later["input_snapshot"]["source_evidence"][0]
    assert changed["loaded_geometry_revision_status"] == "differs_from_loaded_geometry"
    assert changed["sha256"] == _hash(source.read_bytes())
    assert changed["loaded_sha256"] == _hash(b"loaded CAD")
    assert entry["sha256"] == _hash(b"loaded CAD")
    assert original["input_digest"] != later["input_digest"]


@pytest.mark.parametrize("changes", [
    {"loaded_sha256": None}, {"loaded_hash_status": "unverified"},
    {"loaded_capture_basis": "declared_project_hash"}, {"loaded_sha256": "invented"},
])
def test_declared_or_unverified_hash_cannot_establish_loaded_geometry_identity(tmp_path, changes):
    source = tmp_path / "plate.step"
    source.write_bytes(b"loaded CAD")
    result = _capture(source, **changes)
    entry = result["input_snapshot"]["source_evidence"][0]
    assert entry["matches_recorded_hash"] is True
    assert entry["loaded_geometry_revision_status"] == "unverified"


def test_missing_referenced_file_retains_separate_load_digest_without_claiming_file_hash(tmp_path):
    result = _capture(tmp_path / "missing.step")
    entry = result["input_snapshot"]["source_evidence"][0]
    assert entry["loaded_sha256"] == _hash(b"loaded CAD")
    assert entry["sha256"] is None
    assert entry["hash_status"] == "unavailable"
    assert entry["loaded_geometry_revision_status"] == "referenced_file_unavailable"


def test_legacy_uppercase_expected_digest_matches_same_loaded_and_referenced_bytes(tmp_path):
    source = tmp_path / "plate.step"
    source.write_bytes(b"loaded CAD")
    result = _capture(source, expected_sha256=_hash(b"loaded CAD").upper())
    entry = result["input_snapshot"]["source_evidence"][0]
    assert entry["matches_recorded_hash"] is True
    assert entry["loaded_geometry_revision_status"] == "matches_loaded_geometry"


def test_resolved_cad_sources_replace_default_paths_and_detach_session_metadata(tmp_path):
    project = Project("Portable study")
    part = project.add_part(PartDefinition("Plate", "../CAD/plate.step"))
    descriptors = [{"kind": "cad", "part_id": part.id, "path": str(tmp_path / "CAD" / "plate.step"),
                    "loaded_sha256": _hash(b"loaded CAD"), "loaded_hash_status": "verified"}]
    context = project_report_context(project, cad_sources=descriptors,
                                     sources=[{"kind": "inspection_csv", "path": "measurements.csv"}])
    original = deepcopy(context)
    descriptors[0]["path"] = "other.step"
    assert context == original
    assert len(context["sources"]) == 2
    assert context["sources"][0]["path"] == str(tmp_path / "CAD" / "plate.step")
