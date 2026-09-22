"""Persistent geometric feature identity.

The problem this solves: everywhere else in this app, a "feature" is
identified by id(scene_object) or by (entity_type, entity_index) - both
are only stable within a single load of a single STEP file. Reload the
same file (even unchanged) and there's no guarantee OCCT's face/edge
ordering comes back identical; load a revised version of the design and
the ordering is even less likely to match. Any annotation (a datum, a
GD&T control, a dimension-to-feature link) that's meant to persist across
reloads or be saved as part of a project needs something else to hang
onto.

FeatureSignature is that something else: a small, tolerance-comparable
geometric fingerprint (kind, center, normal, radius, rough size/point
count) computed once when a feature is picked. On reload, fresh
signatures are computed for every currently-loaded entity and matched
against each saved signature by geometric proximity - not by any kind of
topological ID. This is a heuristic, not a solved problem (real
topological naming is a genuinely hard problem even in mature CAD
kernels) - match_signature() reports its own confidence (exact/good/
ambiguous/none) rather than pretending certainty it doesn't have, so the
caller can prompt for manual re-linking when confidence is low instead
of silently attaching an annotation to the wrong feature.
"""

from dataclasses import dataclass
import numpy as np

# Kinds a signature can represent - deliberately coarse; enough to avoid
# comparing a circle's signature against a plane's, not a full geometry
# classification.
_KINDS = ("circle", "cylinder", "plane", "point", "generic")


@dataclass
class FeatureSignature:
    kind: str
    center: np.ndarray
    normal: np.ndarray | None  # None for "point" and some "generic" cases
    radius: float | None       # meaningful for "circle" and "cylinder"
    point_count: int           # rough tessellation-density fingerprint, tie-breaker only
    bbox_diagonal: float       # size scale of the point cloud this was fit from

    def __post_init__(self):
        if self.kind not in _KINDS:
            raise ValueError(f"Unknown signature kind '{self.kind}', expected one of {_KINDS}.")
        self.center = np.asarray(self.center, dtype=float)
        if self.normal is not None:
            norm = np.linalg.norm(self.normal)
            self.normal = np.asarray(self.normal, dtype=float) / norm if norm > 0 else None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "center": self.center.tolist(),
            "normal": self.normal.tolist() if self.normal is not None else None,
            "radius": self.radius,
            "point_count": self.point_count,
            "bbox_diagonal": self.bbox_diagonal,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FeatureSignature":
        return cls(
            kind=data["kind"],
            center=np.array(data["center"], dtype=float),
            normal=np.array(data["normal"], dtype=float) if data.get("normal") is not None else None,
            radius=data.get("radius"),
            point_count=int(data.get("point_count", 0)),
            bbox_diagonal=float(data.get("bbox_diagonal", 0.0)),
        )


def signature_from_points(
    entity_type: str, points: np.ndarray, circle_fit: dict | None = None,
    surface: dict | None = None,
) -> FeatureSignature | None:
    """Builds a signature from whatever a pick already produces elsewhere
    in this app: raw tessellation points, plus an optional circle fit
    (center/radius/normal) and optional analytic surface metadata. Cylinders
    use their analytic axis/radius and the midpoint of the axial point extent.
    Returns None if there isn't enough here to build anything meaningful
    (fewer than 1 point).
    """
    points = np.asarray(points, dtype=float)
    if len(points) == 0:
        return None

    bbox_diagonal = float(np.linalg.norm(points.max(axis=0) - points.min(axis=0)))

    if surface and surface.get("kind") == "cylinder":
        axis = np.asarray(surface["direction"], dtype=float)
        axis /= np.linalg.norm(axis)
        point = np.asarray(surface["point"], dtype=float)
        # Midpoint of axial extent is invariant to mesh point density and to
        # where the CAD kernel chooses an arbitrary point on the axis.
        stations = (points - point) @ axis
        center = point + axis * (stations.min() + stations.max()) / 2
        return FeatureSignature("cylinder", center, axis, surface["radius"], len(points), bbox_diagonal)

    if circle_fit is not None:
        return FeatureSignature(
            kind="circle", center=circle_fit["center"], normal=circle_fit["normal"],
            radius=circle_fit["radius"], point_count=len(points), bbox_diagonal=bbox_diagonal,
        )

    if entity_type == "vertex":
        return FeatureSignature(
            kind="point", center=points[0], normal=None, radius=None,
            point_count=1, bbox_diagonal=0.0,
        )

    if entity_type == "face" and len(points) >= 3:
        centroid = points.mean(axis=0)
        centered = points - centroid
        try:
            _u, _s, vt = np.linalg.svd(centered, full_matrices=False)
            normal = vt[-1]
        except np.linalg.LinAlgError:
            normal = None
        return FeatureSignature(
            kind="plane", center=centroid, normal=normal, radius=None,
            point_count=len(points), bbox_diagonal=bbox_diagonal,
        )

    # Fallback for edges that aren't circular, solids, or anything else -
    # just a centroid + rough size, no direction. Still usable for
    # matching (position + size), just a weaker fingerprint.
    return FeatureSignature(
        kind="generic", center=points.mean(axis=0), normal=None, radius=None,
        point_count=len(points), bbox_diagonal=bbox_diagonal,
    )


def signature_distance(a: FeatureSignature, b: FeatureSignature) -> float | None:
    """A ranking score for how well two SAME-kind signatures match - 0 is
    identical, larger is worse. Not a normalized/calibrated metric across
    kinds (don't compare scores from different kind pairs), and there's
    no fixed upper bound - only meant for ranking candidates against one
    target, which is exactly what match_signature() below does. Returns
    None if the kinds differ (shouldn't be compared at all).

    Every term is normalized by bbox_diagonal so the score is roughly
    scale-independent (a 1mm miss matters a lot on a 5mm feature, barely
    at all on a 500mm one).
    """
    if a.kind != b.kind:
        return None

    scale = max(a.bbox_diagonal, b.bbox_diagonal, 1e-9)
    score = float(np.linalg.norm(a.center - b.center)) / scale

    if a.radius is not None and b.radius is not None:
        score += abs(a.radius - b.radius) / scale

    if a.normal is not None and b.normal is not None:
        cos_angle = np.clip(abs(np.dot(a.normal, b.normal)), -1.0, 1.0)
        angle_deg = float(np.degrees(np.arccos(cos_angle)))
        score += angle_deg / 90.0

    return score


@dataclass
class MatchResult:
    matched_index: int | None      # index into the `candidates` list passed to match_signature()
    confidence: str                # "exact" | "good" | "ambiguous" | "none"
    best_score: float | None
    runner_up_score: float | None  # None if there was only one (or zero) candidates of this kind


def match_signature(
    target: FeatureSignature, candidates: list, max_score: float = 0.15, ambiguity_margin: float = 0.03,
) -> MatchResult:
    """Finds the best-matching candidate signature for `target`.

    - "none": nothing scored under max_score - no confident match exists
      (the feature was probably removed/changed beyond recognition).
    - "ambiguous": the best match exists, but a second candidate scored
      close enough behind it (within ambiguity_margin) that picking the
      best one automatically would be a guess, not a match - e.g. two
      very similar, closely-spaced holes. The caller should prompt for
      manual disambiguation rather than silently taking the top score.
    - "good" / "exact": a confident, unambiguous match; "exact" only for
      a near-perfect score (< 10% of max_score), "good" otherwise.
    """
    scored = []
    for i, candidate in enumerate(candidates):
        d = signature_distance(target, candidate)
        if d is not None:
            scored.append((i, d))

    if not scored:
        return MatchResult(None, "none", None, None)

    scored.sort(key=lambda pair: pair[1])
    best_index, best_score = scored[0]
    runner_up_score = scored[1][1] if len(scored) > 1 else None

    if best_score > max_score:
        return MatchResult(None, "none", best_score, runner_up_score)

    if runner_up_score is not None and (runner_up_score - best_score) < ambiguity_margin:
        return MatchResult(best_index, "ambiguous", best_score, runner_up_score)

    confidence = "exact" if best_score < max_score * 0.1 else "good"
    return MatchResult(best_index, confidence, best_score, runner_up_score)
