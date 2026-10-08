"""Prepare auditable Windows build inputs; never search a workstation for CAD DLLs."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, timezone


SYSTEM_DLLS = frozenset({
    "advapi32.dll", "bcrypt.dll", "bcryptprimitives.dll", "cfgmgr32.dll",
    "comctl32.dll", "comdlg32.dll", "crypt32.dll", "cryptbase.dll", "dbghelp.dll",
    "dnsapi.dll", "dwmapi.dll", "dwrite.dll", "dxgi.dll", "d3d11.dll", "gdi32.dll",
    "glu32.dll", "imm32.dll", "iphlpapi.dll", "kernel32.dll", "kernelbase.dll",
    "msvcrt.dll", "ncrypt.dll", "netapi32.dll", "normaliz.dll", "ntdll.dll",
    "ole32.dll", "oleaut32.dll", "opengl32.dll", "powrprof.dll", "psapi.dll",
    "rpcrt4.dll", "secur32.dll", "setupapi.dll", "shell32.dll", "shlwapi.dll",
    "ucrtbase.dll", "user32.dll", "userenv.dll", "version.dll", "winhttp.dll",
    "wininet.dll", "winmm.dll", "winspool.drv", "ws2_32.dll", "wsock32.dll", "wtsapi32.dll",
})


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256") if sys.version_info >= (3, 11) else None
        if digest is not None:
            return digest.hexdigest()
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
        return digest.hexdigest()


def git(root: Path, *args: str) -> str:
    output = subprocess.check_output(["git", "-C", str(root), *args], text=True, encoding="utf-8")
    return output if "-z" in args else output.strip()


def source_provenance(root: Path) -> dict:
    # Include nonignored untracked implementation files: a dirty build's HEAD
    # alone does not describe its executable. Paths and per-file digests are
    # portable and also make the aggregate digest independently checkable.
    paths = sorted(set(git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\0")) - {""})
    files = []
    digest = hashlib.sha256()
    for relative in paths:
        path = root / relative
        if path.is_file():
            file_hash = sha256(path)
            files.append({"path": relative, "sha256": file_hash})
            digest.update(relative.encode("utf-8") + b"\0" + file_hash.encode("ascii") + b"\n")
        else:
            files.append({"path": relative, "deleted": True})
            digest.update(relative.encode("utf-8") + b"\0deleted\n")
    return {
        "source_revision": git(root, "rev-parse", "HEAD"),
        "source_branch": git(root, "branch", "--show-current"),
        "source_dirty": bool(git(root, "status", "--porcelain", "--untracked-files=normal")),
        "source_tree_sha256": digest.hexdigest(),
        "source_files": files,
    }


def assert_release_dependencies(root: Path) -> dict:
    if os.name != "nt" or sys.version_info[:2] != (3, 12):
        raise RuntimeError("Windows release builds require the locked Windows x64 Python 3.12 environment.")
    if sys.maxsize <= 2**32:
        raise RuntimeError("Windows release builds require a 64-bit interpreter.")
    expected_python = (root / ".github/environments/python-version").read_text(encoding="utf-8-sig").strip()
    actual_python = ".".join(str(value) for value in sys.version_info[:3])
    if actual_python != expected_python:
        raise RuntimeError(f"Release interpreter: expected Python {expected_python}, found {actual_python}.")
    lock = root / ".github/environments/windows-release-py312.lock"
    versions = {}
    for line in lock.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([\w.-]+)==([^\s]+)\s+--hash=sha256:([a-f0-9]{64})$", line)
        if match:
            name, expected, _ = match.groups()
            actual = importlib.metadata.version(name)
            if actual != expected:
                raise RuntimeError(f"Release dependency {name}: expected {expected}, found {actual}. Install the hash lock.")
            versions[name] = actual
    if not versions:
        raise RuntimeError("Release dependency lock is empty.")
    return versions


def native_dependencies(prefix: Path) -> dict:
    """Resolve OCC PE import closure strictly inside its conda prefix."""
    import pefile

    prefix = prefix.resolve()
    records = []
    for path in sorted((prefix / "conda-meta").glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        records.append(record)
    occ_record = next((x for x in records if x.get("name") == "pythonocc-core"), None)
    if not occ_record or occ_record.get("version") != "7.9.3":
        raise RuntimeError("CAD builds require the locked conda pythonocc-core 7.9.3 environment, not workstation DLL directories.")
    if importlib.metadata.version("compas_occ") != "1.5.0":
        raise RuntimeError("CAD builds require compas_occ 1.5.0 from the pinned source archive.")
    direct_url = json.loads(importlib.metadata.distribution("compas_occ").read_text("direct_url.json") or "{}")
    wrapper_hash = direct_url.get("archive_info", {}).get("hashes", {}).get("sha256")
    wrapper_revision = direct_url.get("vcs_info", {}).get("commit_id")
    if wrapper_hash != "7ebcaedae2c27b284015521cb25efe8673807bef7257e5883559027631721656" and wrapper_revision != "8dc35a32e447bb053b236f0836c2a92d8900f784":
        raise RuntimeError("CAD wrapper origin does not match the hash-locked official source revision.")
    spec = importlib.util.find_spec("OCC")
    if spec is None or spec.origin is None:
        raise RuntimeError("The locked CAD interpreter cannot locate OCC.")
    occ_dir = Path(spec.origin).resolve().parent
    if not occ_dir.is_relative_to(prefix):
        raise RuntimeError("OCC must be installed inside the locked CAD interpreter prefix.")
    search_dirs = [occ_dir / "Core", prefix / "Library/bin", prefix / "DLLs", prefix]
    by_name = {}
    for directory in search_dirs:
        if directory.is_dir():
            for path in sorted(directory.iterdir()):
                if path.is_file() and path.suffix.lower() in {".dll", ".pyd"}:
                    by_name.setdefault(path.name.lower(), path)
    roots = sorted((occ_dir / "Core").glob("*.pyd"))
    if not roots:
        raise RuntimeError("The locked CAD environment contains no OCC native extension modules.")
    queue, seen, binaries, imports, system_dependencies = list(roots), set(), {}, {}, set()
    while queue:
        path = queue.pop()
        name = path.name.lower()
        if name in seen:
            continue
        seen.add(name)
        pe = pefile.PE(str(path), fast_load=True)
        try:
            pe.parse_data_directories(directories=[
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"],
            ])
            dependencies = sorted({
                entry.dll.decode("ascii").lower()
                for table in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT")
                for entry in getattr(pe, table, [])
            })
        finally:
            pe.close()
        relative = path.relative_to(prefix).as_posix()
        imports[relative] = dependencies
        for dependency in dependencies:
            if dependency.startswith(("api-ms-win-", "ext-ms-win-")) or dependency in SYSTEM_DLLS:
                system_dependencies.add(dependency)
                continue
            resolved = by_name.get(dependency)
            if resolved is None:
                raise RuntimeError(f"CAD native dependency {dependency} imported by {relative} is missing from the locked prefix.")
            if resolved.suffix.lower() == ".dll":
                binaries[dependency] = resolved
            queue.append(resolved)
    return {
        "schema_version": 1,
        "pythonocc_core": occ_record["version"],
        "compas_occ": "1.5.0",
        "conda_packages": [{key: record.get(key) for key in ("name", "version", "build", "subdir", "url", "sha256", "md5")} for record in records],
        "native_binaries": [{"path": path.relative_to(prefix).as_posix(), "bundle_path": path.name,
                             "sha256": sha256(path), "size_bytes": path.stat().st_size} for path in sorted(binaries.values())],
        "extension_modules": [{"path": path.relative_to(prefix).as_posix(), "sha256": sha256(path)} for path in roots],
        "pe_imports": imports,
        "system_dependencies": sorted(system_dependencies),
        "allowed_system_dependencies": sorted(SYSTEM_DLLS),
    }


def assert_conda_lock(prefix: Path, lock: Path) -> None:
    expected = {}
    for line in lock.read_text(encoding="utf-8-sig").splitlines():
        if not line or line.startswith(("#", "@")):
            continue
        url, separator, checksum = line.rpartition("#")
        if not separator or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise RuntimeError("The native conda explicit lock must pin every archive with SHA256.")
        expected[Path(url).name] = checksum
    if not expected:
        raise RuntimeError("The native conda lock is empty.")
    actual = {}
    for path in (prefix / "conda-meta").glob("*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        actual[record.get("fn", Path(record.get("url", "")).name)] = record.get("sha256")
    if expected != actual:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        changed = sorted(name for name in set(expected) & set(actual) if expected[name] != actual[name])
        raise RuntimeError(f"CAD conda prefix differs from the explicit lock (missing={missing}, extra={extra}, hash mismatch={changed}).")


def prepare(root: Path, output: Path, profile: str) -> dict:
    versions = assert_release_dependencies(root)
    lock_paths = [root / ".github/environments/windows-release-py312.lock"]
    native = None
    conda_runtime = None
    if profile == "cad":
        lock_paths.extend([root / ".github/environments/windows-cad-py312.lock", root / ".github/environments/native-cad-win-64.conda.lock"])
        assert_conda_lock(Path(sys.prefix), lock_paths[-1])
        native = native_dependencies(Path(sys.prefix))
        versions["compas_occ"] = "1.5.0"
        versions["pythonocc-core"] = "7.9.3"
    elif (Path(sys.base_prefix) / "conda-meta").is_dir():
        scalar_lock = root / ".github/environments/scalar-win-64.conda.lock"
        lock_paths.append(scalar_lock)
        assert_conda_lock(Path(sys.base_prefix), scalar_lock)
        conda_runtime = {
            "schema_version": 1,
            "profile": "scalar",
            "packages": [{key: record.get(key) for key in ("name", "version", "build", "subdir", "url", "sha256", "md5")}
                         for path in sorted((Path(sys.base_prefix) / "conda-meta").glob("*.json"))
                         for record in [json.loads(path.read_text(encoding="utf-8"))]],
        }
    output.mkdir(parents=True, exist_ok=True)
    provenance = {
        "schema_version": 1, "profile": profile,
        "build_started_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version, "python_implementation": sys.implementation.name,
        "packages": versions,
        "dependency_locks": [{"path": path.relative_to(root).as_posix(), "sha256": sha256(path)} for path in lock_paths],
        **source_provenance(root),
    }
    if native is not None:
        native_manifest = output / "native-dependencies.json"
        native_manifest.write_text(json.dumps(native, indent=2) + "\n", encoding="utf-8")
        provenance["native_dependencies_sha256"] = sha256(native_manifest)
    if conda_runtime is not None:
        runtime_path = output / "native-conda-runtime.json"
        runtime_path.write_text(json.dumps(conda_runtime, indent=2) + "\n", encoding="utf-8")
        provenance["conda_runtime_manifest_sha256"] = sha256(runtime_path)
    (output / "build-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    metadata = {key: value for key, value in provenance.items() if key != "source_files"}
    (output / "tolforge-build.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return provenance


def finalize(output: Path, profile: str) -> None:
    files = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path != output / "SHA256.json":
            if not path.resolve().is_relative_to(output.resolve()):
                raise RuntimeError("An artifact evidence path resolves outside its staged package.")
            files.append({"path": path.relative_to(output).as_posix(), "sha256": sha256(path), "size_bytes": path.stat().st_size})
    (output / "SHA256.json").write_text(json.dumps({"schema_version": 1, "profile": profile, "files": files}, indent=2) + "\n", encoding="utf-8")


def verify_source(root: Path, output: Path) -> None:
    before = json.loads((output / "build-provenance.json").read_text(encoding="utf-8"))
    after = source_provenance(root)
    if any(before.get(key) != after.get(key) for key in ("source_revision", "source_tree_sha256", "source_dirty")):
        raise RuntimeError("Source revision or working-tree contents changed while building/qualifying the executable.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "finalize", "verify-source"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", choices=("scalar", "cad"), required=True)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.root.resolve(), args.output.resolve(), args.profile)
    elif args.action == "finalize":
        finalize(args.output.resolve(), args.profile)
    else:
        verify_source(args.root.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
