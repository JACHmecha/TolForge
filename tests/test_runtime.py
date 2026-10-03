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
    monkeypatch.delenv("TOLFORGE_DLL_DIRS", raising=False)
    monkeypatch.delenv("CONDA_PREFIX", raising=False)
    monkeypatch.setattr(runtime, "_DLL_HANDLES", {})
    monkeypatch.setattr(runtime, "_loaded_native_module_paths", lambda: {})
    assert runtime._configured_dll_directories() == []
    report = runtime.native_runtime_diagnostics()
    assert report["runtime_config_source"] == "none"
    assert report["active_runtime_config_path"] is None
