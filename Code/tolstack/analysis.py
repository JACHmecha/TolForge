"""Qt-independent application service for the supported scalar stack model.

Functional acceptance limits are independent of the zero-clearance fit check.
Contributions are exact variances for the independent input distributions used
by Stack.monte_carlo; they are not 3D GD&T sensitivities or a six-sigma claim.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field, replace
import json
from math import pi, sqrt

import numpy as np

from .models import (
    Dimension, FitAssessment, MonteCarloResult, StackResult,
    finite_number, parse_optional_cpk, validated_dimension,
)
from .stack import Stack
from .reporting import ReportEvidence, build_report_evidence, canonical_json, revise_report_evidence


def build_stack(rows: Iterable[Mapping]) -> Stack:
    """Build a stack from plain row values (including GUI numeric text)."""
    dimensions = []
    for index, row in enumerate(rows):
        try:
            dimension = Dimension(
                name=row["name"], nominal=row["nominal"],
                tol_plus=row["tol_plus"], tol_minus=row["tol_minus"],
                sign=row.get("sign", "+"), cpk=row.get("cpk"),
            )
        except (KeyError, TypeError) as exc:
            raise ValueError(f"Row {index + 1} has incomplete dimension data.") from exc
        dimensions.append(validated_dimension(dimension, f"Row {index + 1}"))
    return Stack(dimensions)


def parse_seed(value) -> int | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text.isascii() or not text.isdecimal():
            raise ValueError("Seed must be an integer from 0 to 4294967295 or empty.")
        value = int(text)
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or not 0 <= value <= 2**32 - 1:
        raise ValueError("Seed must be an integer from 0 to 4294967295 or empty.")
    return int(value)


@dataclass(frozen=True)
class AnalysisSettings:
    method: str = "worst_case"
    lower_limit: float | None = None
    upper_limit: float | None = None
    iterations: int = 10000
    default_cpk: float | None = None
    seed: int | None = None
    response_name: str = "Functional response"

    def __post_init__(self):
        if self.method not in ("worst_case", "rss", "monte_carlo"):
            raise ValueError("Method must be worst_case, rss or monte_carlo.")
        lower, upper = _validated_limits(self.lower_limit, self.upper_limit)
        object.__setattr__(self, "lower_limit", lower)
        object.__setattr__(self, "upper_limit", upper)
        object.__setattr__(self, "default_cpk", parse_optional_cpk(self.default_cpk, "Global Cpk"))
        object.__setattr__(self, "seed", parse_seed(self.seed))
        if isinstance(self.iterations, (bool, np.bool_)) or not isinstance(self.iterations, (int, np.integer)) or self.iterations <= 0:
            raise ValueError("Iterations must be a positive integer.")
        object.__setattr__(self, "iterations", int(self.iterations))
        if not isinstance(self.response_name, str) or not self.response_name.strip():
            raise ValueError("Response name must not be empty.")
        object.__setattr__(self, "response_name", self.response_name.strip())


def _validated_limits(lower, upper) -> tuple[float | None, float | None]:
    lower = None if lower is None else finite_number(lower, "Response lower limit")
    upper = None if upper is None else finite_number(upper, "Response upper limit")
    if lower is not None and upper is not None and lower > upper:
        raise ValueError("Response lower limit cannot exceed the upper limit.")
    return lower, upper


@dataclass(frozen=True)
class ResponseAcceptance:
    lower_limit: float | None
    upper_limit: float | None
    status: str
    sample_count: int | None = None
    rejected_count: int | None = None
    rejection_probability: float | None = None
    rejection_ppm: float | None = None


def assess_acceptance(
    result: StackResult | MonteCarloResult,
    lower_limit: float | None, upper_limit: float | None,
) -> ResponseAcceptance:
    """Check inclusive functional limits without assuming a zero fit target."""
    lower, upper = _validated_limits(lower_limit, upper_limit)
    if lower is None and upper is None:
        return ResponseAcceptance(lower, upper, "not_specified")
    if isinstance(result, MonteCarloResult):
        samples = np.asarray(result.samples)
        if samples.ndim != 1 or not len(samples) or not np.all(np.isfinite(samples)):
            raise ValueError("Acceptance requires a nonempty, finite sample vector.")
        rejected = np.zeros(len(samples), dtype=bool)
        if lower is not None:
            rejected |= samples < lower
        if upper is not None:
            rejected |= samples > upper
        count = int(np.count_nonzero(rejected))
        probability = count / len(samples)
        status = "all_samples_within" if count == 0 else "all_samples_outside" if count == len(samples) else "some_samples_outside"
        return ResponseAcceptance(lower, upper, status, len(samples), count, probability, probability * 1_000_000)
    if not isinstance(result, StackResult):
        raise TypeError("Acceptance expects StackResult or MonteCarloResult.")
    if (lower is None or result.lower_limit >= lower) and (upper is None or result.upper_limit <= upper):
        status = "within_limits"
    elif (lower is not None and result.upper_limit < lower) or (upper is not None and result.lower_limit > upper):
        status = "outside_limits"
    else:
        status = "overlaps_limits"
    return ResponseAcceptance(lower, upper, status)


@dataclass(frozen=True)
class VarianceContribution:
    source_index: int
    name: str
    sensitivity: int
    distribution: str
    cpk: float | None
    expected_source_value: float
    source_variance: float
    response_variance: float
    variance_fraction: float


def rank_contributions(stack: Stack, default_cpk: float | None = None) -> tuple[VarianceContribution, ...]:
    """Exact independent-source variances for the implemented scalar sampler.

    The sign-scaled normal uses equally likely positive/negative standard-normal
    halves. Its mean offset is (sigma_plus-sigma_minus)/sqrt(2*pi), which must be
    subtracted when calculating variance for an asymmetric tolerance.
    """
    default_cpk = parse_optional_cpk(default_cpk, "Global Cpk")
    contributions = []
    for index, raw in enumerate(stack.dimensions):
        dimension = validated_dimension(raw, f"Row {index + 1}")
        cpk = dimension.cpk if dimension.cpk is not None else default_cpk
        if cpk is None:
            offset = (dimension.tol_plus - dimension.tol_minus) / 2
            width = dimension.tol_plus + dimension.tol_minus
            variance = width * (width / 12)
            distribution = "uniform"
        else:
            sigma_plus = dimension.tol_plus / 3 / cpk
            sigma_minus = dimension.tol_minus / 3 / cpk
            offset = (sigma_plus - sigma_minus) / sqrt(2 * pi)
            variance = (sigma_plus * sigma_plus + sigma_minus * sigma_minus) / 2 - offset * offset
            distribution = "sign_scaled_normal"
        variance = finite_number(variance, f"Row {index + 1}: variance")
        sensitivity = Stack._sign_multiplier(dimension.sign)
        contributions.append(VarianceContribution(
            source_index=index, name=dimension.name, sensitivity=sensitivity,
            distribution=distribution, cpk=cpk,
            expected_source_value=finite_number(dimension.nominal + offset, f"Row {index + 1}: expected value"),
            source_variance=variance, response_variance=variance, variance_fraction=0.0,
        ))
    total = finite_number(sum(item.response_variance for item in contributions), "Total variance")
    ranked = [replace(item, variance_fraction=item.response_variance / total if total else 0.0) for item in contributions]
    return tuple(sorted(ranked, key=lambda item: (-item.response_variance, item.source_index)))


@dataclass(frozen=True)
class AnalysisReport:
    settings: AnalysisSettings
    dimensions: tuple[Dimension, ...]
    result: StackResult | MonteCarloResult
    acceptance: ResponseAcceptance
    fit_at_zero: FitAssessment
    contributions: tuple[VarianceContribution, ...]
    assumptions: tuple[str, ...]
    evidence: ReportEvidence | None = None
    _export_json: str = field(init=False, repr=False, compare=False)
    _evaluated_samples: bytes | None = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        if self.evidence is None:
            object.__setattr__(self, "evidence", build_report_evidence(
                "independent_linear_scalar_stack", {"dimensions": [asdict(item) for item in self.dimensions]},
                settings=asdict(self.settings), scope=self.assumptions, solver="independent_scalar_stack",
            ))
        object.__setattr__(self, "_export_json", canonical_json(self._capture_export_payload()))
        # Legacy result objects remain available to callers, but reassessment
        # uses the original sample values even if those objects are edited.
        object.__setattr__(self, "_evaluated_samples", (
            np.asarray(self.result.samples, dtype=np.float64).tobytes()
            if isinstance(self.result, MonteCarloResult) else None
        ))

    def to_dict(self) -> dict:
        """Detached evaluation snapshot, including immutable result summaries."""
        return json.loads(self._export_json)

    def _result_for_reassessment(self):
        """Retain compatible result identity only while its values are intact."""
        summary = self.to_dict()["result"]
        if self._evaluated_samples is None:
            original = StackResult(**summary)
            if isinstance(self.result, StackResult) and asdict(self.result) == summary:
                return self.result
            return original
        samples = np.frombuffer(self._evaluated_samples, dtype=np.float64)
        original = MonteCarloResult(samples=samples, **{
            key: summary[key] for key in ("mean", "std_dev", "minimum", "maximum")
        })
        if (isinstance(self.result, MonteCarloResult)
                and all(getattr(self.result, key) == getattr(original, key)
                        for key in ("mean", "std_dev", "minimum", "maximum"))
                and np.array_equal(self.result.samples, samples)):
            return self.result
        return original

    def _capture_export_payload(self) -> dict:
        """Capture once at construction; reassessment constructs a new report."""
        if isinstance(self.result, MonteCarloResult):
            result = {
                "sample_count": len(self.result.samples), "mean": float(self.result.mean),
                "std_dev": float(self.result.std_dev), "minimum": float(self.result.minimum),
                "maximum": float(self.result.maximum),
            }
        else:
            result = asdict(self.result)
        payload = {
            "analysis_kind": "independent_linear_scalar_stack", "settings": asdict(self.settings),
            "dimensions": [asdict(item) for item in self.dimensions], "result": result,
            "acceptance": asdict(self.acceptance), "fit_at_zero": asdict(self.fit_at_zero),
            "contributions": [asdict(item) for item in self.contributions],
            "expected_response": sum(item.sensitivity * item.expected_source_value for item in self.contributions),
            "expected_variance": sum(item.response_variance for item in self.contributions),
            "assumptions": list(self.assumptions),
        }
        if self.evidence is not None:
            evidence = self.evidence.to_dict()
            # Export the captured inputs, even if a consumer mutates one of the
            # legacy mutable Dimension objects held by this frozen dataclass.
            payload["dimensions"] = evidence["input_snapshot"]["inputs"]["dimensions"]
            payload["settings"] = evidence["input_snapshot"]["settings"]
            payload["evidence"] = evidence
        return payload


def update_report_limits(report: AnalysisReport, lower, upper, *, assumptions=None) -> AnalysisReport:
    """Reassess an existing result without resampling when limits are edited."""
    snapshot = report.to_dict()
    original_settings = AnalysisSettings(**snapshot["settings"])
    settings = replace(original_settings, lower_limit=lower, upper_limit=upper)
    original_assumptions = tuple(snapshot["assumptions"])
    revised_assumptions = original_assumptions if assumptions is None else tuple(assumptions)
    if settings == original_settings and revised_assumptions == original_assumptions:
        return report
    evidence = (revise_report_evidence(report.evidence, settings=asdict(settings), scope=revised_assumptions)
                if report.evidence is not None else None)
    result = report._result_for_reassessment()
    return AnalysisReport(
        settings=settings, dimensions=tuple(Dimension(**item) for item in snapshot["dimensions"]),
        result=result, acceptance=assess_acceptance(result, lower, upper),
        fit_at_zero=FitAssessment(**snapshot["fit_at_zero"]),
        contributions=tuple(VarianceContribution(**item) for item in snapshot["contributions"]),
        assumptions=revised_assumptions, evidence=evidence,
    )


def analyze_stack(stack: Stack, settings: AnalysisSettings | None = None, *, report_context=None) -> AnalysisReport:
    settings = settings or AnalysisSettings()
    dimensions = tuple(validated_dimension(d, f"Row {i + 1}") for i, d in enumerate(stack.dimensions))
    if not dimensions:
        raise ValueError("Add at least one dimension.")
    assumptions = [
        "Linear scalar response; independent sources; sensitivity coefficients are +1 or -1.",
        "Contribution ranking uses exact model variances, including asymmetric mean shifts.",
        "A supplied Cpk is a sampling assumption, not measured process capability; asymmetric tolerances use sign-scaled normal samples.",
        "Zero-clearance fit is separate from the functional response acceptance limits.",
    ]
    if settings.method == "rss":
        assumptions.append("RSS is an engineering tolerance-band estimate, not a guaranteed bound or a calibrated yield prediction.")
    elif settings.method == "monte_carlo":
        assumptions.append("Yield and PPM are empirical sample estimates; zero observed rejects does not establish zero failure risk or six-sigma performance.")
        assumptions.append("Normal samples are unbounded and are not clipped to drawing tolerance limits.")
    else:
        assumptions.append("Worst-case limits bound inputs inside drawing tolerances, not unbounded normal process samples.")
    evidence = build_report_evidence(
        "independent_linear_scalar_stack", {"dimensions": [asdict(item) for item in dimensions]},
        settings=asdict(settings), units=(report_context or {}).get("units"),
        context=report_context, scope=assumptions, solver="independent_scalar_stack",
    )
    validated = Stack(list(dimensions))
    contributions = rank_contributions(validated, settings.default_cpk)
    if settings.method == "monte_carlo":
        result = validated.monte_carlo(settings.iterations, settings.default_cpk, seed=settings.seed)
    elif settings.method == "rss":
        result = validated.rss()
    else:
        result = validated.worst_case()
    summary_values = (result.mean, result.std_dev, result.minimum, result.maximum) if isinstance(result, MonteCarloResult) else (result.nominal, result.lower_limit, result.upper_limit)
    for value in summary_values:
        finite_number(value, "Analysis result (check input magnitude)")
    return AnalysisReport(
        settings=settings, dimensions=dimensions, result=result,
        acceptance=assess_acceptance(result, settings.lower_limit, settings.upper_limit),
        fit_at_zero=validated.assess_fit(result, 0.0),
        contributions=contributions,
        assumptions=tuple(assumptions),
        evidence=evidence,
    )
