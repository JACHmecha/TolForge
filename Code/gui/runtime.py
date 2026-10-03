"""Portable startup configuration and an executable packaging smoke check.

Custom Windows CAD installations can set TOLFORGE_DLL_DIRS to a semicolon-
separated list of absolute DLL directories before launching TolForge, or use
%LOCALAPPDATA%/TolForge/runtime.json with a dll_directories array. Source
checkouts can also use a private .tolforge/runtime.json when the per-user
file is unavailable. The explicit environment setting takes precedence
over both files; the per-user file takes precedence over the source file. An
activated conda environment contributes its Library/bin directory. No paths
from a developer's workstation are part of the application configuration.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import warnings


# Windows removes a search directory when its returned handle is closed.
# Keep these handles alive for as long as the application may load CAD DLLs.
_DLL_HANDLES: dict[str, object] = {}
_NATIVE_DIAGNOSTIC_MODULES = (
    "TKernel.dll", "TKMath.dll", "TKBRep.dll", "_BRep.pyd", "Qt6Core.dll",
    "MSVCP140.dll", "VCRUNTIME140.dll", "VCRUNTIME140_1.dll", "tbb12.dll", "tbb.dll",
)


def native_runtime_config_path() -> Path:
    """Per-user machine configuration, kept outside shared source code."""
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "TolForge" / "runtime.json"


def source_native_runtime_config_path() -> Path | None:
    """Private checkout configuration; frozen applications have no checkout."""
    if getattr(sys, "frozen", False):
        return None
    return Path(__file__).resolve().parents[2] / ".tolforge" / "runtime.json"


def _active_native_runtime_config_path() -> Path | None:
    """Select one existing file using the same precedence as DLL registration."""
    if os.environ.get("TOLFORGE_DLL_DIRS", "").strip():
        return None
    user_config = native_runtime_config_path()
    if user_config.is_file():
        return user_config
    source_config = source_native_runtime_config_path()
    if source_config is not None and source_config.is_file():
        return source_config
    return None


def _configured_dll_directories() -> list[str]:
    explicit = os.environ.get("TOLFORGE_DLL_DIRS", "").strip()
    if explicit:
        return [value.strip().strip('"') for value in explicit.split(os.pathsep) if value.strip()]
    config = _active_native_runtime_config_path()
    if config is None:
        return []
    try:
        data = json.loads(config.read_text(encoding="utf-8-sig"))
        values = data.get("dll_directories", [])
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise ValueError("dll_directories must be a list of directory paths")
        return values
    except (OSError, ValueError, AttributeError) as exc:
        warnings.warn(f"Cannot read native runtime configuration {config}: {exc}", RuntimeWarning, stacklevel=2)
        return []


def configure_native_runtime() -> tuple[str, ...]:
    """Register explicitly configured native dependencies, once per path.

    Missing/relative user paths produce warnings instead of preventing scalar
    analysis from starting. Registration is a no-op on non-Windows systems.
    Returns the currently registered directories for diagnostics.
    """
    if os.name != "nt":
        return ()

    configured = _configured_dll_directories()
    conda_prefix = os.environ.get("CONDA_PREFIX")
    if conda_prefix:
        conda_bin = Path(conda_prefix) / "Library" / "bin"
        if conda_bin.is_dir():
            configured.append(str(conda_bin))

    for value in configured:
        path = Path(value).expanduser()
        if not path.is_absolute() or not path.is_dir():
            warnings.warn(
                f"Ignoring native DLL directory {value!r}: an existing absolute path is required.",
                RuntimeWarning, stacklevel=2,
            )
            continue
        key = str(path.resolve())
        if key in _DLL_HANDLES:
            continue
        try:
            _DLL_HANDLES[key] = os.add_dll_directory(key)
        except OSError as exc:
            warnings.warn(f"Cannot register native DLL directory {key!r}: {exc}",
                          RuntimeWarning, stacklevel=2)
    return tuple(_DLL_HANDLES)


def _loaded_native_module_paths() -> dict[str, str]:
    """Read paths of relevant DLLs already loaded in this process on Windows."""
    if os.name != "nt":
        return {}
    import ctypes
    from ctypes import wintypes

    try:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        get_handle = kernel.GetModuleHandleW
        get_handle.argtypes = [wintypes.LPCWSTR]
        get_handle.restype = wintypes.HMODULE
        get_filename = kernel.GetModuleFileNameW
        get_filename.argtypes = [wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
        get_filename.restype = wintypes.DWORD
        paths = {}
        for name in _NATIVE_DIAGNOSTIC_MODULES:
            handle = get_handle(name)
            if not handle:
                continue
            size = 1024
            while size <= 32768:
                buffer = ctypes.create_unicode_buffer(size)
                length = get_filename(handle, buffer, size)
                if not length:
                    break
                if length < size:
                    paths[name] = buffer.value
                    break
                size *= 2
        return paths
    except OSError:
        return {}


def native_runtime_diagnostics() -> dict:
    """Capture bounded native-loading evidence without exposing full environment."""
    config = native_runtime_config_path()
    explicit = os.environ.get("TOLFORGE_DLL_DIRS", "").strip()
    config_exists = config.is_file()
    active_config = _active_native_runtime_config_path()
    source = (
        "environment" if explicit else
        "file" if active_config == config else
        "source_file" if active_config is not None else "none"
    )
    # A malformed optional config should not turn diagnostics into another
    # warning/error when the user is already handling a native import failure.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        configured = _configured_dll_directories()
    conda_prefix = os.environ.get("CONDA_PREFIX")
    if conda_prefix:
        conda_bin = Path(conda_prefix) / "Library" / "bin"
        if conda_bin.is_dir():
            configured.append(str(conda_bin))
    return {
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "runtime_module_path": str(Path(__file__).resolve()),
        "runtime_config_path": str(config),
        "runtime_config_exists": config_exists,
        "runtime_config_source": source,
        "active_runtime_config_path": str(active_config) if active_config is not None else None,
        "configured_dll_directories": configured,
        "registered_dll_directories": list(_DLL_HANDLES),
        "conda_prefix": conda_prefix,
        "loaded_native_modules": _loaded_native_module_paths(),
    }


def write_native_runtime_diagnostics(error) -> Path | None:
    """Atomically save local evidence, returning None if writing is unavailable.

    This is secondary to the caller's native import error. Filesystem failures
    must not replace that error or destroy a previous valid diagnostic report.
    """
    temporary = None
    try:
        report = native_runtime_diagnostics()
        report["error"] = f"{type(error).__name__}: {error}" if isinstance(error, BaseException) else str(error)
        payload = json.dumps(report, indent=2, allow_nan=False) + "\n"
        destination = native_runtime_config_path().with_name("native-runtime-diagnostics.json")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destination.parent,
            prefix=".native-runtime-diagnostics-", suffix=".tmp", delete=False,
        ) as output:
            temporary = Path(output.name)
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
        return destination
    except OSError:
        return None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def run_packaged_smoke_check(report_path: str | Path, *, include_cad: bool = False) -> int:
    """Exercise imports, scalar math and bundled SVGs without a visible window.

    This is intentionally a packaging check, not qualification of CAD parsing,
    driver/OpenGL behavior, or operation on every supported Windows machine.
    The explicit JSON report also works with a windowed PyInstaller executable
    whose stdout/stderr are unavailable.
    """
    report = {"status": "failed", "python": sys.version.split()[0],
              "frozen": bool(getattr(sys, "frozen", False)), "checks": [],
              "cad_qualification": "not exercised"}
    try:
        import importlib

        for name in ("numpy", "matplotlib", "PySide6", "compas", "compas_viewer"):
            importlib.import_module(name)
        report["checks"].append("GUI and numerical imports")

        from tolstack import Dimension, Stack

        result = Stack([Dimension("housing", 10.0, 0.1, 0.1, "+"),
                        Dimension("insert", 9.0, 0.05, 0.05, "-")]).worst_case()
        if abs(result.lower_limit - 0.85) > 1e-10 or abs(result.upper_limit - 1.15) > 1e-10:
            raise RuntimeError("Scalar clearance check failed")
        report["checks"].append("Scalar clearance calculation")

        from PySide6.QtSvg import QSvgRenderer

        icon_dir = Path(__file__).resolve().parent / "assets" / "icons" / "gdt"
        manifest = json.loads((icon_dir / "manifest.json").read_text(encoding="utf-8"))
        if not manifest.get("icons"):
            raise RuntimeError("Bundled GD&T icon manifest is empty")
        for entry in manifest["icons"]:
            if not QSvgRenderer(str(icon_dir / entry["file"])).isValid():
                raise RuntimeError(f"Bundled GD&T icon failed to load: {entry['file']}")
        report["checks"].append(f"{len(manifest['icons'])} bundled GD&T SVGs")
        if include_cad:
            configure_native_runtime()
            from tempfile import TemporaryDirectory
            from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeCylinder
            from OCC.Core.STEPControl import STEPControl_Writer, STEPControl_AsIs
            from OCC.Core.IFSelect import IFSelect_RetDone
            from gui.step_load_worker import StepLoadWorker
            with TemporaryDirectory(prefix="tolforge-cad-check-") as directory:
                step_path = Path(directory) / "cylinder.step"
                writer = STEPControl_Writer()
                writer.Transfer(BRepPrimAPI_MakeCylinder(2.0, 5.0).Shape(), STEPControl_AsIs)
                if writer.Write(str(step_path)) != IFSelect_RetDone:
                    raise RuntimeError("CAD STEP fixture write failed")
                loaded = StepLoadWorker(str(step_path), 0.1)._load()
                if not loaded.face_meshes or not any(surface.get("kind") == "cylinder" for surface in loaded.face_surfaces):
                    raise RuntimeError("CAD STEP import/analytic recognition failed")
            report["checks"].append("CAD cylinder STEP round-trip and analytic recognition")
            report["cad_qualification"] = "STEP round-trip passed; native viewport/clean-machine check still required"
        report["status"] = "ok"
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    Path(report_path).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["status"] == "ok" else 1
