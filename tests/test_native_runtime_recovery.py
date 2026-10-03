"""Retry reader detection after changing DLL configuration in a running app.

The loader is simulated so this recovery contract runs without OpenCascade,
Windows or workstation-specific dependency directories.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

from gui import runtime, step_renderer


@pytest.mark.parametrize("configuration_source", ["local_file", "environment"])
def test_reader_recovers_when_dll_configuration_is_added_after_startup(tmp_path, monkeypatch, configuration_source):
    config = tmp_path / "runtime.json"
    dependency_dir = tmp_path / "native-reader"
    dependency_dir.mkdir()
    monkeypatch.setattr(runtime, "native_runtime_config_path", lambda: config)
    monkeypatch.setattr(runtime, "source_native_runtime_config_path", lambda: None, raising=False)
    monkeypatch.delenv("TOLFORGE_DLL_DIRS", raising=False)
    monkeypatch.delenv("CONDA_PREFIX", raising=False)
    monkeypatch.setattr(runtime, "_DLL_HANDLES", {})
    events = []

    def register_configured_runtime():
        events.append("configure")
        for directory in runtime._configured_dll_directories():
            if Path(directory).is_dir():
                # Retaining the simulated search handle mirrors the loader
                # contract: imports cannot succeed until registration occurs.
                runtime._DLL_HANDLES.setdefault(directory, object())
        return tuple(runtime._DLL_HANDLES)

    def native_import(name):
        events.append(("import", name))
        if str(dependency_dir) not in runtime._DLL_HANDLES:
            raise ImportError("native reader dependency is not registered")
        assert name in ("compas_occ.brep", "OCC.Core.STEPControl")
        return object()

    monkeypatch.setattr(runtime, "configure_native_runtime", register_configured_runtime)
    # Support the production binding whether it is imported at module scope
    # or resolved from gui.runtime inside the detection function.
    monkeypatch.setattr(step_renderer, "configure_native_runtime", register_configured_runtime, raising=False)
    monkeypatch.setattr(step_renderer.importlib.util, "find_spec", lambda name: object() if name == "compas_occ" else None)
    monkeypatch.setattr(step_renderer.importlib, "import_module", native_import)

    # Application startup happens while native configuration is unavailable.
    register_configured_runtime()
    backend, message = step_renderer.detect_step_backend()
    assert backend is None
    assert "native reader dependency is not registered" in message
    assert runtime._DLL_HANDLES == {}

    if configuration_source == "local_file":
        config.write_text(json.dumps({"dll_directories": [str(dependency_dir)]}), encoding="utf-8")
    else:
        monkeypatch.setenv("TOLFORGE_DLL_DIRS", str(dependency_dir))

    # No restart and no explicit reconfiguration call: the next Load STEP
    # detection must apply the changed setting before retrying native imports.
    events.clear()
    backend, message = step_renderer.detect_step_backend()
    assert backend == "compas_occ"
    assert events[0] == "configure"
    assert events[1:] == [("import", "compas_occ.brep"), ("import", "OCC.Core.STEPControl")]
    assert "Loaded" in message
    handle = runtime._DLL_HANDLES[str(dependency_dir)]

    # Repeated loads retain the same search handle rather than closing it or
    # requiring another startup sequence.
    assert step_renderer.detect_step_backend()[0] == "compas_occ"
    assert runtime._DLL_HANDLES[str(dependency_dir)] is handle
