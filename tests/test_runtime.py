import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

from gui import runtime


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
