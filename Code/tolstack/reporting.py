"""Evaluation-time evidence for engineering reports, independent of Qt.

Evidence owns an immutable JSON snapshot. Export only copies that snapshot;
it never rereads source files or reconstructs inputs from current widgets.
"""

from __future__ import annotations

from dataclasses import dataclass
import ast
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
from uuid import uuid4

from .json_data import validate_json_value


REPORT_SCHEMA = "tolforge.engineering-report"
REPORT_VERSION = 1
EVIDENCE_VERSION = 1
SOLVER_VERSION = "1"


def canonical_json(value) -> str:
    """Stable UTF-8 JSON representation used to identify an input snapshot."""
    validate_json_value(value, "Report snapshot")
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def input_digest(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _copy_json(value):
    return json.loads(canonical_json(value))


@dataclass(frozen=True)
class ReportEvidence:
    """Frozen envelope; every caller receives a detached export dictionary."""

    _json: str

    def to_dict(self) -> dict:
        return json.loads(self._json)


def _source_evidence(descriptor) -> dict:
    if isinstance(descriptor, (str, Path)):
        descriptor = {"path": str(descriptor)}
    if not isinstance(descriptor, dict):
        raise ValueError("Report sources must be path strings or descriptors.")
    entry = _copy_json(descriptor)
    # An expected/imported digest is metadata, never a replacement for proof
    # that this referenced file was actually readable at evaluation time.
    for field in ("sha256", "capture_basis", "hash_status", "unavailable_reason",
                  "size_bytes", "matches_recorded_hash", "loaded_geometry_revision_status"):
        entry.pop(field, None)
    entry["capture_basis"] = "referenced_file_at_evaluation"
    entry["sha256"] = None
    entry["hash_status"] = "unavailable"
    loaded_digest = entry.get("loaded_sha256")
    verified_load = (
        entry.get("loaded_hash_status") == "verified"
        and entry.get("loaded_capture_basis") == "verified_geometry_source_bytes"
        and isinstance(loaded_digest, str)
        and re.fullmatch(r"[0-9a-f]{64}", loaded_digest) is not None
    )
    if entry.get("kind") == "cad":
        entry["loaded_geometry_revision_status"] = (
            "referenced_file_unavailable" if verified_load else "unverified"
        )
    path = entry.get("path")
    if not isinstance(path, str) or not path.strip():
        entry["unavailable_reason"] = "no_file_path_supplied"
        return entry
    source = Path(path)
    try:
        before = source.stat()
        digest = hashlib.sha256()
        with source.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        after = source.stat()
    except OSError as exc:
        entry["unavailable_reason"] = "missing" if isinstance(exc, FileNotFoundError) else "unreadable"
        return entry
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        entry["unavailable_reason"] = "changed_during_capture"
        return entry
    entry.update(sha256=digest.hexdigest(), hash_status="available", size_bytes=after.st_size)
    expected = entry.get("expected_sha256") or entry.get("import_sha256")
    if expected:
        normalized_expected = (expected.lower() if isinstance(expected, str)
                               and re.fullmatch(r"[0-9a-fA-F]{64}", expected) else expected)
        entry["matches_recorded_hash"] = normalized_expected == entry["sha256"]
    if entry.get("kind") == "cad" and verified_load:
        entry["loaded_geometry_revision_status"] = (
            "matches_loaded_geometry" if loaded_digest == entry["sha256"]
            else "differs_from_loaded_geometry"
        )
    return entry


def project_report_context(project, *, study_metadata=None, sources=(), cad_sources=None) -> dict:
    """Plain, detached project/default-study context for GUI evaluation.

    Schema 1 has one Study workspace. Its derived ID is stable for the same
    project even before a separately stored study_id exists; its origin is
    explicit so it cannot be mistaken for an external inspection-system ID.
    """
    if project is None:
        return {"project": None, "study": None, "sources": list(sources)}
    study = project.study
    stored_id = study.get("study_id")
    resolved_cad_sources = list(cad_sources) if cad_sources is not None else [
        {"kind": "cad", "part_id": part.id, "reference": part.name,
         "path": part.source_file, "expected_sha256": part.source_sha256}
        for part in project.parts.values()
    ]
    return _copy_json({
        "project": {"id": project.id, "name": project.name,
                    "schema_version": project.schema_version},
        "study": {"id": stored_id or f"{project.id}:study",
                  "id_origin": "stored" if stored_id else "derived_single_project_study",
                  "metadata": study_metadata if study_metadata is not None else study},
        "sources": resolved_cad_sources + list(sources),
    })


def _version(package):
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return None


def _source_package_version():
    """Read the source declaration without importing/executing setup.py."""
    try:
        tree = ast.parse((Path(__file__).resolve().parents[2] / "setup.py").read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "setup":
                for keyword in node.keywords:
                    if keyword.arg == "version" and isinstance(keyword.value, ast.Constant):
                        return keyword.value.value if isinstance(keyword.value.value, str) else None
    except (OSError, SyntaxError):
        pass
    return None


def _implementation_manifest():
    directory = Path(__file__).resolve().parent
    entries = []
    # Source is often absent in frozen artifacts. Do not claim the source tree's
    # digest identifies a binary; its executable hash is separate build evidence.
    if not getattr(sys, "frozen", False):
        for path in sorted(directory.glob("*.py")):
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                entries.append({"module": f"tolstack.{path.stem}", "sha256": digest, "status": "available"})
            except OSError:
                entries.append({"module": f"tolstack.{path.stem}", "sha256": None, "status": "unavailable"})
    complete = bool(entries) and all(item["status"] == "available" for item in entries)
    return {"capture_basis": "source_file_bytes_at_evaluation",
            "status": "available" if complete else "partial_or_unavailable" if entries else "unavailable",
            "files": entries, "sha256": input_digest(entries) if complete else None}


def _runtime_evidence(solver) -> dict:
    # Git is optional for installed/frozen/library use. Missing provenance is
    # stated explicitly rather than substituted with an invented revision.
    revision = None
    dirty = None
    if not getattr(sys, "frozen", False):
        root = Path(__file__).resolve().parents[2]
        try:
            revision_result = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=3, check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            revision = revision_result.stdout.strip()
            status_result = subprocess.run(
                ["git", "-C", str(root), "status", "--porcelain"],
                capture_output=True, text=True, timeout=3, check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            dirty = bool(status_result.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            pass
    installed = _version("tolforge")
    declared = _source_package_version() if not installed else None
    return {
        "software": {"name": "TolForge", "version": installed or declared,
                     "version_basis": "installed_package" if installed else "source_package_declaration" if declared else "unavailable",
                     "source_revision": revision, "source_dirty": dirty,
                     "source_provenance_status": "available" if revision else "unavailable"},
        "solver": {"name": solver, "version": SOLVER_VERSION,
                   "implementation": _implementation_manifest()},
        "runtime": {"python": platform.python_version(), "implementation": platform.python_implementation(),
                    "numpy": _version("numpy"), "PySide6": _version("PySide6"),
                    "compas": _version("compas"), "compas_occ": _version("compas_occ"),
                    "platform": platform.platform(),
                    "frozen": bool(getattr(sys, "frozen", False))},
    }


def build_report_evidence(report_kind, input_snapshot, *, settings=None, units=None,
                          context=None, scope=(), solver=None, report_kind_version=1) -> ReportEvidence:
    """Capture all evidence once, at evaluation, with strict input identity.

    Source paths/descriptors live in context['sources']. Free-text references
    with no path stay visible with an unavailable digest. Plain API use has
    no fabricated project/study ID and explicitly unspecified units.
    """
    if not isinstance(report_kind, str) or not report_kind.strip():
        raise ValueError("Report kind must not be empty.")
    if type(report_kind_version) is not int or report_kind_version <= 0:
        raise ValueError("Report kind version must be a positive integer.")
    raw_context = dict(context or {})
    source_descriptors = raw_context.pop("sources", [])
    captured_context = _copy_json(raw_context)
    sources = [_source_evidence(item) for item in source_descriptors]
    captured_context.setdefault("project", None)
    captured_context.setdefault("study", None)
    snapshot = _copy_json({
        "inputs": input_snapshot, "settings": settings or {},
        "units": units if units is not None else {"status": "unspecified"},
        "context": captured_context, "source_evidence": sources, "scope": list(scope),
    })
    created = datetime.now(timezone.utc).isoformat()
    envelope = {
        "report_schema": REPORT_SCHEMA, "report_version": REPORT_VERSION,
        "evidence_version": EVIDENCE_VERSION, "report_kind": report_kind,
        "report_kind_version": report_kind_version,
        "report_id": str(uuid4()), "input_snapshot_id": str(uuid4()),
        "created_at": created, "result_evaluated_at": created,
        "input_digest": {"algorithm": "sha256", "canonicalization": "sorted-key-utf8-json-v1",
                         "value": input_digest(snapshot)},
        "input_snapshot": snapshot,
        "source_evidence_status": ("no_sources_supplied" if not sources else
                                   "complete" if all(item["hash_status"] == "available" for item in sources)
                                   else "partial_or_unavailable"),
        **_runtime_evidence(solver or report_kind),
    }
    return ReportEvidence(canonical_json(envelope))


def revise_report_evidence(evidence: ReportEvidence, *, settings, scope=None) -> ReportEvidence:
    """New identity for a reassessment, retaining its original source evidence."""
    previous = evidence.to_dict()
    snapshot = previous["input_snapshot"]
    snapshot["settings"] = _copy_json(settings)
    if scope is not None:
        snapshot["scope"] = _copy_json(list(scope))
    updated = dict(previous)
    updated.update(report_id=str(uuid4()), input_snapshot_id=str(uuid4()),
                   created_at=datetime.now(timezone.utc).isoformat(),
                   derived_from_report_id=previous["report_id"],
                   derivation="reassessed_existing_result", input_snapshot=snapshot)
    updated["input_digest"]["value"] = input_digest(snapshot)
    return ReportEvidence(canonical_json(updated))
