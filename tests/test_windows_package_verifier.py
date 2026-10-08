"""Reject damaged or misidentified distributions before launching their executable."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows target verifier")
VERIFIER = Path(__file__).resolve().parents[1] / "scripts" / "verify_windows_package.ps1"


def _manifest(package, entries, profile="scalar"):
    files = []
    for name in entries:
        path = package / name
        files.append({"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    (package / "SHA256.json").write_text(json.dumps({"schema_version": 1, "profile": profile, "files": files}))


def _verify(package, output, profile="scalar"):
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        pytest.fail("Windows package verification requires the platform's PowerShell")
    result = subprocess.run(
        [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(VERIFIER),
         "-PackageDirectory", str(package), "-Profile", profile, "-OutputDirectory", str(output)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0, result.stdout
    report = json.loads((output / "target-qualification.json").read_text(encoding="utf-8-sig"))
    assert report["status"] == "failed"
    assert report["verifier_sha256"] == hashlib.sha256(VERIFIER.read_bytes()).hexdigest()
    assert report["smoke"] is None
    assert not (output / "installed").exists(), "Invalid artifacts must never reach executable launch"
    return report["error"]


def test_corrupted_executable_is_rejected_before_install(tmp_path):
    package = tmp_path / "package"
    package.mkdir()
    executable = package / "TolForge.exe"
    executable.write_bytes(b"original artifact")
    _manifest(package, ["TolForge.exe"])
    executable.write_bytes(b"modified artifact")
    assert "hash mismatch" in _verify(package, tmp_path / "check").lower()


def test_manifest_cannot_hash_files_outside_the_package(tmp_path):
    package = tmp_path / "package"
    package.mkdir()
    (tmp_path / "outside.exe").write_bytes(b"unrelated")
    _manifest(package, ["../outside.exe"])
    assert "escapes" in _verify(package, tmp_path / "check")


def test_cad_package_cannot_be_qualified_as_scalar(tmp_path):
    package = tmp_path / "package"
    package.mkdir()
    (package / "TolForge.exe").write_bytes(b"original artifact")
    _manifest(package, ["TolForge.exe"], profile="cad")
    assert "incorrect profile" in _verify(package, tmp_path / "check")


def test_missing_hashed_build_evidence_is_rejected(tmp_path):
    package = tmp_path / "package"
    package.mkdir()
    (package / "TolForge.exe").write_bytes(b"original artifact")
    _manifest(package, ["TolForge.exe"])
    assert "omits required evidence" in _verify(package, tmp_path / "check")


def test_interpreter_evidence_must_match_embedded_build_identity(tmp_path):
    package = tmp_path / "package"
    package.mkdir()
    entries = ["TolForge.exe", "tolforge-build.json", "build-provenance.json", "packaged-smoke.json",
               "pip-freeze.txt", "windows-release-py312.lock", "native-conda-runtime.json", "conda-explicit-win-64.txt"]
    for name in entries:
        (package / name).write_text("substituted evidence", encoding="utf-8")
    metadata = {"profile": "scalar", "conda_runtime_manifest_sha256": "a" * 64}
    (package / "tolforge-build.json").write_text(json.dumps(metadata), encoding="utf-8")
    _manifest(package, entries)
    assert "interpreter manifest does not match" in _verify(package, tmp_path / "check")


def test_native_evidence_must_match_embedded_build_identity(tmp_path):
    package = tmp_path / "package"
    package.mkdir()
    entries = ["TolForge.exe", "tolforge-build.json", "build-provenance.json", "packaged-smoke.json",
               "pip-freeze.txt", "windows-release-py312.lock", "native-dependencies.json",
               "windows-cad-py312.lock", "conda-explicit-win-64.txt"]
    for name in entries:
        (package / name).write_text("substituted evidence", encoding="utf-8")
    metadata = {"profile": "cad", "native_dependencies_sha256": "a" * 64}
    (package / "tolforge-build.json").write_text(json.dumps(metadata), encoding="utf-8")
    _manifest(package, entries, profile="cad")
    assert "Native dependency manifest does not match" in _verify(package, tmp_path / "check", profile="cad")
