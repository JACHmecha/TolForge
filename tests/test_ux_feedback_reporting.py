"""Reports distinguish product evidence from runner/infra and safely render local data."""

import hashlib
from html.parser import HTMLParser
import json
import subprocess
from urllib.parse import unquote

import pytest

from scripts.ux_feedback import reporting


@pytest.fixture
def report():
    return {
        "schema_version": 1, "run_id": "pilot-001", "started_at": "2026-10-16T01:00:00Z",
        "finished_at": "2026-10-16T01:00:03Z", "status": "pass", "complete": True,
        "source": {"revision": "abc123", "branch": "main", "dirty": True},
        "environment": {"qt_platform": "offscreen"},
        "coverage": {"native_dialogs": False, "cad_renderer": False},
        "configurations": [{
            "id": "1300x800", "width": 1300, "height": 800, "status": "pass",
            "scenarios": [{"id": "U01", "title": "Analizar", "status": "pass", "scope": "Cadena escalar"}],
            "steps": [{
                "id": "analyze", "scenario": "U01", "title": "Ejecutar análisis", "status": "pass",
                "action": "Pulsar Analyze", "expected": "Worst Case [0.7, 1.3] mm",
                "observed": "Worst Case [0.7, 1.3] mm", "elapsed_ms": 80,
                "screenshot": "shots/results.png",
            }], "findings": [],
        }],
    }


@pytest.fixture
def run_dir(tmp_path):
    directory = reporting.new_run_directory(tmp_path / "runs")
    (directory / "shots").mkdir()
    (directory / "shots/results.png").write_bytes(b"synthetic image placeholder")
    return directory


class _Links(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.links = []
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        self.links.extend(value for key, value in attrs if key in ("href", "src"))


@pytest.mark.parametrize(("status", "label"), [
    ("product_failure", "Defecto reproducido en el producto"),
    ("runner_error", "Error del corredor de pruebas"),
    ("infrastructure_unavailable", "Infraestructura no disponible"),
])
def test_incomplete_and_failure_reports_preserve_distinct_statuses(run_dir, report, status, label):
    report.update(status=status, configurations=[], complete=False)
    reporting.write_reports(run_dir, report)
    summary = (run_dir / "summary.md").read_text(encoding="utf-8")
    html = (run_dir / "report.html").read_text(encoding="utf-8")
    assert label in summary
    assert label in html
    assert "Comprobaciones del recorrido aprobadas" not in summary
    assert json.loads((run_dir / "run.json").read_text(encoding="utf-8"))["status"] == status
    assert "No se ejecutó una revisión visual con IA" in summary


def test_pass_reports_link_only_existing_relative_evidence_and_declare_limits(run_dir, report):
    reporting.write_reports(run_dir, report)
    html = (run_dir / "report.html").read_text(encoding="utf-8")
    summary = (run_dir / "summary.md").read_text(encoding="utf-8")
    links = _Links(html).links
    assert "shots/results.png" in links
    for link in links:
        assert ":" not in link and not link.startswith("/")
        assert (run_dir / unquote(link)).is_file()
    assert "Qt offscreen, con el renderer CAD desactivado" in summary
    assert "no mide satisfacción" in summary
    assert "diálogos nativos" in summary
    assert "Pendiente: no se ejecutó una revisión visual con IA" in (run_dir / "review-prompt.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("unsafe", [
    "../outside.png", "/outside.png", "C:/outside.png", "javascript:alert(1)",
    "https://example.com/image.png", "shots/results.png?execute", "shots/../results.png",
    "shots/results.png\n[bad](https://example.com)", "shots/missing.png", "shots/report.html",
])
def test_unavailable_or_unsafe_evidence_is_not_linked(run_dir, report, unsafe):
    report["status"] = "runner_error"
    report["configurations"][0]["steps"][0]["screenshot"] = unsafe
    reporting.write_reports(run_dir, report)
    html = (run_dir / "report.html").read_text(encoding="utf-8")
    assert "Sin captura disponible" in html
    assert not any(link.startswith(("http", "javascript", "file", "/", "C:")) for link in _Links(html).links)
    assert "src=" not in html
    assert "No hay capturas válidas disponibles" in (run_dir / "review-prompt.md").read_text(encoding="utf-8")


def test_html_markdown_and_image_paths_escape_hostile_text(run_dir, report):
    filename = "frame (1)&quote.png"
    (run_dir / "shots" / filename).write_bytes(b"placeholder")
    report["source"]["branch"] = '<script>alert("branch")</script>'
    step = report["configurations"][0]["steps"][0]
    step["title"] = '<img src=x onerror="alert(1)"> [external](javascript:alert(1))'
    step["screenshot"] = "shots/" + filename
    report["configurations"][0]["findings"] = [{"title": step["title"], "classification": "ux_hypothesis"}]
    reporting.write_reports(run_dir, report)
    html = (run_dir / "report.html").read_text(encoding="utf-8")
    summary = (run_dir / "summary.md").read_text(encoding="utf-8")
    assert "<script>" not in html and '<img src=x onerror=' not in html
    assert "&lt;script&gt;" in html
    assert '<img src=x onerror=' not in summary
    assert "\\[external\\]\\(javascript:alert\\(1\\)\\)" in summary
    assert "shots/frame%20%281%29%26quote.png" in _Links(html).links
    assert json.loads((run_dir / "run.json").read_text(encoding="utf-8"))["source"]["branch"] == report["source"]["branch"]


def test_only_three_priorities_shown_but_all_findings_preserved(run_dir, report):
    report["configurations"][0]["findings"] = [
        {"id": f"f{i}", "severity": severity, "title": title, "classification": "ux_hypothesis"}
        for i, severity, title in [(1, "low", "Omitido"), (2, "high", "Prioridad alta"),
                                   (3, "medium", "Prioridad media"), (4, "critical", "Prioridad crítica")]
    ]
    reporting.write_reports(run_dir, report)
    html = (run_dir / "report.html").read_text(encoding="utf-8")
    summary = (run_dir / "summary.md").read_text(encoding="utf-8")
    assert "Omitido" not in html and "Omitido" not in summary
    assert html.index("Prioridad crítica") < html.index("Prioridad alta") < html.index("Prioridad media")
    assert "Hipótesis de UX; requiere revisión" in html
    assert len(json.loads((run_dir / "run.json").read_text(encoding="utf-8"))["configurations"][0]["findings"]) == 4


@pytest.mark.parametrize("number", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_report_values_fail_before_any_report_is_written(run_dir, report, number):
    report["configurations"][0]["steps"][0]["elapsed_ms"] = number
    with pytest.raises(ValueError):
        reporting.write_reports(run_dir, report)
    assert not (run_dir / "run.json").exists()
    assert not (run_dir / "summary.md").exists()


@pytest.mark.parametrize("change", ["no_configurations", "no_steps", "no_scenarios", "no_screenshot", "failed_step", "failed_scenario", "incomplete"])
def test_pass_requires_actual_evidence(run_dir, report, change):
    configuration = report["configurations"][0]
    if change == "no_configurations":
        report["configurations"] = []
    elif change == "no_steps":
        configuration["steps"] = []
    elif change == "no_scenarios":
        configuration["scenarios"] = []
    elif change == "no_screenshot":
        configuration["steps"][0].pop("screenshot")
    elif change == "failed_step":
        configuration["steps"][0]["status"] = "fail"
    elif change == "failed_scenario":
        configuration["scenarios"][0]["status"] = "fail"
    else:
        report["complete"] = False
    with pytest.raises(ValueError, match="passing report"):
        reporting.write_reports(run_dir, report)
    assert not (run_dir / "run.json").exists()


def test_run_directories_and_report_files_never_overwrite_existing_evidence(tmp_path, run_dir, report):
    second = reporting.new_run_directory(tmp_path / "runs")
    assert second != run_dir and second.is_dir()
    reporting.write_reports(run_dir, report)
    before = {path.name: path.read_bytes() for path in run_dir.iterdir() if path.is_file()}
    report["run_id"] = "modified"
    with pytest.raises(FileExistsError):
        reporting.write_reports(run_dir, report)
    assert before == {path.name: path.read_bytes() for path in run_dir.iterdir() if path.is_file()}


def test_source_provenance_hashes_actual_edited_files_without_copying_or_secrets(tmp_path, monkeypatch):
    files = {
        "Code/gui/app.py": b"version=1", "scripts/ux_feedback/reporting.py": b"report",
        "tests/ux/fixtures/clearance.json": b"{}", "requirements.txt": b"PySide6",
        "setup.py": b"setup()", "TolForge.spec": b"build",
        ".github/workflows/test.yml": b"name: tests",
        "Code/gui/secret_keys.py": b"private", "Code/.hidden/hidden.py": b"hidden",
        "scripts/__pycache__/cache.py": b"cache", "Code/unrelated.json": b"ignored",
    }
    for relative, content in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def git_result(args, **kwargs):
        output = "abc123\n" if args[-1] == "HEAD" else "?? scripts/\n"
        if "--abbrev-ref" in args:
            output = "main\n"
        return subprocess.CompletedProcess(args, 0, stdout=output, stderr="")

    monkeypatch.setattr(reporting.subprocess, "run", git_result)
    before = reporting.collect_source_provenance(tmp_path)
    assert before["revision"] == "abc123" and before["branch"] == "main" and before["dirty"] is True
    assert before["files"]["Code/gui/app.py"] == hashlib.sha256(b"version=1").hexdigest()
    assert "tests/ux/fixtures/clearance.json" in before["files"]
    assert ".github/workflows/test.yml" in before["files"]
    assert not any(word in key for key in before["files"] for word in ("secret", "hidden", "__pycache__", "unrelated"))
    (tmp_path / "Code/gui/app.py").write_bytes(b"version=2")
    after = reporting.collect_source_provenance(tmp_path)
    assert before["files"]["Code/gui/app.py"] != after["files"]["Code/gui/app.py"]
    assert len([path for path in tmp_path.rglob("*") if path.is_file()]) == len(files)


def test_missing_git_does_not_fabricate_clean_provenance(tmp_path, monkeypatch):
    def unavailable(*args, **kwargs):
        raise FileNotFoundError("git unavailable")

    monkeypatch.setattr(reporting.subprocess, "run", unavailable)
    provenance = reporting.collect_source_provenance(tmp_path)
    assert provenance["revision"] is None and provenance["dirty"] is None
    assert provenance["git_error"] == "FileNotFoundError"


def test_diagnostic_injected_failure_is_conspicuous_and_not_a_product_claim(run_dir, report):
    report.update(status="product_failure", diagnostic_failure_injection=True)
    report["configurations"][0].update(status="product_failure", environment={"device_pixel_ratio": 1.5})
    reporting.write_reports(run_dir, report)
    for filename in ("summary.md", "report.html", "review-prompt.md"):
        content = (run_dir / filename).read_text(encoding="utf-8")
        assert "EJECUCIÓN DE DIAGNÓSTICO" in content
        assert "no demuestra un defecto" in content
    html = (run_dir / "report.html").read_text(encoding="utf-8")
    assert "Defecto reproducido en el producto" not in html
    assert "device_pixel_ratio" in html and "1.5" in html


def test_summary_stays_short_for_a_hundred_steps_and_full_details_remain_in_html(run_dir, report):
    original = report["configurations"][0]["steps"][0]
    report["configurations"][0]["steps"] = [
        {**original, "id": f"step-{index:03}", "title": f"Detailed step {index:03}",
         "observed": f"Observed evidence {index:03}"}
        for index in range(100)
    ]
    reporting.write_reports(run_dir, report)
    summary = (run_dir / "summary.md").read_text(encoding="utf-8")
    html = (run_dir / "report.html").read_text(encoding="utf-8")
    assert len(summary.splitlines()) < 65
    assert len(summary) < 5000
    assert "Pasos aprobados: **100/100**" in summary
    assert "Capturas distintas: **1**" in summary
    assert "| Configuración | Estado | Escenarios aprobados | Pasos aprobados | Capturas | Evidencia |" in summary
    assert "shots/results.png" in summary
    assert "Detailed step" not in summary and "Observed evidence" not in summary
    assert "descargar y extraer el artefacto completo" in summary
    for index in range(100):
        assert f"Detailed step {index:03}" in html
        assert f"Observed evidence {index:03}" in html
