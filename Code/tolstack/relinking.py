"""Explain heuristic CAD matches and validate explicit reassignment.

Scores rank geometry within one saved kind; they are not probabilities or
topological identity. Domain definitions and their IDs remain unchanged.
"""

from dataclasses import dataclass
import os
from pathlib import Path
import re

import numpy as np

from .features import FeatureSignature, match_signature, signature_distance


@dataclass(frozen=True)
class RelinkCandidate:
    entity_index: int
    score: float | None
    reasons: tuple[str, ...]
    occupied_by: str | None = None


@dataclass(frozen=True)
class RelinkDiagnostic:
    feature_id: str
    name: str
    kind: str
    status: str
    matched_index: int | None
    confidence: str
    best_score: float | None
    runner_up_score: float | None
    candidates: tuple[RelinkCandidate, ...]
    reason: str


def _comparison_reasons(target, candidate):
    reasons = [f"Center distance {np.linalg.norm(target.center - candidate.center):.6g}"]
    if target.radius is not None and candidate.radius is not None:
        reasons.append(f"Radius difference {abs(target.radius - candidate.radius):.6g}")
    if target.normal is not None and candidate.normal is not None:
        cosine = np.clip(abs(np.dot(target.normal, candidate.normal)), -1, 1)
        reasons.append(f"Axis/normal angle {np.degrees(np.arccos(cosine)):.6g} deg")
    reasons.append("Score combines normalized center/radius and axis angle; lower is closer")
    return tuple(reasons)


def plan_relinking(features, candidates, *, assignments=None, auto_attach=True):
    """Return diagnostics for every saved feature, including unmatchable ones.

Candidates map scene indices to a kind/signature map. Existing assignments
reserve scene entities. Conflicting automatic proposals stay unresolved.
"""
    features = list(features)
    assignments = dict(assignments or {})
    if len(set(assignments.values())) != len(assignments):
        raise ValueError("A loaded entity cannot be assigned to two saved features.")
    owners = {index: feature_id for feature_id, index in assignments.items()}
    diagnostics = []
    for feature in features:
        target = FeatureSignature.from_dict(feature.signature) if feature.signature else None
        if target is not None and target.kind != feature.kind:
            target = None
        ranked = []
        for index, signatures in candidates.items():
            candidate = signatures.get(feature.kind)
            if candidate is None:
                continue
            score = signature_distance(target, candidate) if target is not None else None
            reasons = _comparison_reasons(target, candidate) if target is not None else ("Saved geometric signature is unavailable; explicit assignment required",)
            ranked.append(RelinkCandidate(index, score, reasons, owners.get(index)))
        ranked.sort(key=lambda item: (float("inf") if item.score is None else item.score, item.entity_index))
        eligible = [item for item in ranked if item.occupied_by in (None, feature.id)]
        result = match_signature(target, [candidates[item.entity_index][feature.kind] for item in eligible]) if target else None
        matched = assignments.get(feature.id)
        status = "attached" if matched is not None else "unresolved"
        confidence = "retained" if matched is not None else (result.confidence if result else "none")
        reason = "Explicit or retained assignment" if matched is not None else "No compatible saved signature or candidate"
        if matched is None and result is not None:
            if result.confidence == "ambiguous":
                status, reason = "ambiguous", "Two candidates score too closely for automatic attachment"
            elif result.matched_index is not None:
                reason = "Unique candidate within heuristic threshold"
                if auto_attach:
                    matched, status = eligible[result.matched_index].entity_index, "attached"
            elif result.best_score is not None:
                reason = "Best candidate exceeds the automatic-match threshold"
        diagnostics.append(RelinkDiagnostic(
            feature.id, feature.name, feature.kind, status, matched, confidence,
            result.best_score if result else None, result.runner_up_score if result else None,
            tuple(ranked), reason,
        ))
    proposals = {}
    for item in diagnostics:
        if item.matched_index is not None and item.feature_id not in assignments:
            proposals.setdefault(item.matched_index, []).append(item.feature_id)
    collisions = {index for index, ids in proposals.items() if len(ids) > 1}
    return tuple(RelinkDiagnostic(
        item.feature_id, item.name, item.kind, "ambiguous", None, "ambiguous",
        item.best_score, item.runner_up_score, item.candidates,
        "Multiple saved features propose the same loaded entity; assign explicitly",
    ) if item.matched_index in collisions and item.feature_id not in assignments else item for item in diagnostics)


def validate_manual_assignment(feature, entity_index, candidates, assignments):
    if entity_index not in candidates:
        raise ValueError("The selected entity is no longer in the loaded scene.")
    if feature.kind not in candidates[entity_index]:
        raise ValueError(f"The selected entity is not a {feature.kind} feature.")
    for feature_id, assigned in assignments.items():
        if assigned == entity_index and feature_id != feature.id:
            raise ValueError("The selected loaded entity is already assigned to another saved feature.")
    return candidates[entity_index][feature.kind]


def resolve_source_path(source_file, project_path=None):
    """Resolve relative CAD paths against their engineering project file."""
    if not source_file:
        return None
    path = Path(source_file)
    if not path.is_absolute():
        if project_path is None:
            return None
        path = Path(project_path).resolve().parent / path
    return path.resolve()


def portable_source_path(source_path, project_path):
    path = Path(source_path).resolve()
    try:
        return Path(os.path.relpath(path, Path(project_path).resolve().parent)).as_posix()
    except ValueError:  # Different Windows drives cannot form a relative path.
        return str(path)


def source_revision_status(expected_sha256, loaded_sha256, loaded_hash_status):
    valid = lambda value: isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value) is not None
    if loaded_hash_status != "verified" or not valid(loaded_sha256) or not valid(expected_sha256):
        return "unverified"
    return "unchanged" if expected_sha256.lower() == loaded_sha256.lower() else "changed"
