"""Study intent, readiness checks and supported-engine boundaries (no Qt)."""
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class Finding:
    stage: str
    severity: str
    message: str


def validate_study(study):
    """Validate the optional, backwards-compatible study settings block."""
    if not isinstance(study, dict):
        raise ValueError("Study settings must be an object.")
    for key in ("response_name", "objective", "assumptions", "seed", "default_cpk", "gdt_default_cpk"):
        if key in study and not isinstance(study[key], str):
            raise ValueError(f"Study {key} must be text.")
    seed = study.get("seed", "").strip()
    if seed and (not seed.isascii() or not seed.isdecimal() or int(seed) > 2**32 - 1):
        raise ValueError("Seed must be an integer from 0 to 4294967295, or blank.")
    for key in ("default_cpk", "gdt_default_cpk"):
        value = study.get(key, "").strip()
        if value and (not isfinite(float(value)) or float(value) <= 0):
            raise ValueError(f"{key} must be finite and positive, or blank.")
    for key in ("iterations", "gdt_iterations"):
        if key in study and (type(study[key]) is not int or not 100 <= study[key] <= 1000000):
            raise ValueError(f"{key} must be an integer from 100 to 1000000.")
    for key in ("lower_limit", "upper_limit"):
        if key in study and (not isinstance(study[key], (int, float)) or not isfinite(study[key])):
            raise ValueError(f"{key} must be finite.")
    if study.get("lower_limit", 0) > study.get("upper_limit", 0):
        raise ValueError("Acceptance minimum cannot exceed maximum.")
    if study.get("method", "worst_case") not in ("worst_case", "rss", "monte_carlo"):
        raise ValueError("Unsupported study analysis method.")
    if "units_confirmed" in study and not isinstance(study["units_confirmed"], bool):
        raise ValueError("Units confirmation must be true or false.")
    inspection = study.get("inspection", {})
    if not isinstance(inspection, dict):
        raise ValueError("Inspection settings must be an object.")
    for key in ("drawing", "source", "datum_frame"):
        if key in inspection and not isinstance(inspection[key], str):
            raise ValueError(f"Inspection {key} must be text.")
    if inspection.get("units", "mm") not in ("mm", "in"):
        raise ValueError("Inspection units must be mm or in.")
    for key in ("alignment_confirmed", "scope_confirmed"):
        if key in inspection and type(inspection[key]) is not bool:
            raise ValueError(f"Inspection {key} must be true or false.")
    rows = inspection.get("rows", [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Inspection rows must be a list of objects.")
    from .inspection import INSPECTION_FIELDS
    for row in rows:
        if any(not isinstance(row.get(key, ""), str) for key in INSPECTION_FIELDS):
            raise ValueError("Draft inspection cells must be text.")


def require_supported_distribution(distribution, name):
    if distribution.correlation_group:
        raise ValueError(f"{name}: correlated sources are not supported by the current engines.")
    if distribution.kind not in ("uniform", "normal"):
        raise ValueError(f"{name}: distribution '{distribution.kind}' is not supported by this workspace.")
    if distribution.kind == "normal":
        cpk = distribution.parameters.get("cpk")
        if cpk is None or not isfinite(cpk) or cpk <= 0:
            raise ValueError(f"{name}: normal sampling requires a finite positive Cpk.")
    allowed = {"cpk"} if distribution.kind == "normal" else set()
    if set(distribution.parameters) - allowed:
        raise ValueError(f"{name}: unsupported distribution parameters cannot be evaluated here.")


def validate_workspace_project(project):
    """Prevent editing a model in a GUI that cannot preserve its semantics."""
    project.validate()
    for tolerance in project.tolerances.values():
        require_supported_distribution(tolerance.distribution, tolerance.name)
    for stack in project.stacks.values():
        ids = [term.tolerance_id for term in stack.terms]
        if len(ids) != len(set(ids)):
            raise ValueError("Repeated uses of one tolerance source require shared sampling, which this workspace does not yet support.")
    for datum in project.datum_references.values():
        if datum.modifier != "RFS":
            raise ValueError("The CAD workspace does not support datum material-boundary modifiers or datum mobility.")
    for control in project.position_controls.values():
        for member in control.members:
            for source_id in (member.size_tolerance_id, member.position_x_tolerance_id, member.position_y_tolerance_id):
                source = project.tolerances[source_id]
                if source.tolerance_plus != source.tolerance_minus or source.distribution.kind != "uniform":
                    raise ValueError("The CAD pattern editor supports symmetric source bounds with a global Cpk only. This project needs a richer editor to preserve its source definitions.")


def study_readiness(project, *, datum_count=0, frame_ready=False,
                    pattern_count=0, unresolved_count=0, input_error=None):
    """Return actionable checks; readiness is not a standards certification."""
    findings = []
    if not project.study.get("objective", "").strip():
        findings.append(Finding("1 · Requirement", "warning", "Describe the functional requirement and assembly assumptions in Study."))
    if not project.study.get("units_confirmed", False):
        findings.append(Finding("2 · Model", "warning", "Confirm that CAD, drawing and numerical inputs use the displayed project units."))
    if project.units.length != "mm" or project.units.angle != "deg":
        findings.append(Finding("2 · Model", "error", "CAD/GD&T workspace currently requires mm and deg; conversion is not implemented."))
    if unresolved_count:
        findings.append(Finding("2 · Model", "error", f"Resolve {unresolved_count} missing or ambiguous feature link(s)."))
    if datum_count < 3:
        findings.append(Finding("3 · Datums", "error", "Assign A, B and C in precedence order for the position study."))
    elif not frame_ready:
        findings.append(Finding("3 · Datums", "error", "Build a supported datum frame and inspect its origin and axes."))
    if not pattern_count:
        findings.append(Finding("4 · Tolerances", "error", "Pick circular pattern features and define basic XY, sizes and position control."))
    if input_error:
        findings.append(Finding("4 · Tolerances", "error", input_error))
    if project.constraints or project.responses:
        findings.append(Finding("5 · Analyze", "warning", "Stored assembly constraints/responses are declarative; pattern conformance does not solve assembly motion or contact."))
    findings.append(Finding("5 · Analyze", "info", "Run as-modeled validation first, then seeded Monte Carlo. XY process variation is separate from the diametral GD&T acceptance zone."))
    findings.append(Finding("6 · Improve", "info", "Review size versus position failures; change one justified input at a time and rerun with the same seed."))
    return findings
