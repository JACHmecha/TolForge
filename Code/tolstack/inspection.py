"""Position/size inspection of supplied measurements already aligned to a DRF.

This module does not fit measured datums, evaluate form/orientation, or apply
measurement-uncertainty decision rules. It uses the existing bounded model.
"""
from dataclasses import dataclass, asdict
from math import isfinite
from .characteristics import (
    SUPPORTED_CHARACTERISTICS, drawing_coverage, normalize_datum_references,
    parse_control_specification, validate_drawing_controls,
)
from .gdt import evaluate_position


INSPECTION_FIELDS = (
    "name", "basic_x", "basic_y", "measured_x", "measured_y", "diameter",
    "size_lower", "size_upper", "position_tolerance", "modifier", "feature_kind",
)


@dataclass(frozen=True)
class InspectionFeature:
    name: str
    basic_x: float
    basic_y: float
    measured_x: float
    measured_y: float
    diameter: float
    size_lower: float
    size_upper: float
    position_tolerance: float
    modifier: str = "RFS"
    feature_kind: str = "hole"

    @classmethod
    def from_row(cls, row):
        try:
            values = {key: str(row.get(key, "")).strip() for key in INSPECTION_FIELDS}
            for key in INSPECTION_FIELDS[1:9]:
                values[key] = float(values[key])
            feature = cls(**values)
        except (ValueError, TypeError) as exc:
            raise ValueError("Every inspection row needs a name, numeric coordinates/size/limits, modifier and feature kind.") from exc
        feature.validate()
        return feature

    def validate(self):
        if not self.name.strip():
            raise ValueError("Inspection feature name is required.")
        for key in INSPECTION_FIELDS[1:9]:
            if not isfinite(getattr(self, key)):
                raise ValueError(f"{self.name}: {key} must be finite.")
        if min(self.diameter, self.size_lower, self.size_upper) <= 0:
            raise ValueError(f"{self.name}: diameters and drawing size limits must be positive.")
        if self.size_lower > self.size_upper or self.position_tolerance < 0:
            raise ValueError(f"{self.name}: ordered size limits and nonnegative position tolerance are required.")
        if self.modifier not in ("RFS", "MMC", "LMC") or self.feature_kind not in ("hole", "pin"):
            raise ValueError(f"{self.name}: choose RFS/MMC/LMC and hole/pin.")


def _validate_inspection_context(drawing, measurement_source, datum_frame,
                                 alignment_confirmed, scope_confirmed):
    if not all(isinstance(value, str) and value.strip() for value in (drawing, measurement_source, datum_frame)):
        raise ValueError("Record drawing/revision, measurement source/part ID, and datum alignment before evaluation.")
    if alignment_confirmed is not True:
        raise ValueError("Confirm measurements and basic coordinates use the recorded datum frame and units.")
    if scope_confirmed is not True:
        raise ValueError("Confirm this is a single-segment position/size check with axes parallel to datum Z and no datum mobility.")


def _evaluate_feature(feature):
    mmc, lmc = ((feature.size_lower, feature.size_upper) if feature.feature_kind == "hole"
                else (feature.size_upper, feature.size_lower))
    return asdict(evaluate_position(
        feature.measured_x - feature.basic_x, feature.measured_y - feature.basic_y,
        feature.position_tolerance, feature.diameter, mmc, lmc,
        feature.modifier, feature.feature_kind,
    ))


def _measurement_rows_by_name(rows):
    measured = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Inspection measurement rows must be objects.")
        name = str(row.get("name", "")).strip()
        if not name:
            continue  # An unrelated blank draft row is not a measured feature.
        if name in measured:
            raise ValueError("Inspection feature names must be unique.")
        measured[name] = row
    return measured


def _prepare_drawing_controls(controls, rows, *, drawing, measurement_source, datum_frame,
                              alignment_confirmed, scope_confirmed):
    measured = _measurement_rows_by_name(rows)
    evaluated_controls = []
    prepared = []
    for control in controls:
        characteristic = control["characteristic"]
        supported = characteristic in SUPPORTED_CHARACTERISTICS
        effective_specification = parse_control_specification(characteristic, control["specification"])
        evaluated = dict(
            control, supported=supported, status="unevaluated", passes=None,
            effective_specification=effective_specification,
            effective_datum_frame=control["datum_references"] or (datum_frame if characteristic == "size" else None),
            evidence=None, reason="",
        )
        if not supported:
            evaluated.update(status="unsupported", reason="This characteristic has no supported inspection solver.")
        elif characteristic == "position" and not control["datum_references"]:
            evaluated["reason"] = "Position control datum references are missing; the drawing alignment requirement is unverified."
        elif not control["feature_name"] or control["feature_name"] not in measured:
            evaluated["reason"] = "No linked measurement is available for this requested control."
        elif control["datum_references"] and (
            normalize_datum_references(control["datum_references"]) != normalize_datum_references(datum_frame)
        ):
            evaluated["reason"] = "Requested datum references differ from the recorded measurement datum frame; alignment is unverified."
        else:
            _validate_inspection_context(drawing, measurement_source, datum_frame,
                                         alignment_confirmed, scope_confirmed)
            effective_row = dict(measured[control["feature_name"]])
            effective_row.update(effective_specification)
            try:
                feature = InspectionFeature.from_row(effective_row)
            except ValueError as exc:
                raise ValueError(f"Drawing control {control['balloon']} ({control['id']}): {exc}") from exc
            prepared.append((evaluated, feature))
        evaluated_controls.append(evaluated)
    return evaluated_controls, prepared


def evaluate_inspection(rows, *, drawing, measurement_source, datum_frame, units,
                        alignment_confirmed, scope_confirmed, drawing_controls=None,
                        report_context=None):
    """Snapshot requested checks and coverage, keeping measurements separate from CAD.

    Omitting the inventory retains the original per-feature position-and-size
    behavior. A declared inventory evaluates each supported request with its own
    drawing limits. Unsupported and missing/alignment-unverified measurements
    remain explicit in coverage; only requested dispositions affect coverage.
    """
    if units not in ("mm", "in"):
        raise ValueError("Inspection units must be mm or in.")
    if not all(isinstance(value, str) for value in (drawing, measurement_source, datum_frame)):
        raise ValueError("Drawing, measurement source and datum frame must be text.")
    try:
        rows = list(rows)
    except TypeError as exc:
        raise ValueError("Inspection measurements must be a sequence of row objects.") from exc
    controls = validate_drawing_controls(drawing_controls) if drawing_controls is not None else []
    if controls:
        evaluated_controls, prepared = _prepare_drawing_controls(
            controls, rows, drawing=drawing, measurement_source=measurement_source,
            datum_frame=datum_frame, alignment_confirmed=alignment_confirmed,
            scope_confirmed=scope_confirmed,
        )
    else:
        _validate_inspection_context(drawing, measurement_source, datum_frame,
                                     alignment_confirmed, scope_confirmed)
        features = [InspectionFeature.from_row(row) for row in rows]
        if not features:
            raise ValueError("Add at least one measured feature.")
        if len({feature.name for feature in features}) != len(features):
            raise ValueError("Inspection feature names must be unique.")
        evaluated_controls = []
        prepared = [(None, feature) for feature in features]
    limitations = [
        "Supplied measurements are already aligned to the stated datum frame; no measured datum fitting is performed.",
        "Single-segment diametral position and size only; feature axes parallel to datum Z; no datum mobility.",
        "No form, general orientation, composite position or whole-drawing conformance assessment.",
        "No measurement-uncertainty guard band or decision rule is applied; report nominal margins for engineering review.",
        "Independent size check uses supplied diameter, not a complete feature-of-size form/envelope verification.",
        "Coverage applies only to the supplied drawing-control inventory; unsupported or unevaluated requests prevent complete coverage.",
    ]
    from .reporting import build_report_evidence
    evidence_context = dict(report_context or {})
    sources = list(evidence_context.get("sources", []))
    seen_references = {
        (source.get("kind"), normalize_datum_references(source.get("reference", "")))
        for source in sources if isinstance(source, dict) and isinstance(source.get("reference", ""), str)
    }
    references = [("drawing", drawing), ("measurement", measurement_source)]
    references.extend(("drawing", f"{control['drawing']} Rev {control['revision']}") for control in controls)
    for kind, reference in references:
        identity = kind, normalize_datum_references(reference)
        if reference.strip() and identity not in seen_references:
            sources.append({"kind": kind, "reference": reference})
            seen_references.add(identity)
    evidence_context["sources"] = sources
    # Capture caller-owned inputs/context and referenced file bytes before the
    # solver runs. Exports retain this evidence even if those sources change.
    report_version = 2 if controls else 1
    evidence = build_report_evidence(
        "measured_position_and_size",
        {"drawing": drawing, "measurement_source": measurement_source,
         "datum_frame": datum_frame, "measurement_rows": rows,
         "evaluated_inputs": [asdict(feature) for _, feature in prepared],
         "drawing_controls": controls, "submitted_drawing_controls": drawing_controls},
        settings={"alignment_confirmed": alignment_confirmed is True, "scope_confirmed": scope_confirmed is True},
        units={"length": units}, context=evidence_context, scope=limitations,
        solver="measured_position_size", report_kind_version=report_version,
    ).to_dict()
    results = []
    for control, feature in prepared:
        try:
            evaluation = _evaluate_feature(feature)
        except ValueError as exc:
            if control is None:
                raise
            raise ValueError(f"Drawing control {control['balloon']} ({control['id']}): {exc}") from exc
        result = {"input": asdict(feature), "evaluation": evaluation}
        if control is not None:
            characteristic = control["characteristic"]
            passed = evaluation[f"{characteristic}_conforming"]
            result.update(control_id=control["id"], characteristic=characteristic, requested_control_passes=passed)
            control.update(status="evaluated", passes=passed, evidence={
                "input": asdict(feature), "evaluation": dict(evaluation),
                "requested_check": characteristic,
                "margin": evaluation[f"{characteristic}_margin"], "dataset_datum_frame": datum_frame,
            })
        results.append(result)
    if controls:
        dispositions = [control["passes"] for control in evaluated_controls if control["status"] == "evaluated"]
        passes_supported_checks = all(dispositions) if dispositions else None
    else:
        passes_supported_checks = all(row["evaluation"]["passes"] for row in results)
    return {
        "report_type": "measured_position_and_size", "report_version": report_version,
        "drawing": drawing, "measurement_source": measurement_source,
        "datum_frame": datum_frame, "units": units,
        "alignment_confirmed": alignment_confirmed is True, "scope_confirmed": scope_confirmed is True,
        "passes_supported_checks": passes_supported_checks,
        "features": results, "drawing_controls": evaluated_controls,
        "coverage": drawing_coverage(evaluated_controls), "limitations": limitations,
        "evidence": evidence,
    }
