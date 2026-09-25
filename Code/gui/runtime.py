"""Portable startup configuration and an executable packaging smoke check.

Custom Windows CAD installations can set TOLFORGE_DLL_DIRS to a semicolon-
separated list of absolute DLL directories before launching TolForge. An
activated conda environment contributes its Library/bin directory. No paths
from a developer's workstation are part of the application configuration.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import warnings


# Windows removes a search directory when its returned handle is closed.
# Keep these handles alive for as long as the application may load CAD DLLs.
_DLL_HANDLES: dict[str, object] = {}


def configure_native_runtime() -> tuple[str, ...]:
    """Register explicitly configured native dependencies, once per path.

    Missing/relative user paths produce warnings instead of preventing scalar
    analysis from starting. Registration is a no-op on non-Windows systems.
    Returns the currently registered directories for diagnostics.
    """
    if os.name != "nt":
        return ()

    configured = [value.strip().strip('"') for value in
                  os.environ.get("TOLFORGE_DLL_DIRS", "").split(os.pathsep)
                  if value.strip()]
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
