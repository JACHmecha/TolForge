"""Portable startup configuration and an executable packaging smoke check.

Source Windows CAD installations can set TOLFORGE_DLL_DIRS to a semicolon-
separated list of absolute DLL directories before launching TolForge, or use
%LOCALAPPDATA%/TolForge/runtime.json with a dll_directories array. Source
checkouts can also use a private .tolforge/runtime.json when the per-user
file is unavailable. The explicit environment setting takes precedence
over both files; the per-user file takes precedence over the source file. An
activated conda environment contributes its Library/bin directory. No paths
from a developer's workstation are part of the application configuration.
Frozen packages register only their own bundled DLLs and ignore these source
configuration mechanisms.
"""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import warnings


# Windows removes a search directory when its returned handle is closed.
# Keep these handles alive for as long as the application may load CAD DLLs.
_DLL_HANDLES: dict[str, object] = {}
_WINDOWS_ICU_HANDLES: dict[str, object] = {}
_NATIVE_DIAGNOSTIC_MODULES = (
    "TKernel.dll", "TKMath.dll", "TKBRep.dll", "_BRep.pyd", "Qt6Core.dll",
    "MSVCP140.dll", "VCRUNTIME140.dll", "VCRUNTIME140_1.dll", "tbb12.dll", "tbb.dll",
    "icuuc.dll", "icuin.dll",
)


def _bundle_root() -> Path | None:
    """PyInstaller's private runtime root, never a developer search path."""
    if not getattr(sys, "frozen", False):
        return None
    return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)).resolve()


def _bundled_dll_directories() -> list[str]:
    root = _bundle_root()
    if root is None:
        return []
    relative = (".", "Library/bin", "OCC/Core", "OCC/.libs", "PySide6", "PySide6/Qt/bin")
    return [str(path.resolve()) for value in relative if (path := root / value).is_dir()]


def _windows_system_directory() -> Path:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    get_directory = kernel.GetSystemDirectoryW
    get_directory.argtypes = [wintypes.LPWSTR, wintypes.UINT]
    get_directory.restype = wintypes.UINT
    buffer = ctypes.create_unicode_buffer(32768)
    length = get_directory(buffer, len(buffer))
    if not length or length >= len(buffer):
        raise OSError(ctypes.get_last_error(), "Cannot resolve the Windows system directory")
    return Path(buffer.value)


def _preload_windows_icu() -> None:
    """Select Qt's Windows ICU API before Conda's versioned-export aliases.

    Recent Conda environments can contain generic icuuc/icuin DLL aliases whose
    symbols differ from the Windows ICU API used by the PySide6 wheels. Load the
    actual system DLLs first without changing the environment's installed files.
    Persistent ctypes handles keep this loader choice alive for the process.
    """
    import ctypes

    try:
        directory = _windows_system_directory()
        for name in ("icuuc.dll", "icuin.dll"):
            path = directory / name
            key = str(path)
            if path.is_file() and key not in _WINDOWS_ICU_HANDLES:
                # LOAD_LIBRARY_SEARCH_SYSTEM32: only Windows owns these APIs.
                _WINDOWS_ICU_HANDLES[key] = ctypes.WinDLL(key, winmode=0x800)
    except OSError as exc:
        warnings.warn(f"Cannot select Windows system ICU before Qt: {exc}", RuntimeWarning, stacklevel=2)


def _windows_program_data_directory() -> Path:
    """Resolve the OS known folder rather than trust a process environment value."""
    import ctypes
    from ctypes import wintypes
    import uuid

    directory = _windows_system_directory()
    shell = ctypes.WinDLL(str(directory / "shell32.dll"), winmode=0x800)
    ole = ctypes.WinDLL(str(directory / "ole32.dll"), winmode=0x800)
    get_folder = shell.SHGetKnownFolderPath
    get_folder.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(wintypes.LPWSTR)]
    get_folder.restype = wintypes.LONG
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole.CoTaskMemFree.restype = None
    folder_id = (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID("62AB5D82-FDC1-4DC3-A9DD-070D1D495D97").bytes_le)
    folder = wintypes.LPWSTR()
    result = get_folder(ctypes.byref(folder_id), 0, None, ctypes.byref(folder))
    if result != 0:
        raise OSError(result, "Cannot resolve the Windows ProgramData known folder")
    try:
        return Path(folder.value).resolve()
    finally:
        ole.CoTaskMemFree(ctypes.cast(folder, ctypes.c_void_p))


def _offline_authenticode_signer(path: Path) -> dict | None:
    """Verify an embedded signature and its actual leaf signer using local trust.

    WinVerifyTrust's cache-only flag forbids network certificate retrieval. The
    state is closed in every outcome; unsigned/catalog-only files fail closed.
    """
    import ctypes
    from ctypes import wintypes
    import uuid

    class FileInfo(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("path", wintypes.LPCWSTR),
                    ("file", wintypes.HANDLE), ("known_subject", ctypes.c_void_p)]

    class TrustData(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("policy", ctypes.c_void_p), ("sip", ctypes.c_void_p),
                    ("ui", wintypes.DWORD), ("revocation", wintypes.DWORD), ("choice", wintypes.DWORD),
                    ("file", ctypes.POINTER(FileInfo)), ("state_action", wintypes.DWORD),
                    ("state", wintypes.HANDLE), ("url", wintypes.LPWSTR), ("flags", wintypes.DWORD),
                    ("ui_context", wintypes.DWORD), ("signature_settings", ctypes.c_void_p)]

    class ProviderCertificatePrefix(ctypes.Structure):
        # Read only the documented prefix of the provider-owned certificate.
        _fields_ = [("size", wintypes.DWORD), ("certificate", ctypes.c_void_p)]

    directory = _windows_system_directory()
    trust = ctypes.WinDLL(str(directory / "wintrust.dll"), winmode=0x800)
    crypt = ctypes.WinDLL(str(directory / "crypt32.dll"), winmode=0x800)
    verify = trust.WinVerifyTrust
    verify.argtypes = [wintypes.HWND, ctypes.c_void_p, ctypes.POINTER(TrustData)]
    verify.restype = wintypes.LONG
    provider_data = trust.WTHelperProvDataFromStateData
    provider_data.argtypes = [wintypes.HANDLE]
    provider_data.restype = ctypes.c_void_p
    provider_signer = trust.WTHelperGetProvSignerFromChain
    provider_signer.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    provider_signer.restype = ctypes.c_void_p
    provider_certificate = trust.WTHelperGetProvCertFromChain
    provider_certificate.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    provider_certificate.restype = ctypes.POINTER(ProviderCertificatePrefix)
    get_name = crypt.CertGetNameStringW
    get_name.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                        wintypes.LPWSTR, wintypes.DWORD]
    get_name.restype = wintypes.DWORD
    action = (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID("00AAC56B-CD44-11D0-8CC2-00C04FC295EE").bytes_le)
    file_info = FileInfo(ctypes.sizeof(FileInfo), str(path), None, None)
    data = TrustData()
    data.size = ctypes.sizeof(TrustData)
    data.ui = 2  # WTD_UI_NONE
    data.choice = 1  # WTD_CHOICE_FILE
    data.file = ctypes.pointer(file_info)
    data.state_action = 1  # WTD_STATEACTION_VERIFY
    data.flags = 0x1000 | 0x10  # CACHE_ONLY_URL_RETRIEVAL | REVOCATION_CHECK_NONE
    try:
        if verify(None, ctypes.byref(action), ctypes.byref(data)) != 0:
            return None
        provider = provider_data(data.state)
        signer = provider_signer(provider, 0, False, 0) if provider else None
        certificate = provider_certificate(signer, 0) if signer else None
        if not certificate or not certificate.contents.certificate:
            return None

        def attribute(oid):
            value = ctypes.c_char_p(oid)
            size = get_name(certificate.contents.certificate, 3, 0, value, None, 0)
            if size <= 1:
                return ""
            buffer = ctypes.create_unicode_buffer(size)
            get_name(certificate.contents.certificate, 3, 0, value, buffer, size)
            return buffer.value

        return {"status": "valid", "publisher": attribute(b"2.5.4.3"),
                "organization": attribute(b"2.5.4.10"), "verification": "WinVerifyTrust embedded signature; offline cache only"}
    finally:
        data.state_action = 2  # WTD_STATEACTION_CLOSE
        verify(None, ctypes.byref(action), ctypes.byref(data))


def _windows_security_component_evidence(path: Path) -> dict | None:
    """Allow only the verified Microsoft Defender DLL injected into this process."""
    if os.name != "nt" or path.name.lower() != "mpoav.dll":
        return None
    try:
        directory = _windows_program_data_directory() / "Microsoft" / "Windows Defender" / "Platform"
        relative = path.resolve().relative_to(directory.resolve())
        import re
        if len(relative.parts) != 2 or re.fullmatch(r"\d+(?:\.\d+){3}-\d+", relative.parts[0]) is None:
            return None
        signature = _offline_authenticode_signer(path)
        if (signature is None or signature["status"] != "valid"
                or signature["publisher"] not in ("Microsoft Windows", "Microsoft Corporation")
                or signature["organization"] != "Microsoft Corporation"):
            return None
        return signature
    except (OSError, ValueError, KeyError):
        return None


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
    if _bundle_root() is not None:
        return None
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
    if _bundle_root() is not None:
        return _bundled_dll_directories()
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

    if _bundle_root() is not None or os.environ.get("CONDA_PREFIX"):
        _preload_windows_icu()
    if _bundle_root() is not None:
        # pythonocc's optional initializer otherwise registers workstation
        # directories independently of TolForge. OCC.config is excluded from
        # frozen builds; suppress its environment fallback as well.
        os.environ.pop("OCCT_ESSENTIALS_ROOT", None)
    configured = _configured_dll_directories()
    conda_prefix = os.environ.get("CONDA_PREFIX") if _bundle_root() is None else None
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
        "bundle" if _bundle_root() is not None else
        "environment" if explicit else
        "file" if active_config == config else
        "source_file" if active_config is not None else "none"
    )
    # A malformed optional config should not turn diagnostics into another
    # warning/error when the user is already handling a native import failure.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        configured = _configured_dll_directories()
    conda_prefix = os.environ.get("CONDA_PREFIX") if _bundle_root() is None else None
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
        "preloaded_windows_icu": list(_WINDOWS_ICU_HANDLES),
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


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inside(path: str | Path, directory: Path) -> bool:
    return Path(path).resolve().is_relative_to(directory.resolve())


def _qualification_native_module_paths() -> dict[str, str]:
    """Enumerate loaded DLLs/PYDs rather than guess transitive dependencies."""
    paths = _loaded_native_module_paths()
    if os.name != "nt":
        return paths
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    enum_modules = psapi.EnumProcessModulesEx
    enum_modules.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE), wintypes.DWORD,
                            ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
    enum_modules.restype = wintypes.BOOL
    get_filename = kernel.GetModuleFileNameW
    get_filename.argtypes = [wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
    get_filename.restype = wintypes.DWORD
    capacity = 1024
    while True:
        modules = (wintypes.HMODULE * capacity)()
        needed = wintypes.DWORD()
        if not enum_modules(kernel.GetCurrentProcess(), modules, ctypes.sizeof(modules),
                            ctypes.byref(needed), 3):
            raise OSError(ctypes.get_last_error(), "Cannot enumerate loaded native dependencies")
        count = needed.value // ctypes.sizeof(wintypes.HMODULE)
        if count <= capacity:
            break
        if count > 16384:
            raise RuntimeError("Native dependency inventory exceeded its safety bound")
        capacity = count
    for handle in modules[:count]:
        buffer = ctypes.create_unicode_buffer(32768)
        length = get_filename(handle, buffer, len(buffer))
        if not length or length == len(buffer):
            raise OSError(ctypes.get_last_error(), "Cannot identify a loaded native dependency")
        path = Path(buffer.value)
        name = path.name
        if path.suffix.lower() in (".dll", ".pyd"):
            # Full paths identify duplicate basenames as well as DLL origins.
            paths[str(path)] = str(path)
    return paths


def _package_versions(build_metadata: dict | None = None) -> dict[str, dict]:
    import importlib
    import importlib.metadata

    packages = {}
    for name, distribution in (("numpy", "numpy"), ("matplotlib", "matplotlib"),
                               ("PySide6", "PySide6"), ("compas", "compas"),
                               ("compas_viewer", "compas-viewer"), ("compas_occ", "compas-occ"),
                               ("OCC", "pythonocc-core")):
        module = sys.modules.get(name)
        if module is None:
            continue
        try:
            version = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            version = getattr(module, "__version__", getattr(module, "VERSION", "unavailable"))
            embedded = (build_metadata or {}).get("packages", {})
            if version == "unavailable" and isinstance(embedded, dict):
                version = embedded.get(distribution, embedded.get(distribution.replace("-", "_"), "unavailable"))
        packages[name] = {"version": str(version), "module_path": getattr(module, "__file__", None)}
    if "PySide6" in packages:
        from PySide6.QtCore import qVersion
        packages["PySide6"]["qt_version"] = qVersion()
    return packages


def _check_frozen_profile(expected_profile: str | None, include_cad: bool) -> dict | None:
    root = _bundle_root()
    if expected_profile is not None and expected_profile not in ("scalar", "cad"):
        raise ValueError("Expected profile must be scalar or cad")
    if expected_profile is not None and root is None:
        raise RuntimeError("Package qualification requires a frozen executable")
    if root is None:
        return None
    metadata_path = root / "tolforge-build.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    actual = metadata.get("profile")
    if actual not in ("scalar", "cad"):
        raise RuntimeError("Frozen build metadata has no valid package profile")
    if expected_profile is not None and actual != expected_profile:
        raise RuntimeError(f"Expected {expected_profile} package; executable contains {actual} profile")
    if include_cad and actual != "cad":
        raise RuntimeError("CAD self-check requires the CAD package profile")
    if expected_profile == "cad" and not include_cad:
        raise RuntimeError("CAD package qualification must exercise its STEP backend")
    if actual == "scalar":
        import importlib.util
        if any(importlib.util.find_spec(name) is not None for name in ("OCC", "compas_occ")):
            raise RuntimeError("Scalar package unexpectedly exposes optional native CAD packages")
    return metadata


def _native_dependency_evidence() -> list[dict]:
    root = _bundle_root()
    windows = Path(os.environ.get("WINDIR", "C:/Windows")).resolve()
    evidence = []
    for value in sorted(set(_qualification_native_module_paths().values()), key=str.casefold):
        path = Path(value).resolve()
        bundled = root is not None and _inside(path, root)
        system = any(_inside(path, windows / directory) for directory in ("System32", "SysWOW64", "WinSxS", "SysArm32"))
        security = _windows_security_component_evidence(path) if root is not None and not bundled and not system else None
        item = {"name": path.name, "path": str(path), "sha256": _sha256(path),
                "origin": "bundle" if bundled else "windows" if system else "windows-security" if security else "external"}
        if security is not None:
            item["authenticode"] = security
        evidence.append(item)
    return evidence


def _verify_native_bundle(build_metadata: dict | None) -> dict:
    """Match packaged CAD binaries to the build environment's hashed closure."""
    root = _bundle_root()
    if root is None or (build_metadata or {}).get("profile") != "cad":
        return {"status": "not applicable"}
    manifest_path = root / "native-dependencies.json"
    expected_digest = build_metadata.get("native_dependencies_sha256")
    if not expected_digest or _sha256(manifest_path) != expected_digest:
        raise RuntimeError("Bundled native dependency manifest does not match build provenance")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_files = []
    for entry in manifest["native_binaries"]:
        expected_files.append((entry["bundle_path"], entry["sha256"]))
    for entry in manifest["extension_modules"]:
        expected_files.append((str(Path("OCC") / "Core" / Path(entry["path"]).name), entry["sha256"]))
    if not expected_files:
        raise RuntimeError("Bundled native dependency manifest is empty")
    for relative, digest in expected_files:
        path = root / relative
        if not _inside(path, root) or not path.is_file() or _sha256(path) != digest:
            raise RuntimeError(f"Bundled native dependency differs from the recorded build environment: {relative}")
    return {"status": "ok", "manifest_sha256": expected_digest, "native_files_verified": len(expected_files)}


def _validate_frozen_dependencies(evidence: list[dict]) -> None:
    if _bundle_root() is None:
        return
    for item in evidence:
        if item["origin"] == "external":
            raise RuntimeError(f"Frozen executable borrowed a native dependency outside its bundle: {item['path']}")
        # Windows may supply its VC redistributable. CAD/Qt must belong to the
        # executable even if an administrator happened to install them there.
        if item["origin"] != "bundle" and item["name"].lower().startswith(("tk", "qt6", "qwindows")):
            raise RuntimeError(f"Frozen CAD/Qt dependency is not bundled: {item['path']}")


def _cad_fixture_checks(directory: Path) -> tuple[list[dict], object]:
    """Round-trip three defined solids through the application STEP worker."""
    from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCone, BRepPrimAPI_MakeCylinder
    from OCC.Core.STEPControl import STEPControl_Writer, STEPControl_AsIs
    from OCC.Core.IFSelect import IFSelect_RetDone
    from gui.step_load_worker import StepLoadWorker

    fixtures = (
        ("cylinder", BRepPrimAPI_MakeCylinder(2.0, 5.0).Shape(), {"cylinder", "plane"}, 3),
        ("box", BRepPrimAPI_MakeBox(3.0, 4.0, 5.0).Shape(), {"plane"}, 6),
        # TolForge recognizes plane/cylinder analytically; the conical face is
        # intentionally recorded as other, while still exercising STEP/meshing.
        ("cone", BRepPrimAPI_MakeCone(2.0, 1.0, 5.0).Shape(), {"other", "plane"}, 3),
    )
    records = []
    viewport_result = None
    for name, shape, expected_kinds, face_count in fixtures:
        step_path = directory / f"{name}.step"
        writer = STEPControl_Writer()
        with tempfile.NamedTemporaryFile(dir=directory, prefix=f".{name}-", suffix=".step", delete=False) as output:
            temporary = Path(output.name)
        try:
            if writer.Transfer(shape, STEPControl_AsIs) != IFSelect_RetDone or writer.Write(str(temporary)) != IFSelect_RetDone:
                raise RuntimeError(f"CAD {name} STEP fixture write failed")
            os.replace(temporary, step_path)
        finally:
            temporary.unlink(missing_ok=True)
        loaded = StepLoadWorker(str(step_path), 0.1)._load()
        kinds = {surface.get("kind") for surface in loaded.face_surfaces}
        if (len(loaded.face_meshes) != face_count or not expected_kinds.issubset(kinds)
                or any(mesh.number_of_faces() == 0 for mesh in loaded.face_meshes)
                or loaded.source_sha256 != _sha256(step_path)):
            raise RuntimeError(f"CAD {name} STEP import/analytic recognition failed")
        records.append({"fixture": name, "file": step_path.name, "sha256": _sha256(step_path),
                        "faces": len(loaded.face_meshes), "edges": len(loaded.edge_polylines),
                        "vertices": len(loaded.vertex_points), "surface_kinds": sorted(kinds),
                        "status": "ok"})
        if name == "cylinder":
            viewport_result = loaded
    return records, viewport_result


def _qualify_native_viewport(loaded, screenshot_path: Path) -> dict:
    """Show the production renderer and prove geometry drawing and GPU picking.

    This deliberately needs an interactive native Qt platform and graphics
    driver. An offscreen/minimal test pass cannot qualify the desktop viewport.
    """
    if os.environ.get("QT_QPA_PLATFORM", "").split(":")[0].lower() in ("offscreen", "minimal", "minimalegl", "vnc"):
        raise RuntimeError("Native viewport qualification cannot use an offscreen/minimal Qt platform")
    import time
    import numpy as np
    from types import SimpleNamespace
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication
    from compas.colors import Color
    from compas_viewer.viewer import Viewer
    from gui.step_renderer import Renderer
    from gui.viewport_adapter import CompasViewportAdapter
    from gui.step_viewer_mixin import StepViewerMixin
    from OpenGL import GL

    # Match app.main: Viewer creates the first QApplication for its singleton.
    viewer = Viewer()
    app = QApplication.instance()
    platform = app.platformName().lower()
    if platform in ("offscreen", "minimal", "minimalegl", "vnc"):
        raise RuntimeError(f"Native viewport qualification rejected Qt platform {platform}")
    if Renderer is None:
        raise RuntimeError("Production STEP renderer is unavailable")
    renderer = Renderer()
    renderer.setWindowTitle("TolForge native viewport qualification")
    # COMPAS overrides resize to update initialized shaders. Qt must establish
    # the widget/context first, so use QWidget's fixed-size geometry here.
    renderer.setFixedSize(800, 600)
    viewport = CompasViewportAdapter(renderer)
    viewport.clear()
    renderer.show()

    def pump():
        deadline = time.monotonic() + 0.3
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)

    def pixels(image):
        image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        return np.frombuffer(image.bits(), dtype=np.uint8, count=image.sizeInBytes()).reshape(
            image.height(), image.bytesPerLine() // 4, 4)[:, :image.width()].copy()

    try:
        pump()
        context = renderer.context()
        if context is None or not context.isValid() or not renderer.isValid():
            raise RuntimeError("Native Qt/OpenGL context could not be created")
        context_format = context.format()
        context_version = (context_format.majorVersion(), context_format.minorVersion())
        if context_version < (3, 3):
            raise RuntimeError(
                f"Native viewport requires OpenGL 3.3 or newer; Qt created {context_version[0]}.{context_version[1]}"
            )
        blank = pixels(renderer.grabFramebuffer())
        for mesh in loaded.face_meshes:
            viewport.add(mesh, show_faces=True, show_lines=False, facecolor=Color.from_hex("#51B6C8"))
        viewport.refresh(rebuild=True)
        StepViewerMixin._zoom_to_fit(SimpleNamespace(_configure_viewport_grid=lambda *_: None), renderer)
        pump()
        # Some supported COMPAS releases do not set their private _inited
        # flag after init(). Check the buffer manager that actually draws.
        if not all(obj in renderer.buffer_manager.objects for obj in viewport.objects):
            raise RuntimeError("STEP scene objects were not committed to native draw buffers")
        image = renderer.grabFramebuffer()
        rendered = pixels(image)
        changed_pixels = int(np.count_nonzero(np.any(rendered != blank, axis=2)))
        if changed_pixels < 100:
            raise RuntimeError("STEP geometry did not change the native framebuffer")
        colors = np.asarray(renderer.read_instance_color((0, 0, renderer.width() - 1, renderer.height() - 1)))
        colors = colors.reshape(-1, colors.shape[-1])
        picked = any(tuple(int(value) for value in color) in renderer.scene.instance_colors
                     for color in np.unique(colors, axis=0))
        if not picked:
            raise RuntimeError("Native STEP geometry picking did not identify a scene object")
        position = np.asarray(renderer.camera.position).copy()
        renderer.camera.rotate(15, 5)
        renderer.camera.pan(5, 5)
        renderer.camera.zoom(1)
        viewport.refresh()
        pump()
        if np.allclose(position, np.asarray(renderer.camera.position)):
            raise RuntimeError("Native viewport camera controls did not move the camera")
        if np.array_equal(rendered, pixels(renderer.grabFramebuffer())):
            raise RuntimeError("Native viewport camera controls did not change the framebuffer")
        with viewport.gl_context():
            graphics = {name: (GL.glGetString(value) or b"").decode("utf-8", errors="replace")
                        for name, value in (("vendor", GL.GL_VENDOR), ("renderer", GL.GL_RENDERER),
                                            ("version", GL.GL_VERSION), ("glsl", GL.GL_SHADING_LANGUAGE_VERSION))}
        if not graphics["version"]:
            raise RuntimeError("Native OpenGL driver did not report a version")
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        if not image.save(str(screenshot_path), "PNG"):
            raise RuntimeError("Native viewport evidence image could not be saved")
        return {"status": "ok", "qt_platform": platform, "context_valid": True,
                "context_version": f"{context_version[0]}.{context_version[1]}",
                "context_profile": context_format.profile().name,
                "graphics": graphics, "scene_objects": len(viewport.objects),
                "geometry_pixels": changed_pixels, "picking": "ok", "camera_controls": "ok",
                "screenshot": str(screenshot_path), "screenshot_sha256": _sha256(screenshot_path)}
    finally:
        viewport.clear()
        renderer.close()
        renderer.deleteLater()
        app.processEvents()


def run_packaged_smoke_check(report_path: str | Path, *, include_cad: bool = False,
                             expected_profile: str | None = None, qualify_viewport: bool = False) -> int:
    """Write qualification evidence for this process and its exact executable.

    Source runs remain useful diagnostics. Supplying an expected package profile
    requires a frozen executable and checks that its native dependencies belong
    to the bundle. Viewport qualification is opt-in and opens a native window.
    A successful local run never asserts that a clean Windows machine was used.
    """
    report_path = Path(report_path).resolve()
    report = {"schema_version": 2, "status": "failed", "python": sys.version.split()[0],
              "frozen": bool(getattr(sys, "frozen", False)), "checks": [],
              "profile": "cad" if include_cad else "scalar", "packages": {},
              "cad_qualification": "not exercised", "cad_fixtures": [],
              "viewport": {"status": "not exercised"}, "clean_machine": "not asserted"}
    try:
        import importlib

        if qualify_viewport and not include_cad:
            raise ValueError("Native STEP viewport qualification requires the CAD self-check")
        report["build_metadata"] = _check_frozen_profile(expected_profile, include_cad)
        report["native_bundle_verification"] = _verify_native_bundle(report["build_metadata"])
        if report["build_metadata"] is not None:
            report["profile"] = report["build_metadata"]["profile"]
            report["executable"] = {"path": sys.executable, "sha256": _sha256(sys.executable)}
        configure_native_runtime()

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
            fixture_directory = report_path.with_suffix(".cad-fixtures")
            fixture_directory.mkdir(parents=True, exist_ok=True)
            report["cad_fixtures"], loaded = _cad_fixture_checks(fixture_directory)
            for record in report["cad_fixtures"]:
                record["file"] = str((fixture_directory / record["file"]).relative_to(report_path.parent))
            report["cad_qualification"] = "STEP round-trips passed; native viewport/clean-machine check still required"
            if qualify_viewport:
                report["viewport"] = _qualify_native_viewport(loaded, report_path.with_suffix(".viewport.png"))
                report["checks"].append("Native Qt/OpenGL STEP drawing, picking and camera controls")
            report["checks"].append("CAD cylinder, box and cone STEP round-trips")
            report["cad_qualification"] = ("STEP and native viewport passed; clean-machine check not asserted"
                                           if qualify_viewport else
                                           "STEP round-trips passed; native viewport/clean-machine check still required")
        report["packages"] = _package_versions(report.get("build_metadata"))
        report["native_runtime"] = native_runtime_diagnostics()
        report["native_dependencies"] = _native_dependency_evidence()
        _validate_frozen_dependencies(report["native_dependencies"])
        root = _bundle_root()
        if root is not None:
            for name, package in report["packages"].items():
                if package["module_path"] is not None and not _inside(package["module_path"], root):
                    raise RuntimeError(f"Frozen executable imported {name} outside its bundle")
            if any(not _inside(path, root) for path in _DLL_HANDLES):
                raise RuntimeError("Frozen executable retained an external DLL search directory")
        report["isolation"] = {"dll_configuration": "bundle only" if root is not None else "source environment",
                               "external_native_dependencies": [item["name"] for item in report["native_dependencies"]
                                                                if item["origin"] == "external"]}
        report["status"] = "ok"
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        if qualify_viewport and report["viewport"]["status"] != "ok":
            report["viewport"] = {"status": "failed", "error": report["error"]}
        # Early native import/rendering failures still need loading evidence.
        # Diagnostics are secondary and must not replace the original error.
        try:
            report["packages"] = _package_versions(report.get("build_metadata"))
            report.setdefault("native_runtime", native_runtime_diagnostics())
            report.setdefault("native_dependencies", _native_dependency_evidence())
        except Exception as diagnostic_error:
            report["diagnostic_error"] = f"{type(diagnostic_error).__name__}: {diagnostic_error}"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["status"] == "ok" else 1
