"""Use Windows ICU consistently in the builder and its isolated Python workers.

Enabled only by build_installer.ps1. Qt 6.11 on Windows uses the operating
system's unversioned ICU API; conda's private ICU has incompatible exports.
"""
import os

if os.environ.get("TOLFORGE_WINDOWS_BUILD_BOOTSTRAP") == "1":
    import importlib.util
    from pathlib import Path

    # Pytest's backend-boundary fixtures intentionally shadow gui.runtime.
    # Load only this checkout's trusted startup helper, without changing which
    # application/backend modules the child process is exercising.
    runtime_path = Path(__file__).resolve().parents[2] / "Code/gui/runtime.py"
    runtime_spec = importlib.util.spec_from_file_location("_tolforge_windows_build_startup", runtime_path)
    runtime = importlib.util.module_from_spec(runtime_spec)
    runtime_spec.loader.exec_module(runtime)
    runtime._preload_windows_icu()
