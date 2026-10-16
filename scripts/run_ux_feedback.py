"""Run bounded scalar UX journeys and preserve a reviewable evidence bundle.

Each window runs in a separate process. The parent depends only on the standard
library so it can report a missing/broken Qt environment instead of going green.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import traceback

from ux_feedback.reporting import (
    collect_source_provenance,
    new_run_directory,
    write_reports,
)


REPOSITORY = Path(__file__).resolve().parents[1]
STATUSES = {"pass", "product_failure", "runner_error", "infrastructure_unavailable"}
EXIT_CODES = {"pass": 0, "product_failure": 1, "runner_error": 2, "infrastructure_unavailable": 2}
REQUIRED_SCENARIOS = {"U01", "U02", "U06"}
COVERAGE = {
    "profile": "scalar-offscreen",
    "qt_platform": "offscreen",
    "renderer_enabled": False,
    "native_viewport_qualified": False,
    "ai_review_performed": False,
    "interaction": "QtTest mouse and keyboard on production Qt Widgets",
    "included": ["U01 first Worst Case", "U02 functional acceptance versus zero fit", "U06 invalidation and correction"],
    "excluded": ["native desktop/GPU", "discoverability or human satisfaction", "AI exploration", "Monte Carlo/RSS journeys", "save/reopen and export file dialogs"],
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def size_argument(value: str) -> tuple[int, int]:
    try:
        width, height = (int(part) for part in value.lower().split("x"))
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError("Use WIDTHxHEIGHT, for example 1300x800.") from None
    if not (1024 <= width <= 3840 and 768 <= height <= 2160):
        raise argparse.ArgumentTypeError("Supported logical sizes: width 1024–3840, height 768–2160.")
    return width, height


def failed_configuration(identifier, size, status, reason):
    return {
        "id": identifier,
        "width": size[0], "height": size[1], "status": status,
        "steps": [],
        "scenarios": [{"id": code, "title": code, "status": "not_run", "scope": "initial scalar pilot"}
                      for code in sorted(REQUIRED_SCENARIOS)],
        "findings": [{
            "id": f"{identifier}-execution",
            "classification": "infrastructure" if status == "infrastructure_unavailable" else "runner_error",
            "severity": "high", "title": "El recorrido no pudo completarse",
            "description": reason,
            "reproduction": "Repetir la misma configuración con el intérprete y las dependencias registrados.",
            "suggestion": "Revisar los registros del proceso antes de atribuir el fallo a TolForge.",
        }],
    }


def validate_configuration(result, identifier, size, directory):
    """Reject missing/incomplete evidence instead of treating an empty run as pass."""
    if not isinstance(result, dict) or result.get("status") not in STATUSES:
        raise ValueError("Worker did not return a recognized configuration status.")
    for key in ("steps", "scenarios", "findings"):
        if not isinstance(result.get(key), list):
            raise ValueError(f"Worker evidence is missing {key}.")
        if any(not isinstance(item, dict) for item in result[key]):
            raise ValueError(f"Worker {key} contains malformed evidence entries.")
    result["id"], result["width"], result["height"] = identifier, *size
    if result["status"] == "pass":
        completed = {item.get("id") for item in result["scenarios"] if item.get("status") == "pass"}
        if not REQUIRED_SCENARIOS.issubset(completed) or not result["steps"]:
            raise ValueError("A passing run must complete U01, U02 and U06 with step evidence.")
        if any(item.get("status") not in ("pass", "setup") for item in result["steps"]):
            raise ValueError("A passing run contains failed or incomplete steps.")
        if any(item.get("classification") in ("defect_reproduced", "runner_error", "infrastructure")
               for item in result["findings"]):
            raise ValueError("A passing run contains a blocking finding.")
    screenshots = 0
    for item in [*result["steps"], *result["findings"]]:
        relative = item.get("screenshot")
        if not relative:
            continue
        screenshot = Path(relative)
        if screenshot.is_absolute() or ".." in screenshot.parts:
            raise ValueError("Worker returned an unsafe screenshot path.")
        resolved = (directory / screenshot).resolve()
        if not resolved.is_relative_to(directory.resolve()) or not resolved.is_file() or resolved.stat().st_size == 0:
            raise ValueError("Worker returned missing or empty screenshot evidence.")
        item["screenshot"] = (Path(identifier) / screenshot).as_posix()
        screenshots += 1
    if result["status"] == "pass" and screenshots < 3:
        raise ValueError("A passing run requires screenshots for all three scenarios.")
    if result["status"] == "pass" and not REQUIRED_SCENARIOS.issubset(
            {item.get("scenario") for item in result["steps"] if item.get("screenshot")}):
        raise ValueError("Each scenario requires its own screenshot evidence.")
    return result


def run_configuration(directory: Path, size, *, timeout: int, inject_failure=False):
    identifier = directory.name
    state = directory / ".state"
    state.mkdir()
    environment = os.environ.copy()
    environment.update({
        "QT_QPA_PLATFORM": "offscreen",
        "QT_SCALE_FACTOR": "1",
        "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
        "LOCALAPPDATA": str(state / "local"), "APPDATA": str(state / "roaming"),
        "MPLCONFIGDIR": str(state / "matplotlib"),
    })
    arguments = [sys.executable, str(Path(__file__).resolve()),
                 "--_worker-directory", str(directory), "--size", f"{size[0]}x{size[1]}"]
    if inject_failure:
        arguments.append("--inject-failure")
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        with (directory / "stdout.log").open("w", encoding="utf-8") as output, \
                (directory / "stderr.log").open("w", encoding="utf-8") as errors:
            process = subprocess.run(
                arguments, cwd=REPOSITORY, env=environment, stdout=output, stderr=errors,
                timeout=timeout, check=False, creationflags=creationflags,
            )
        result_path = directory / "result.json"
        if not result_path.is_file():
            return failed_configuration(identifier, size, "runner_error",
                                        f"El proceso terminó con código {process.returncode} sin entregar result.json; revisar stdout.log/stderr.log.")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result = validate_configuration(result, identifier, size, directory)
        if process.returncode != EXIT_CODES[result["status"]]:
            raise ValueError(f"Worker exit code {process.returncode} disagrees with status {result['status']}.")
        return result
    except subprocess.TimeoutExpired:
        return failed_configuration(identifier, size, "runner_error",
                                    f"Se agotó el límite de {timeout} segundos. El proceso fue detenido; conservar la primera evidencia y revisar los registros.")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return failed_configuration(identifier, size, "runner_error", f"{type(exc).__name__}: {exc}")


def worker(directory, size, inject_failure=False):
    """All GUI imports stay here; even an unavailable environment gets evidence."""
    sys.path.insert(0, str(REPOSITORY / "Code"))
    try:
        from ux_feedback.journey import run_journey
        result = run_journey(directory, size, inject_failure=inject_failure)
    except (ImportError, OSError) as exc:
        traceback.print_exc()
        result = failed_configuration(directory.name, size, "infrastructure_unavailable",
                                      f"El entorno GUI no está disponible: {type(exc).__name__}: {exc}")
    except Exception as exc:
        traceback.print_exc()
        result = failed_configuration(directory.name, size, "runner_error",
                                      f"El corredor falló: {type(exc).__name__}: {exc}")
    (directory / "result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8",
    )
    return EXIT_CODES.get(result.get("status"), 2)


def aggregate_status(configurations):
    if not configurations:
        return "runner_error"
    for status in ("runner_error", "infrastructure_unavailable", "product_failure"):
        if any(item.get("status") == status for item in configurations):
            return status
    return "pass" if all(item.get("status") == "pass" for item in configurations) else "runner_error"


def reconcile_source(report, source_end):
    """A matrix spanning different source contents cannot certify one snapshot."""
    before = report["source"]
    changes = sorted(path for path in before.get("files", {}).keys() | source_end.get("files", {}).keys()
                     if before.get("files", {}).get(path) != source_end.get("files", {}).get(path))
    complete = bool(before.get("files")) and not before.get("hash_errors") and not source_end.get("hash_errors")
    consistent = complete and not changes and before.get("revision") == source_end.get("revision")
    report["source_validation"] = {
        "consistent": bool(consistent), "changed_files": changes,
        "revision_at_end": source_end.get("revision"), "files_at_end": source_end.get("files", {}),
        "hash_errors_at_end": source_end.get("hash_errors", []),
    }
    if not consistent:
        report["status"] = "runner_error"
        if report["configurations"]:
            configuration = report["configurations"][0]
            configuration["status"] = "runner_error"
            configuration["findings"].append({
                "id": "source-drift", "classification": "runner_error", "severity": "high",
                "title": "La identidad del código no pudo mantenerse durante la ejecución",
                "description": "Los archivos o la revisión cambiaron, o no se pudieron verificar todos sus hashes. El recorrido no certifica una única versión.",
                "reproduction": "Ejecutar de nuevo sin editar los archivos del checkout mientras la matriz está en marcha.",
                "suggestion": "Revisar source y source_validation en run.json; conservar esta ejecución como evidencia incompleta.",
            })


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=REPOSITORY / "artifacts" / "ux-feedback",
                        help="Evidence root; every invocation creates a unique run directory.")
    parser.add_argument("--size", type=size_argument, action="append", help="Repeat for multiple sizes; defaults to 1300x800 and 1024x768.")
    parser.add_argument("--repeat", type=int, default=1, help="Repeat the complete matrix, 1–10 times.")
    parser.add_argument("--timeout", type=int, default=60, help="Seconds per window, 10–180.")
    parser.add_argument("--inject-failure", action="store_true", help="Diagnostic verifier self-test; deliberately produces failure evidence and exit 1.")
    parser.add_argument("--_worker-directory", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not 1 <= args.repeat <= 10 or not 10 <= args.timeout <= 180:
        parser.error("--repeat must be 1–10 and --timeout 10–180.")
    sizes = args.size or [(1300, 800), (1024, 768)]
    if args._worker_directory:
        if len(sizes) != 1:
            parser.error("A worker requires one size.")
        return worker(args._worker_directory.resolve(), sizes[0], args.inject_failure)
    run_dir = new_run_directory(args.output_dir.resolve())
    report = {
        "schema_version": 1, "run_id": run_dir.name, "started_at": now(),
        "source": collect_source_provenance(REPOSITORY),
        "environment": {"python": platform.python_version(), "platform": platform.platform(),
                        "interpreter": sys.executable, "qt_platform": "offscreen", "scale_factor": 1},
        "coverage": COVERAGE, "diagnostic_failure_injection": args.inject_failure,
        "expected_configurations": len(sizes) * args.repeat, "complete": False,
        "configurations": [],
    }
    for repetition in range(1, args.repeat + 1):
        for width, height in sizes:
            identifier = f"{width}x{height}-r{repetition}-{len(report['configurations']) + 1:02d}"
            directory = run_dir / identifier
            directory.mkdir()
            configuration = run_configuration(directory, (width, height), timeout=args.timeout,
                                              inject_failure=args.inject_failure)
            report["configurations"].append(configuration)
            # Preserve immutable checkpoints if a later process/host cannot run.
            report["complete"] = len(report["configurations"]) == report["expected_configurations"]
            report["status"] = aggregate_status(report["configurations"]) if report["complete"] else "runner_error"
            report["finished_at"] = now()
            checkpoint = run_dir / f"progress-{len(report['configurations']):02d}.json"
            with checkpoint.open("x", encoding="utf-8") as stream:
                json.dump(report, stream, indent=2, ensure_ascii=False, allow_nan=False)
    reconcile_source(report, collect_source_provenance(REPOSITORY))
    report["finished_at"] = now()
    write_reports(run_dir, report)
    print(f"Estado UX: {report['status']}")
    print(f"Informe UX: {run_dir / 'report.html'}")
    print(f"Resumen UX: {run_dir / 'summary.md'}")
    return EXIT_CODES[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
