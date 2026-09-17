"""Engineering-domain entities for TolForge projects.

These classes describe engineering intent without Qt, renderer, or CAD-kernel
objects. Identifiers are UUID strings and are the only supported way to connect
domain objects; names are labels for people, never foreign keys.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import isfinite
from typing import Any, ClassVar
import uuid


def new_id() -> str:
    return uuid.uuid4().hex


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty.")


def _require_finite(value: float, field_name: str) -> None:
    if not isfinite(float(value)):
        raise ValueError(f"{field_name} must be finite.")


@dataclass(frozen=True)
class Units:
    """Units used by every numeric value in a project."""

    length: str = "mm"
    angle: str = "deg"

    LENGTH_UNITS: ClassVar[tuple[str, ...]] = ("mm", "in")
    ANGLE_UNITS: ClassVar[tuple[str, ...]] = ("deg", "rad")

    def __post_init__(self):
        if self.length not in self.LENGTH_UNITS:
            raise ValueError(f"Unsupported length unit '{self.length}'.")
        if self.angle not in self.ANGLE_UNITS:
            raise ValueError(f"Unsupported angle unit '{self.angle}'.")


@dataclass
class Distribution:
    """Manufacturing distribution attached to a tolerance source.

    A shared correlation_group records common-cause variation without forcing
    its future numerical implementation into the persistence schema.
    """

    kind: str = "uniform"
    parameters: dict[str, float] = field(default_factory=dict)
    correlation_group: str | None = None

    KINDS: ClassVar[tuple[str, ...]] = ("fixed", "uniform", "normal", "triangular")

    def __post_init__(self):
        if self.kind not in self.KINDS:
            raise ValueError(f"Unsupported distribution kind '{self.kind}'.")
        for name, value in self.parameters.items():
            _require_finite(value, f"distribution parameter '{name}'")


@dataclass
class PartDefinition:
    name: str
    source_file: str | None = None
    source_sha256: str | None = None
    id: str = field(default_factory=new_id)

    def __post_init__(self):
        _require_text(self.name, "part name")


@dataclass
class RigidTransform:
    """Occurrence pose as translation plus a unit quaternion (w, x, y, z)."""

    translation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0)

    def __post_init__(self):
        if len(self.translation) != 3 or len(self.rotation) != 4:
            raise ValueError("A rigid transform needs 3 translation and 4 quaternion values.")
        for value in (*self.translation, *self.rotation):
            _require_finite(value, "transform value")
        norm_sq = sum(float(value) ** 2 for value in self.rotation)
        if abs(norm_sq - 1.0) > 1e-6:
            raise ValueError("Transform quaternion must have unit length.")


@dataclass
class PartOccurrence:
    part_definition_id: str
    name: str
    transform: RigidTransform = field(default_factory=RigidTransform)
    grounded: bool = False
    id: str = field(default_factory=new_id)

    def __post_init__(self):
        _require_text(self.part_definition_id, "part_definition_id")
        _require_text(self.name, "occurrence name")


@dataclass
class FeatureDefinition:
    """Semantic feature on a part; signature stores its geometric fingerprint."""

    part_definition_id: str
    name: str
    kind: str
    signature: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=new_id)

    KINDS: ClassVar[tuple[str, ...]] = (
        "plane", "cylinder", "circle", "axis", "point", "slot", "surface", "generic"
    )

    def __post_init__(self):
        _require_text(self.part_definition_id, "part_definition_id")
        _require_text(self.name, "feature name")
        if self.kind not in self.KINDS:
            raise ValueError(f"Unsupported feature kind '{self.kind}'.")


@dataclass
class ToleranceDefinition:
    """A source of dimensional or geometric variation."""

    name: str
    kind: str
    nominal: float
    tolerance_plus: float
    tolerance_minus: float
    feature_id: str | None = None
    modifier: str = "RFS"
    distribution: Distribution = field(default_factory=Distribution)
    id: str = field(default_factory=new_id)

    KINDS: ClassVar[tuple[str, ...]] = (
        "size", "distance", "position", "orientation", "form", "profile"
    )
    MODIFIERS: ClassVar[tuple[str, ...]] = ("RFS", "MMC", "LMC")

    def __post_init__(self):
        _require_text(self.name, "tolerance name")
        if self.kind not in self.KINDS:
            raise ValueError(f"Unsupported tolerance kind '{self.kind}'.")
        if self.modifier not in self.MODIFIERS:
            raise ValueError(f"Unsupported material modifier '{self.modifier}'.")
        _require_finite(self.nominal, "nominal")
        _require_finite(self.tolerance_plus, "tolerance_plus")
        _require_finite(self.tolerance_minus, "tolerance_minus")
        if self.tolerance_plus < 0 or self.tolerance_minus < 0:
            raise ValueError("Tolerance magnitudes cannot be negative.")


@dataclass
class StackTerm:
    """One signed use of a tolerance source in a linear stack."""

    tolerance_id: str
    sign: int = 1
    preview_mode: str | None = None
    id: str = field(default_factory=new_id)

    PREVIEW_MODES: ClassVar[tuple[str, ...]] = (
        "diametral", "positional", "normal_offset"
    )

    def __post_init__(self):
        _require_text(self.tolerance_id, "tolerance_id")
        if self.sign not in (-1, 1):
            raise ValueError("Stack-term sign must be +1 or -1.")
        if self.preview_mode is not None and self.preview_mode not in self.PREVIEW_MODES:
            raise ValueError(f"Unsupported preview mode '{self.preview_mode}'.")


@dataclass
class LinearStackDefinition:
    """Ordered signed tolerance chain for one scalar response."""

    name: str
    terms: list[StackTerm] = field(default_factory=list)
    response_id: str | None = None
    id: str = field(default_factory=new_id)

    def __post_init__(self):
        _require_text(self.name, "stack name")
        term_ids = [term.id for term in self.terms]
        if len(term_ids) != len(set(term_ids)):
            raise ValueError("A stack cannot contain duplicate term IDs.")


@dataclass
class DatumReference:
    feature_id: str
    label: str
    modifier: str = "RFS"
    id: str = field(default_factory=new_id)

    def __post_init__(self):
        _require_text(self.feature_id, "feature_id")
        _require_text(self.label, "datum label")
        self.label = self.label.upper()
        if self.modifier not in ToleranceDefinition.MODIFIERS:
            raise ValueError(f"Unsupported datum modifier '{self.modifier}'.")


@dataclass
class DatumSystem:
    """Ordered datum references; list order is precedence order."""

    name: str
    datum_reference_ids: list[str]
    id: str = field(default_factory=new_id)

    def __post_init__(self):
        _require_text(self.name, "datum system name")
        if not self.datum_reference_ids:
            raise ValueError("A datum system needs at least one datum reference.")
        if len(set(self.datum_reference_ids)) != len(self.datum_reference_ids):
            raise ValueError("A datum reference cannot occur twice in one datum system.")


@dataclass
class PositionPatternMember:
    """One semantic feature governed by a position control."""

    name: str
    feature_id: str
    basic_x: float
    basic_y: float
    size_tolerance_id: str
    position_x_tolerance_id: str
    position_y_tolerance_id: str
    id: str = field(default_factory=new_id)

    def __post_init__(self):
        _require_text(self.name, "pattern member name")
        _require_text(self.feature_id, "feature_id")
        _require_text(self.size_tolerance_id, "size_tolerance_id")
        _require_text(self.position_x_tolerance_id, "position_x_tolerance_id")
        _require_text(self.position_y_tolerance_id, "position_y_tolerance_id")
        _require_finite(self.basic_x, "basic_x")
        _require_finite(self.basic_y, "basic_y")


@dataclass
class PositionControlDefinition:
    """Persistent position feature-control frame and its feature pattern."""

    name: str
    datum_system_id: str
    base_tolerance_diameter: float
    modifier: str = "RFS"
    mmc_size: float = 0.0
    lmc_size: float = 0.0
    feature_kind: str = "hole"
    members: list[PositionPatternMember] = field(default_factory=list)
    id: str = field(default_factory=new_id)

    FEATURE_KINDS: ClassVar[tuple[str, ...]] = ("hole", "pin")

    def __post_init__(self):
        _require_text(self.name, "position control name")
        _require_text(self.datum_system_id, "datum_system_id")
        if self.modifier not in ToleranceDefinition.MODIFIERS:
            raise ValueError(f"Unsupported material modifier '{self.modifier}'.")
        if self.feature_kind not in self.FEATURE_KINDS:
            raise ValueError(f"Unsupported feature kind '{self.feature_kind}'.")
        for name, value in (
            ("base_tolerance_diameter", self.base_tolerance_diameter),
            ("mmc_size", self.mmc_size), ("lmc_size", self.lmc_size),
        ):
            _require_finite(value, name)
        if self.base_tolerance_diameter < 0:
            raise ValueError("Position tolerance diameter cannot be negative.")
        member_ids = [member.id for member in self.members]
        if len(member_ids) != len(set(member_ids)):
            raise ValueError("A position control cannot contain duplicate member IDs.")


@dataclass
class AssemblyConstraint:
    """Declarative relationship between two occurrence features."""

    name: str
    kind: str
    occurrence_a_id: str
    feature_a_id: str
    occurrence_b_id: str
    feature_b_id: str
    id: str = field(default_factory=new_id)

    KINDS: ClassVar[tuple[str, ...]] = ("coincident", "concentric", "distance", "contact")

    def __post_init__(self):
        _require_text(self.name, "constraint name")
        if self.kind not in self.KINDS:
            raise ValueError(f"Unsupported constraint kind '{self.kind}'.")


@dataclass
class ResponseDefinition:
    """A key characteristic that an analysis will calculate."""

    name: str
    kind: str
    occurrence_a_id: str
    feature_a_id: str
    occurrence_b_id: str
    feature_b_id: str
    lower_limit: float | None = None
    upper_limit: float | None = None
    id: str = field(default_factory=new_id)

    KINDS: ClassVar[tuple[str, ...]] = ("distance", "clearance", "angle", "overlap")

    def __post_init__(self):
        _require_text(self.name, "response name")
        if self.kind not in self.KINDS:
            raise ValueError(f"Unsupported response kind '{self.kind}'.")
        if self.lower_limit is not None:
            _require_finite(self.lower_limit, "lower_limit")
        if self.upper_limit is not None:
            _require_finite(self.upper_limit, "upper_limit")
        if (
            self.lower_limit is not None and self.upper_limit is not None
            and self.lower_limit > self.upper_limit
        ):
            raise ValueError("Response lower_limit cannot exceed upper_limit.")


def entity_to_dict(entity: Any) -> dict[str, Any]:
    return asdict(entity)
