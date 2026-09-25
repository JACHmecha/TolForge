"""Position/size inspection of supplied measurements already aligned to a DRF.

This module does not fit measured datums, evaluate form/orientation, or apply
measurement-uncertainty decision rules. It uses the existing bounded model.
"""
from dataclasses import dataclass, asdict
from math import isfinite
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


def evaluate_inspection(rows, *, drawing, measurement_source, datum_frame, units,
                        alignment_confirmed, scope_confirmed):
    """Return a JSON-safe snapshot, keeping measurements separate from CAD."""
    if not all(value.strip() for value in (drawing, measurement_source, datum_frame)):
        raise ValueError("Record drawing/revision, measurement source/part ID, and datum alignment before evaluation.")
    if units not in ("mm", "in"):
        raise ValueError("Inspection units must be mm or in.")
    if not alignment_confirmed:
        raise ValueError("Confirm measurements and basic coordinates use the recorded datum frame and units.")
    if not scope_confirmed:
        raise ValueError("Confirm this is a single-segment position/size check with axes parallel to datum Z and no datum mobility.")
    features = [InspectionFeature.from_row(row) for row in rows]
    if not features:
        raise ValueError("Add at least one measured feature.")
    if len({feature.name for feature in features}) != len(features):
        raise ValueError("Inspection feature names must be unique.")
    results = []
    for feature in features:
        mmc, lmc = ((feature.size_lower, feature.size_upper) if feature.feature_kind == "hole"
                    else (feature.size_upper, feature.size_lower))
        result = evaluate_position(
            feature.measured_x - feature.basic_x, feature.measured_y - feature.basic_y,
            feature.position_tolerance, feature.diameter, mmc, lmc,
            feature.modifier, feature.feature_kind,
        )
        results.append({"input": asdict(feature), "evaluation": asdict(result)})
    return {
        "report_type": "measured_position_and_size", "report_version": 1,
        "drawing": drawing, "measurement_source": measurement_source,
        "datum_frame": datum_frame, "units": units,
        "alignment_confirmed": True, "scope_confirmed": True,
        "passes_supported_checks": all(row["evaluation"]["passes"] for row in results),
        "features": results,
        "limitations": [
            "Supplied measurements are already aligned to the stated datum frame; no measured datum fitting is performed.",
            "Single-segment diametral position and size only; feature axes parallel to datum Z; no datum mobility.",
            "No form, general orientation, composite position or whole-drawing conformance assessment.",
            "No measurement-uncertainty guard band or decision rule is applied; report nominal margins for engineering review.",
            "Independent size check uses supplied diameter, not a complete feature-of-size form/envelope verification.",
        ],
    }
