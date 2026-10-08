import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

from gui import runtime

_SOURCE_RUNTIME_CONFIG_PATH = runtime.source_native_runtime_config_path


@pytest.fixture(autouse=True)
def isolate_checkout_runtime_configuration(monkeypatch):
    """Optional machine-local checkout files must not affect test defaults."""
    monkeypatch.setattr(runtime, "source_native_runtime_config_path", lambda: None)


def test_local_runtime_config_is_used_without_environment_override(tmp_path, monkeypatch):
    config = tmp_path / "runtime.json"
    config.write_text(json.dumps({"dll_directories": [str(tmp_path)]}), encoding="utf-8")
    monkeypatch.setattr(runtime, "native_runtime_config_path", lambda: config)
    monkeypatch.delenv("TOLFORGE_DLL_DIRS", raising=False)
    assert runtime._configured_dll_directories() == [str(tmp_path)]
    monkeypatch.setenv("TOLFORGE_DLL_DIRS", str(tmp_path / "override"))
    assert runtime._configured_dll_directories() == [str(tmp_path / "override")]


def test_malformed_local_config_does_not_prevent_startup(tmp_path, monkeypatch):
    config = tmp_path / "runtime.json"
    config.write_text('{"dll_directories": "wrong type"}', encoding="utf-8")
    monkeypatch.setattr(runtime, "native_runtime_config_path", lambda: config)
    monkeypatch.delenv("TOLFORGE_DLL_DIRS", raising=False)
    with pytest.warns(RuntimeWarning, match="Cannot read"):
        assert runtime._configured_dll_directories() == []


def test_failed_backend_check_preserves_renderer_and_reports_details(monkeypatch):
    from types import SimpleNamespace
    from gui import step_viewer_mixin as viewer
    renderer = object()
    messages = []
    state = SimpleNamespace(_step_preview_renderer=renderer,
                            step_status_label=SimpleNamespace(setText=lambda text: None))
    monkeypatch.setattr(viewer.QFileDialog, "getOpenFileName", lambda *args: ("part.step", ""))
    monkeypatch.setattr(viewer, "detect_step_backend", lambda: (None, "Missing native reader DLL"))
    monkeypatch.setattr(viewer.QMessageBox, "warning", lambda *args: messages.append(args[-1]))
    viewer.StepViewerMixin.load_step_file(state)
    assert state._step_preview_renderer is renderer
    assert messages == ["Missing native reader DLL"]


def test_cad_reader_is_checked_before_native_file_dialog(monkeypatch):
    from types import SimpleNamespace
    from gui import step_viewer_mixin as viewer
    events = []
    state = SimpleNamespace(step_status_label=SimpleNamespace(setText=lambda text: None),
                            _start_step_load=lambda path: events.append(("load", path)))
    def backend():
        events.append("backend")
        return "compas_occ", "ready"
    def dialog(*args):
        assert events == ["backend"]
        events.append("dialog")
        return "part.step", ""
    monkeypatch.setattr(viewer, "detect_step_backend", backend)
    monkeypatch.setattr(viewer.QFileDialog, "getOpenFileName", dialog)
    viewer.StepViewerMixin.load_step_file(state)
    assert events == ["backend", "dialog", ("load", "part.step")]


@pytest.mark.skipif(os.name != "nt", reason="Windows DLL registration")
def test_explicit_runtime_paths_remain_registered_and_are_idempotent(tmp_path, monkeypatch):
    native = tmp_path / "cad"
    native.mkdir()
    conda_bin = tmp_path / "conda" / "Library" / "bin"
    conda_bin.mkdir(parents=True)
    monkeypatch.setenv("TOLFORGE_DLL_DIRS", f'"{native}"{os.pathsep}{native}')
    monkeypatch.setenv("CONDA_PREFIX", str(tmp_path / "conda"))
    monkeypatch.setattr(runtime, "_DLL_HANDLES", {})
    handles = []

    def register(path):
        handle = object()
        handles.append((path, handle))
        return handle

    monkeypatch.setattr(os, "add_dll_directory", register)
    first = runtime.configure_native_runtime()
    second = runtime.configure_native_runtime()
    assert first == second == (str(native), str(conda_bin))
    assert len(handles) == 2
    assert list(runtime._DLL_HANDLES.values()) == [value for _, value in handles]


@pytest.mark.skipif(os.name != "nt", reason="Windows DLL registration")
def test_invalid_runtime_paths_do_not_prevent_application_start(tmp_path, monkeypatch):
    monkeypatch.setenv("TOLFORGE_DLL_DIRS", f"relative{os.pathsep}{tmp_path / 'missing'}")
    monkeypatch.delenv("CONDA_PREFIX", raising=False)
    monkeypatch.setattr(runtime, "_DLL_HANDLES", {})
    with pytest.warns(RuntimeWarning) as caught:
        assert runtime.configure_native_runtime() == ()
    assert len(caught) == 2


def test_backend_detection_checks_native_step_imports(monkeypatch):
    from gui import step_renderer

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(step_renderer, "write_native_runtime_diagnostics", lambda error: None)

    def broken_import(name):
        raise ImportError("missing OCCT DLL")

    monkeypatch.setattr(step_renderer.importlib, "import_module", broken_import)
    backend, message = step_renderer.detect_step_backend()
    assert backend is None
    assert "missing OCCT DLL" in message
    assert "TOLFORGE_DLL_DIRS" in message


def test_packaging_smoke_checks_real_imports_calculation_and_bundled_icons(tmp_path):
    report = tmp_path / "smoke.json"
    assert runtime.run_packaged_smoke_check(report) == 0
    result = json.loads(report.read_text(encoding="utf-8"))
    assert result["status"] == "ok"
    assert len(result["checks"]) == 3
    assert result["cad_qualification"] == "not exercised"


def test_native_diagnostics_identifies_config_source_registered_paths_and_modules(tmp_path, monkeypatch):
    config = tmp_path / "runtime.json"
    config.write_text(json.dumps({"dll_directories": [str(tmp_path / "configured")]}), encoding="utf-8")
    monkeypatch.setattr(runtime, "native_runtime_config_path", lambda: config)
    monkeypatch.delenv("TOLFORGE_DLL_DIRS", raising=False)
    monkeypatch.delenv("CONDA_PREFIX", raising=False)
    registered = str(tmp_path / "registered")
    monkeypatch.setattr(runtime, "_DLL_HANDLES", {registered: object()})
    modules = {"TKernel.dll": str(tmp_path / "loaded" / "TKernel.dll")}
    monkeypatch.setattr(runtime, "_loaded_native_module_paths", lambda: modules)
    monkeypatch.setenv("UNRELATED_SECRET", "must-not-be-recorded")

    report = runtime.native_runtime_diagnostics()
    assert report["runtime_config_source"] == "file"
    assert report["runtime_config_path"] == str(config)
    assert report["active_runtime_config_path"] == str(config)
    assert report["runtime_config_exists"] is True
    assert report["configured_dll_directories"] == [str(tmp_path / "configured")]
    assert report["registered_dll_directories"] == [registered]
    assert report["loaded_native_modules"] == modules
    assert report["python_executable"] == sys.executable
    assert report["python_version"] == sys.version.split()[0]
    assert report["runtime_module_path"] == str(Path(runtime.__file__).resolve())
    assert report["conda_prefix"] is None
    assert "must-not-be-recorded" not in json.dumps(report)
    assert "PATH" not in report


def test_native_diagnostics_honors_environment_override_and_conda_without_registering(tmp_path, monkeypatch):
    config = tmp_path / "runtime.json"
    config.write_text(json.dumps({"dll_directories": ["ignored-file-setting"]}), encoding="utf-8")
    monkeypatch.setattr(runtime, "native_runtime_config_path", lambda: config)
    explicit = tmp_path / "override"
    monkeypatch.setenv("TOLFORGE_DLL_DIRS", f'"{explicit}"')
    conda_prefix = tmp_path / "conda"
    conda_bin = conda_prefix / "Library" / "bin"
    conda_bin.mkdir(parents=True)
    monkeypatch.setenv("CONDA_PREFIX", str(conda_prefix))
    monkeypatch.setattr(runtime, "_DLL_HANDLES", {})
    monkeypatch.setattr(runtime, "_loaded_native_module_paths", lambda: {})

    report = runtime.native_runtime_diagnostics()
    assert report["runtime_config_source"] == "environment"
    assert report["active_runtime_config_path"] is None
    assert report["configured_dll_directories"] == [str(explicit), str(conda_bin)]
    assert report["registered_dll_directories"] == []
    assert report["conda_prefix"] == str(conda_prefix)
    assert runtime._DLL_HANDLES == {}


def test_native_diagnostics_reports_no_optional_config_and_tolerates_malformed_file(tmp_path, monkeypatch):
    config = tmp_path / "runtime.json"
    monkeypatch.setattr(runtime, "native_runtime_config_path", lambda: config)
    monkeypatch.delenv("TOLFORGE_DLL_DIRS", raising=False)
    monkeypatch.delenv("CONDA_PREFIX", raising=False)
    monkeypatch.setattr(runtime, "_DLL_HANDLES", {})
    monkeypatch.setattr(runtime, "_loaded_native_module_paths", lambda: {})
    report = runtime.native_runtime_diagnostics()
    assert report["runtime_config_source"] == "none"
    assert report["active_runtime_config_path"] is None
    assert report["runtime_config_exists"] is False
    assert report["configured_dll_directories"] == []
    config.write_text('{"dll_directories": "wrong type"}', encoding="utf-8")
    report = runtime.native_runtime_diagnostics()
    assert report["runtime_config_source"] == "file"
    assert report["configured_dll_directories"] == []


def test_native_diagnostic_writer_commits_complete_report_to_per_user_location(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("TOLFORGE_DLL_DIRS", raising=False)
    monkeypatch.delenv("CONDA_PREFIX", raising=False)
    monkeypatch.setattr(runtime, "_DLL_HANDLES", {})
    monkeypatch.setattr(runtime, "_loaded_native_module_paths", lambda: {})
    destination = tmp_path / "TolForge" / "native-runtime-diagnostics.json"
    error = ImportError("dependent native DLL not found")

    assert runtime.write_native_runtime_diagnostics(error) == destination
    report = json.loads(destination.read_text(encoding="utf-8"))
    assert report["error"] == "ImportError: dependent native DLL not found"
    assert report["runtime_config_path"] == str(tmp_path / "TolForge" / "runtime.json")
    assert report["python_executable"] == sys.executable
    assert list(destination.parent.glob(".native-runtime-diagnostics-*.tmp")) == []


def test_native_diagnostic_replace_failure_preserves_prior_report_and_original_error(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(runtime, "_loaded_native_module_paths", lambda: {})
    destination = tmp_path / "TolForge" / "native-runtime-diagnostics.json"
    destination.parent.mkdir()
    destination.write_text('{"prior": true}', encoding="utf-8")
    previous = destination.read_bytes()
    monkeypatch.setattr(runtime.os, "replace", lambda *args: (_ for _ in ()).throw(PermissionError("report locked")))
    original = ImportError("original missing OCCT dependency")

    try:
        raise original
    except ImportError as caught:
        assert runtime.write_native_runtime_diagnostics(caught) is None
        assert caught is original
        assert str(caught) == "original missing OCCT dependency"
    assert destination.read_bytes() == previous
    assert list(destination.parent.glob(".native-runtime-diagnostics-*.tmp")) == []


def test_native_diagnostic_unwritable_directory_returns_none(tmp_path, monkeypatch):
    blocked_parent = tmp_path / "blocked"
    blocked_parent.write_text("A file cannot be a report directory.", encoding="utf-8")
    monkeypatch.setattr(runtime, "native_runtime_config_path", lambda: blocked_parent / "runtime.json")
    monkeypatch.setattr(runtime, "_loaded_native_module_paths", lambda: {})
    assert runtime.write_native_runtime_diagnostics(ImportError("original")) is None
    assert blocked_parent.read_text(encoding="utf-8") == "A file cannot be a report directory."


def test_source_runtime_config_path_follows_own_checkout_and_is_excluded_when_frozen(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "source_native_runtime_config_path", _SOURCE_RUNTIME_CONFIG_PATH)
    monkeypatch.setattr(runtime, "__file__", str(tmp_path / "Code" / "gui" / "runtime.py"))
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert runtime.source_native_runtime_config_path() == tmp_path / ".tolforge" / "runtime.json"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert runtime.source_native_runtime_config_path() is None


def test_source_runtime_file_is_used_only_without_environment_or_per_user_config(tmp_path, monkeypatch):
    user_config = tmp_path / "user" / "runtime.json"
    source_config = tmp_path / ".tolforge" / "runtime.json"
    source_config.parent.mkdir()
    source_config.write_text(json.dumps({"dll_directories": ["source-native"]}), encoding="utf-8")
    monkeypatch.setattr(runtime, "native_runtime_config_path", lambda: user_config)
    monkeypatch.setattr(runtime, "source_native_runtime_config_path", lambda: source_config)
    monkeypatch.delenv("TOLFORGE_DLL_DIRS", raising=False)
    monkeypatch.delenv("CONDA_PREFIX", raising=False)
    monkeypatch.setattr(runtime, "_DLL_HANDLES", {})
    monkeypatch.setattr(runtime, "_loaded_native_module_paths", lambda: {})

    assert runtime._configured_dll_directories() == ["source-native"]
    report = runtime.native_runtime_diagnostics()
    assert report["runtime_config_source"] == "source_file"
    assert report["runtime_config_path"] == str(user_config)
    assert report["runtime_config_exists"] is False
    assert report["active_runtime_config_path"] == str(source_config)
    assert report["configured_dll_directories"] == ["source-native"]
    assert not user_config.exists()

    user_config.parent.mkdir()
    user_config.write_text(json.dumps({"dll_directories": ["user-native"]}), encoding="utf-8")
    assert runtime._configured_dll_directories() == ["user-native"]
    report = runtime.native_runtime_diagnostics()
    assert report["runtime_config_source"] == "file"
    assert report["active_runtime_config_path"] == str(user_config)

    monkeypatch.setenv("TOLFORGE_DLL_DIRS", "environment-native")
    assert runtime._configured_dll_directories() == ["environment-native"]
    report = runtime.native_runtime_diagnostics()
    assert report["runtime_config_source"] == "environment"
    assert report["active_runtime_config_path"] is None


def test_malformed_per_user_file_keeps_precedence_over_source_fallback(tmp_path, monkeypatch):
    user_config = tmp_path / "runtime.json"
    source_config = tmp_path / "source-runtime.json"
    user_config.write_text('{"dll_directories": "invalid"}', encoding="utf-8")
    source_config.write_text(json.dumps({"dll_directories": ["source-native"]}), encoding="utf-8")
    monkeypatch.setattr(runtime, "native_runtime_config_path", lambda: user_config)
    monkeypatch.setattr(runtime, "source_native_runtime_config_path", lambda: source_config)
    monkeypatch.delenv("TOLFORGE_DLL_DIRS", raising=False)
    with pytest.warns(RuntimeWarning, match="Cannot read"):
        assert runtime._configured_dll_directories() == []
    assert runtime.native_runtime_diagnostics()["runtime_config_source"] == "file"


def test_frozen_runtime_never_uses_source_file_even_if_checkout_file_exists(tmp_path, monkeypatch):
    source_config = tmp_path / ".tolforge" / "runtime.json"
    source_config.parent.mkdir()
    source_config.write_text(json.dumps({"dll_directories": ["source-native"]}), encoding="utf-8")
    monkeypatch.setattr(runtime, "source_native_runtime_config_path", _SOURCE_RUNTIME_CONFIG_PATH)
    monkeypatch.setattr(runtime, "__file__", str(tmp_path / "Code" / "gui" / "runtime.py"))
    monkeypatch.setattr(runtime, "native_runtime_config_path", lambda: tmp_path / "user-runtime.json")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.delenv("TOLFORGE_DLL_DIRS", raising=False)
    monkeypatch.delenv("CONDA_PREFIX", raising=False)
    monkeypatch.setattr(runtime, "_DLL_HANDLES", {})
    monkeypatch.setattr(runtime, "_loaded_native_module_paths", lambda: {})
    assert runtime._configured_dll_directories() == [str(tmp_path)]
    report = runtime.native_runtime_diagnostics()
    assert report["runtime_config_source"] == "bundle"
    assert report["active_runtime_config_path"] is None


@pytest.mark.skipif(os.name != "nt", reason="Windows DLL registration")
def test_frozen_runtime_ignores_workstation_config_environment_and_conda(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    bundled_cad = bundle / "OCC" / "Core"
    bundled_cad.mkdir(parents=True)
    external = tmp_path / "external"
    external.mkdir()
    config = tmp_path / "runtime.json"
    config.write_text(json.dumps({"dll_directories": [str(external)]}), encoding="utf-8")
    conda_bin = external / "Library" / "bin"
    conda_bin.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setenv("TOLFORGE_DLL_DIRS", str(external))
    monkeypatch.setenv("CONDA_PREFIX", str(external))
    monkeypatch.setenv("OCCT_ESSENTIALS_ROOT", str(external))
    monkeypatch.setattr(runtime, "native_runtime_config_path", lambda: config)
    monkeypatch.setattr(runtime, "_DLL_HANDLES", {})
    monkeypatch.setattr(runtime, "_loaded_native_module_paths", lambda: {})
    registered = []
    monkeypatch.setattr(os, "add_dll_directory", lambda path: registered.append(path) or object())
    assert runtime.configure_native_runtime() == (str(bundle), str(bundled_cad))
    assert registered == [str(bundle), str(bundled_cad)]
    report = runtime.native_runtime_diagnostics()
    assert report["runtime_config_source"] == "bundle"
    assert report["active_runtime_config_path"] is None
    assert report["conda_prefix"] is None
    assert report["configured_dll_directories"] == registered
    assert "OCCT_ESSENTIALS_ROOT" not in os.environ


def test_expected_profile_cannot_qualify_a_source_interpreter(tmp_path, monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    report = tmp_path / "qualification.json"
    assert runtime.run_packaged_smoke_check(report, expected_profile="scalar") == 1
    result = json.loads(report.read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert "requires a frozen executable" in result["error"]
    assert result["checks"] == []


@pytest.mark.parametrize("actual,expected,cad,error", [
    ("scalar", "cad", True, "Expected cad package"),
    ("cad", "scalar", False, "Expected scalar package"),
    ("scalar", "scalar", True, "CAD self-check requires"),
    ("cad", "cad", False, "must exercise its STEP backend"),
    ("unknown", "scalar", False, "no valid package profile"),
])
def test_frozen_profile_validation_fails_closed(tmp_path, monkeypatch, actual, expected, cad, error):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    (tmp_path / "tolforge-build.json").write_text(json.dumps({"profile": actual}), encoding="utf-8")
    with pytest.raises(RuntimeError, match=error):
        runtime._check_frozen_profile(expected, cad)


def test_scalar_profile_rejects_accidental_cad_packages(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    (tmp_path / "tolforge-build.json").write_text('{"profile":"scalar"}', encoding="utf-8")
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object() if name == "OCC" else None)
    with pytest.raises(RuntimeError, match="unexpectedly exposes"):
        runtime._check_frozen_profile("scalar", False)


def test_frozen_native_dependency_evidence_preserves_origins_and_hashes(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    windows = tmp_path / "Windows"
    (windows / "System32").mkdir(parents=True)
    native = bundle / "TKBRep.dll"
    native.write_bytes(b"bundled CAD")
    system = windows / "System32" / "VCRUNTIME140.dll"
    system.write_bytes(b"system runtime")
    outside = tmp_path / "workstation.dll"
    outside.write_bytes(b"external dependency")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setenv("WINDIR", str(windows))
    monkeypatch.setattr(runtime, "_qualification_native_module_paths", lambda: {
        "native": str(native), "system": str(system), "outside": str(outside),
    })
    evidence = runtime._native_dependency_evidence()
    assert {item["name"]: item["origin"] for item in evidence} == {
        native.name: "bundle", system.name: "windows", outside.name: "external",
    }
    assert all(item["sha256"] == runtime._sha256(item["path"]) for item in evidence)
    with pytest.raises(RuntimeError, match="borrowed a native dependency"):
        runtime._validate_frozen_dependencies(evidence)
    runtime._validate_frozen_dependencies([item for item in evidence if item["origin"] != "external"])
    with pytest.raises(RuntimeError, match="CAD/Qt dependency is not bundled"):
        runtime._validate_frozen_dependencies([{"name": "TKMath.dll", "path": "system/TKMath.dll", "origin": "windows"}])


@pytest.mark.parametrize("platform", ["offscreen", "offscreen:foo", "minimal", "minimalegl", "vnc"])
def test_viewport_qualification_rejects_headless_platforms(tmp_path, monkeypatch, platform):
    monkeypatch.setenv("QT_QPA_PLATFORM", platform)
    with pytest.raises(RuntimeError, match="offscreen/minimal"):
        runtime._qualify_native_viewport(None, tmp_path / "viewport.png")


@pytest.mark.native_cad
def test_native_qualification_round_trips_cylinder_box_and_cone(tmp_path, native_cad_backend):
    records, loaded = runtime._cad_fixture_checks(tmp_path)
    assert [record["fixture"] for record in records] == ["cylinder", "box", "cone"]
    assert [record["faces"] for record in records] == [3, 6, 3]
    assert records[0]["surface_kinds"] == ["cylinder", "plane"]
    assert records[1]["surface_kinds"] == ["plane"]
    assert records[2]["surface_kinds"] == ["other", "plane"]
    assert all(record["status"] == "ok" and len(record["sha256"]) == 64 for record in records)
    assert loaded.face_surfaces[0]["kind"] in ("cylinder", "plane")


def test_versions_use_embedded_distribution_evidence_when_metadata_is_unavailable(monkeypatch):
    from types import SimpleNamespace
    import importlib.metadata

    monkeypatch.setitem(sys.modules, "compas_occ", SimpleNamespace(__file__="bundle/compas_occ/__init__.py"))
    monkeypatch.setattr(importlib.metadata, "version", lambda name: (_ for _ in ()).throw(
        importlib.metadata.PackageNotFoundError(name)))
    packages = runtime._package_versions({"packages": {"compas_occ": "1.5.0"}})
    assert packages["compas_occ"] == {"version": "1.5.0", "module_path": "bundle/compas_occ/__init__.py"}


def test_frozen_cad_bundle_must_match_the_hashed_build_dependency_closure(tmp_path, monkeypatch):
    dll = tmp_path / "TKernel.dll"
    dll.write_bytes(b"exact native DLL")
    extension = tmp_path / "OCC" / "Core" / "_BRep.pyd"
    extension.parent.mkdir(parents=True)
    extension.write_bytes(b"exact native extension")
    manifest_path = tmp_path / "native-dependencies.json"
    manifest_path.write_text(json.dumps({
        "native_binaries": [{"bundle_path": dll.name, "sha256": runtime._sha256(dll)}],
        "extension_modules": [{"path": "Lib/site-packages/OCC/Core/_BRep.pyd", "sha256": runtime._sha256(extension)}],
    }), encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    metadata = {"profile": "cad", "native_dependencies_sha256": runtime._sha256(manifest_path)}
    assert runtime._verify_native_bundle(metadata)["native_files_verified"] == 2
    extension.write_bytes(b"substituted external runtime")
    with pytest.raises(RuntimeError, match="differs from the recorded build environment"):
        runtime._verify_native_bundle(metadata)
    manifest_path.write_text('{}', encoding="utf-8")
    with pytest.raises(RuntimeError, match="does not match build provenance"):
        runtime._verify_native_bundle(metadata)


@pytest.mark.skipif(os.name != "nt", reason="Windows ICU loader selection")
def test_system_icu_preload_uses_authoritative_system_paths_and_retains_handles(tmp_path, monkeypatch):
    import ctypes

    system_directory = tmp_path / "System32"
    system_directory.mkdir()
    for name in ("icuuc.dll", "icuin.dll"):
        (system_directory / name).write_bytes(b"system ICU")
    monkeypatch.setattr(runtime, "_windows_system_directory", lambda: system_directory)
    monkeypatch.setattr(runtime, "_WINDOWS_ICU_HANDLES", {})
    loaded = []
    monkeypatch.setattr(ctypes, "WinDLL", lambda path, **kwargs: loaded.append((path, kwargs)) or object())
    runtime._preload_windows_icu()
    runtime._preload_windows_icu()
    assert [path for path, _ in loaded] == [str(system_directory / name) for name in ("icuuc.dll", "icuin.dll")]
    assert all(options == {"winmode": 0x800} for _, options in loaded)
    assert len(runtime._WINDOWS_ICU_HANDLES) == 2


@pytest.mark.skipif(os.name != "nt", reason="Windows ICU loader selection")
@pytest.mark.parametrize("conda,frozen,expected", [(False, False, 0), (True, False, 1), (False, True, 1)])
def test_icu_is_selected_before_dll_registration_only_for_conda_or_frozen(tmp_path, monkeypatch, conda, frozen, expected):
    events = []
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(runtime, "_preload_windows_icu", lambda: events.append("system ICU"))
    monkeypatch.setattr(runtime, "_configured_dll_directories", lambda: [str(tmp_path)])
    monkeypatch.setattr(runtime, "_DLL_HANDLES", {})
    monkeypatch.setattr(os, "add_dll_directory", lambda path: events.append("register DLL directory") or object())
    if conda:
        monkeypatch.setenv("CONDA_PREFIX", str(tmp_path))
    else:
        monkeypatch.delenv("CONDA_PREFIX", raising=False)
    runtime.configure_native_runtime()
    assert events.count("system ICU") == expected
    assert events[-1] == "register DLL directory"


@pytest.mark.skipif(os.name != "nt", reason="Windows Defender trust exception")
def test_verified_defender_injection_is_recorded_separately_from_external_dependencies(tmp_path, monkeypatch):
    program_data = tmp_path / "ProgramData"
    defender = program_data / "Microsoft" / "Windows Defender" / "Platform" / "4.18.26080.4-0" / "MpOAV.dll"
    defender.parent.mkdir(parents=True)
    defender.write_bytes(b"verified Defender component")
    external = tmp_path / "TKMath.dll"
    external.write_bytes(b"external CAD replacement")
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(runtime, "_windows_program_data_directory", lambda: program_data)
    signer = {"status": "valid", "publisher": "Microsoft Windows", "organization": "Microsoft Corporation",
              "verification": "WinVerifyTrust embedded signature; offline cache only"}
    monkeypatch.setattr(runtime, "_offline_authenticode_signer", lambda path: signer)
    monkeypatch.setattr(runtime, "_qualification_native_module_paths", lambda: {
        "defender": str(defender), "external CAD": str(external),
    })
    evidence = runtime._native_dependency_evidence()
    verified = next(item for item in evidence if item["name"] == "MpOAV.dll")
    assert verified["origin"] == "windows-security"
    assert verified["authenticode"] == signer
    assert verified["sha256"] == runtime._sha256(defender)
    runtime._validate_frozen_dependencies([verified])
    with pytest.raises(RuntimeError, match="borrowed a native dependency"):
        runtime._validate_frozen_dependencies(evidence)


@pytest.mark.skipif(os.name != "nt", reason="Windows Defender trust exception")
@pytest.mark.parametrize("signature", [None,
    {"status": "valid", "publisher": "Other publisher", "organization": "Microsoft Corporation"},
    {"status": "valid", "publisher": "Microsoft Windows", "organization": "Other organization"},
    {"status": "invalid", "publisher": "Microsoft Windows", "organization": "Microsoft Corporation"},
])
def test_defender_exception_rejects_unsigned_invalid_or_other_publishers(tmp_path, monkeypatch, signature):
    defender = tmp_path / "Microsoft" / "Windows Defender" / "Platform" / "4.18.26080.4-0" / "MpOAV.dll"
    monkeypatch.setattr(runtime, "_windows_program_data_directory", lambda: tmp_path)
    monkeypatch.setattr(runtime, "_offline_authenticode_signer", lambda path: signature)
    assert runtime._windows_security_component_evidence(defender) is None


@pytest.mark.skipif(os.name != "nt", reason="Windows Defender trust exception")
@pytest.mark.parametrize("relative", ["Other/MpOAV.dll", "Microsoft/Windows Defender/Platform/bad/MpOAV.dll",
    "Microsoft/Windows Defender/Platform/4.18.26080.4-0/Qt6Core.dll",
    "Microsoft/Windows Defender/Platform/4.18.26080.4-0/subdirectory/MpOAV.dll",
])
def test_defender_exception_is_narrow_to_known_platform_path_and_filename(tmp_path, monkeypatch, relative):
    monkeypatch.setattr(runtime, "_windows_program_data_directory", lambda: tmp_path)
    def unexpected_signature_check(path):
        pytest.fail("An unrelated DLL must never receive the Defender exception")
    monkeypatch.setattr(runtime, "_offline_authenticode_signer", unexpected_signature_check)
    assert runtime._windows_security_component_evidence(tmp_path / relative) is None


@pytest.mark.skipif(os.name != "nt", reason="Windows Authenticode verification")
def test_offline_authenticode_verification_rejects_an_unsigned_file(tmp_path):
    unsigned = tmp_path / "MpOAV.dll"
    unsigned.write_bytes(b"unsigned replacement")
    assert runtime._offline_authenticode_signer(unsigned) is None


@pytest.mark.native_cad
def test_cad_self_check_preserves_hashed_fixture_evidence(tmp_path, native_cad_backend):
    report_path = tmp_path / "cad.json"
    assert runtime.run_packaged_smoke_check(report_path, include_cad=True) == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["cad_qualification"].startswith("STEP round-trips passed")
    assert report["viewport"]["status"] == "not exercised"
    for record in report["cad_fixtures"]:
        fixture = report_path.parent / record["file"]
        assert fixture.is_file()
        assert not Path(record["file"]).is_absolute()
        assert runtime._sha256(fixture) == record["sha256"]
