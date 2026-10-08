"""Release qualification must reject missing, substituted, and stale inputs."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def build_module():
    path = Path(__file__).resolve().parents[1] / "scripts/windows_build.py"
    spec = importlib.util.spec_from_file_location("tolforge_windows_build", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_conda_lock(tmp_path, records):
    prefix = tmp_path / "prefix"
    metadata = prefix / "conda-meta"
    metadata.mkdir(parents=True)
    for record in records:
        (metadata / f"{record['name']}.json").write_text(json.dumps(record), encoding="utf-8")
    lock = tmp_path / "native.conda.lock"
    lock.write_text("# platform: win-64\n@EXPLICIT\n" + "\n".join(
        f"https://conda.anaconda.org/conda-forge/win-64/{record['fn']}#{record['sha256']}"
        for record in records
    ) + "\n", encoding="utf-8")
    return prefix, lock


def test_explicit_conda_lock_requires_exact_archive_hashes(build_module, tmp_path):
    record = {"name": "pythonocc-core", "fn": "pythonocc-core-7.9.3.conda", "sha256": "a" * 64}
    prefix, lock = make_conda_lock(tmp_path, [record])
    build_module.assert_conda_lock(prefix, lock)
    record["sha256"] = "b" * 64
    (prefix / "conda-meta/pythonocc-core.json").write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(RuntimeError, match="hash mismatch=.*pythonocc-core"):
        build_module.assert_conda_lock(prefix, lock)


def test_prepare_embeds_hash_of_exact_native_manifest_bytes(build_module, tmp_path, monkeypatch):
    environment = tmp_path / ".github/environments"
    environment.mkdir(parents=True)
    for name in ("windows-release-py312.lock", "windows-cad-py312.lock", "native-cad-win-64.conda.lock"):
        (environment / name).write_text("# fixture lock\n", encoding="utf-8")
    monkeypatch.setattr(build_module, "assert_release_dependencies", lambda *_: {"compas": "2.15.1"})
    monkeypatch.setattr(build_module, "assert_conda_lock", lambda *_: None)
    monkeypatch.setattr(build_module, "native_dependencies", lambda *_: {"native_binaries": [], "extension_modules": []})
    monkeypatch.setattr(build_module, "source_provenance", lambda *_: {"source_files": [], "source_revision": "test"})
    output = tmp_path / "artifact"
    provenance = build_module.prepare(tmp_path, output, "cad")
    assert provenance["native_dependencies_sha256"] == build_module.sha256(output / "native-dependencies.json")
    metadata = json.loads((output / "tolforge-build.json").read_text())
    assert metadata["native_dependencies_sha256"] == provenance["native_dependencies_sha256"]


def test_release_environment_requires_pinned_python_patch_version(build_module, monkeypatch, tmp_path):
    environment = tmp_path / ".github/environments"
    environment.mkdir(parents=True)
    (environment / "python-version").write_text("3.12.13\n", encoding="utf-8")
    monkeypatch.setattr(build_module, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(build_module, "sys", SimpleNamespace(version_info=(3, 12, 12), maxsize=2**63 - 1))
    with pytest.raises(RuntimeError, match="expected Python 3.12.13, found 3.12.12"):
        build_module.assert_release_dependencies(tmp_path)


def test_explicit_conda_lock_rejects_extra_environment_packages(build_module, tmp_path):
    prefix, lock = make_conda_lock(tmp_path, [{"name": "python", "fn": "python.conda", "sha256": "a" * 64}])
    (prefix / "conda-meta/unpinned.json").write_text(json.dumps({"fn": "unpinned.conda", "sha256": "b" * 64}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="extra=.*unpinned"):
        build_module.assert_conda_lock(prefix, lock)


@pytest.mark.parametrize("entry", ["https://example.invalid/python.conda", "https://example.invalid/python.conda#" + "a" * 32])
def test_explicit_conda_lock_rejects_unhashed_or_md5_archives(build_module, tmp_path, entry):
    lock = tmp_path / "native.conda.lock"
    lock.write_text("@EXPLICIT\n" + entry + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="SHA256"):
        build_module.assert_conda_lock(tmp_path, lock)


def mock_source_git(module, monkeypatch, paths):
    def git(root, *args):
        if args[0] == "ls-files":
            return "\0".join(paths) + "\0"
        if args[0] == "rev-parse":
            return "a" * 40
        if args[0] == "branch":
            return "main"
        return " M core.py"
    monkeypatch.setattr(module, "git", git)


def test_source_gate_rejects_content_change_after_manifest(build_module, monkeypatch, tmp_path):
    source = tmp_path / "core.py"
    source.write_text("original", encoding="utf-8")
    mock_source_git(build_module, monkeypatch, ["core.py"])
    output = tmp_path / "artifact"
    output.mkdir()
    before = build_module.source_provenance(tmp_path)
    (output / "build-provenance.json").write_text(json.dumps(before), encoding="utf-8")
    build_module.verify_source(tmp_path, output)
    source.write_text("changed during packaging", encoding="utf-8")
    with pytest.raises(RuntimeError, match="changed while building"):
        build_module.verify_source(tmp_path, output)


def test_source_manifest_retains_deleted_file_identity(build_module, monkeypatch, tmp_path):
    mock_source_git(build_module, monkeypatch, ["deleted.py"])
    result = build_module.source_provenance(tmp_path)
    assert result["source_files"] == [{"path": "deleted.py", "deleted": True}]
    missing_hash = result["source_tree_sha256"]
    (tmp_path / "deleted.py").write_text("restored", encoding="utf-8")
    assert build_module.source_provenance(tmp_path)["source_tree_sha256"] != missing_hash


@pytest.fixture
def native_prefix(build_module, monkeypatch, tmp_path):
    prefix, _ = make_conda_lock(tmp_path, [{"name": "pythonocc-core", "version": "7.9.3", "fn": "occ.conda", "sha256": "a" * 64}])
    core = prefix / "Lib/site-packages/OCC/Core"
    core.mkdir(parents=True)
    (core.parent / "__init__.py").write_text("", encoding="utf-8")
    (core / "_BRep.pyd").write_bytes(b"test extension")
    library = prefix / "Library/bin"
    library.mkdir(parents=True)
    (library / "TKernel.dll").write_bytes(b"test CAD dependency")
    monkeypatch.setattr(build_module.importlib.util, "find_spec", lambda name: SimpleNamespace(origin=str(core.parent / "__init__.py")))
    monkeypatch.setattr(build_module.importlib.metadata, "version", lambda name: "1.5.0")
    direct_url = {"archive_info": {"hashes": {"sha256": "7ebcaedae2c27b284015521cb25efe8673807bef7257e5883559027631721656"}}}
    monkeypatch.setattr(build_module.importlib.metadata, "distribution", lambda name: SimpleNamespace(read_text=lambda file: json.dumps(direct_url)))
    imports = {"_BRep.pyd": [b"TKernel.dll"], "TKernel.dll": [b"KERNEL32.dll"]}

    class FakePE:
        def __init__(self, path, fast_load):
            self.DIRECTORY_ENTRY_IMPORT = [SimpleNamespace(dll=value) for value in imports[Path(path).name]]
        def parse_data_directories(self, directories):
            pass
        def close(self):
            pass
    monkeypatch.setitem(sys.modules, "pefile", SimpleNamespace(PE=FakePE, DIRECTORY_ENTRY={"IMAGE_DIRECTORY_ENTRY_IMPORT": 1, "IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT": 13}))
    return prefix, imports


def test_native_manifest_records_dll_closure_and_hashes(build_module, native_prefix):
    prefix, _ = native_prefix
    report = build_module.native_dependencies(prefix)
    assert [entry["bundle_path"] for entry in report["native_binaries"]] == ["TKernel.dll"]
    assert report["native_binaries"][0]["sha256"] == build_module.sha256(prefix / "Library/bin/TKernel.dll")
    assert report["system_dependencies"] == ["kernel32.dll"]
    assert report["extension_modules"][0]["path"] == "Lib/site-packages/OCC/Core/_BRep.pyd"


def test_native_manifest_rejects_older_workstation_occ(build_module, native_prefix):
    prefix, _ = native_prefix
    record_path = prefix / "conda-meta/pythonocc-core.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["version"] = "7.9.0"
    record_path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(RuntimeError, match="pythonocc-core 7.9.3"):
        build_module.native_dependencies(prefix)


def test_native_manifest_rejects_wrapper_from_different_source(build_module, native_prefix, monkeypatch):
    prefix, _ = native_prefix
    wrong_origin = {"archive_info": {"hashes": {"sha256": "b" * 64}}}
    monkeypatch.setattr(build_module.importlib.metadata, "distribution", lambda name: SimpleNamespace(read_text=lambda file: json.dumps(wrong_origin)))
    with pytest.raises(RuntimeError, match="origin does not match"):
        build_module.native_dependencies(prefix)


def test_native_manifest_rejects_missing_dll_even_if_workstation_path_has_it(build_module, native_prefix, monkeypatch, tmp_path):
    prefix, imports = native_prefix
    imports["TKernel.dll"] = [b"workstation.dll"]
    workstation = tmp_path / "workstation"
    workstation.mkdir()
    (workstation / "workstation.dll").write_bytes(b"unqualified workstation dependency")
    monkeypatch.setenv("PATH", str(workstation))
    monkeypatch.setenv("TOLFORGE_DLL_DIRS", str(workstation))
    with pytest.raises(RuntimeError, match="workstation.dll.*missing from the locked prefix"):
        build_module.native_dependencies(prefix)


def test_artifact_hashes_include_nested_step_fixtures(build_module, tmp_path):
    fixture = tmp_path / "packaged-smoke.cad-fixtures/cylinder.step"
    fixture.parent.mkdir()
    fixture.write_text("STEP fixture", encoding="utf-8")
    (tmp_path / "TolForge.exe").write_bytes(b"executable")
    build_module.finalize(tmp_path, "cad")
    report = json.loads((tmp_path / "SHA256.json").read_text(encoding="utf-8"))
    assert report["profile"] == "cad"
    assert {entry["path"] for entry in report["files"]} == {"TolForge.exe", "packaged-smoke.cad-fixtures/cylinder.step"}
    assert all(len(entry["sha256"]) == 64 for entry in report["files"])


def test_scalar_venv_records_and_verifies_locked_base_interpreter(build_module, monkeypatch, tmp_path):
    prefix, explicit = make_conda_lock(tmp_path, [{"name": "python", "version": "3.12.15", "fn": "python.conda", "sha256": "a" * 64}])
    root = tmp_path / "source"
    environment = root / ".github/environments"
    environment.mkdir(parents=True)
    (environment / "scalar-win-64.conda.lock").write_text(explicit.read_text(encoding="utf-8"), encoding="utf-8")
    (environment / "windows-release-py312.lock").write_text("# hash-locked pip baseline", encoding="utf-8")
    monkeypatch.setattr(build_module, "sys", SimpleNamespace(base_prefix=str(prefix), prefix=str(tmp_path / "venv"), version="3.12.15", version_info=(3, 12, 15), implementation=SimpleNamespace(name="cpython")))
    monkeypatch.setattr(build_module, "assert_release_dependencies", lambda root: {"numpy": "2.1.3"})
    monkeypatch.setattr(build_module, "source_provenance", lambda root: {"source_revision": "a" * 40, "source_tree_sha256": "b" * 64, "source_files": []})
    output = tmp_path / "artifact"
    provenance = build_module.prepare(root, output, "scalar")
    runtime = json.loads((output / "native-conda-runtime.json").read_text(encoding="utf-8"))
    assert runtime["packages"][0]["name"] == "python"
    assert provenance["conda_runtime_manifest_sha256"] == build_module.sha256(output / "native-conda-runtime.json")
    assert len(provenance["dependency_locks"]) == 2
    (prefix / "conda-meta/python.json").write_text(json.dumps({"fn": "python.conda", "sha256": "c" * 64}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="hash mismatch"):
        build_module.prepare(root, output, "scalar")
