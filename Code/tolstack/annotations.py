"""GD&T annotation domain model - the persistent source of truth for
datums, position controls, and dimension-to-feature links.

Design principle: this module holds NO UI state. Everything here is
plain data plus (de)serialization - which slider is where, which scene
object currently represents which feature, and so on all lives in the
GUI layer and is derived from an AnnotationSet at runtime, not the other
way around. That's deliberate: it's what makes "save this part's GD&T
annotations", "reload the STEP and re-match everything", and "run an
analysis against these annotations from a script, no GUI involved" all
possible without three different sources of truth quietly drifting apart
from each other.

Every reference to a feature goes through a FeatureReference, which wraps
a FeatureSignature (see features.py) rather than any kind of index or
object id - that's what survives a STEP reload. FeatureReference.id (a
UUID, not the feature's index) is the stable key annotations actually
point to internally, so an annotation keeps working even if a
FeatureReference's underlying signature later gets updated after a
successful re-match.
"""

from dataclasses import dataclass, field
import uuid
from pathlib import Path

from .features import FeatureSignature
from .json_data import loads_strict
from .persistence import backup_path, save_json

_MODIFIERS = ("RFS", "MMC", "LMC")
_FEATURE_KINDS = ("hole", "pin")
_LINK_MODES = ("diametral", "positional", "normal_offset")


def _new_id() -> str:
    return uuid.uuid4().hex


@dataclass
class FeatureReference:
    """A persistent handle to a STEP feature. `id` is what everything
    else in this module actually links to; `signature` is what
    match_signature() compares against on reload to find the feature
    again; `label` and `part_name` are purely informational (shown to the
    user, never used for matching)."""

    signature: FeatureSignature
    label: str = ""
    part_name: str | None = None
    id: str = field(default_factory=_new_id)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "label": self.label, "part_name": self.part_name,
            "signature": self.signature.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FeatureReference":
        return cls(
            id=data["id"], label=data.get("label", ""), part_name=data.get("part_name"),
            signature=FeatureSignature.from_dict(data["signature"]),
        )


@dataclass
class DatumDefinition:
    """A GD&T datum letter (A, B, C, ...) bound to a feature. The letter
    is the datum's own persistent identity - reusable across multiple
    position controls - separate from the Primary/Secondary/Tertiary
    ROLE it plays within any one control (that role is recorded on
    PositionControlDefinition, not here)."""

    letter: str
    feature_ref_id: str  # FeatureReference.id

    def to_dict(self) -> dict:
        return {"letter": self.letter, "feature_ref_id": self.feature_ref_id}

    @classmethod
    def from_dict(cls, data: dict) -> "DatumDefinition":
        return cls(letter=data["letter"], feature_ref_id=data["feature_ref_id"])


@dataclass
class PatternFeatureDefinition:
    """One feature within a position control's pattern - mirrors
    tolstack.gdt.PatternFeature's basic_x/basic_y, but references a
    persistent FeatureReference instead of carrying the as-measured
    location directly (that gets re-derived from wherever the referenced
    feature currently is, each time the control is evaluated)."""

    name: str
    feature_ref_id: str
    basic_x: float
    basic_y: float

    def to_dict(self) -> dict:
        return {
            "name": self.name, "feature_ref_id": self.feature_ref_id,
            "basic_x": self.basic_x, "basic_y": self.basic_y,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PatternFeatureDefinition":
        return cls(
            name=data["name"], feature_ref_id=data["feature_ref_id"],
            basic_x=float(data["basic_x"]), basic_y=float(data["basic_y"]),
        )


@dataclass
class PositionControlDefinition:
    """A GD&T position (\u2316) callout: three datums in precedence order,
    a diametral tolerance zone, an optional MMC/LMC modifier, and the
    pattern of features it controls. This is the persistent counterpart
    of tolstack.gdt.PatternPositionControl - that class stays as the pure
    evaluation engine (it doesn't need to know about persistence at all);
    this class is what gets saved, and produces a PatternPositionControl
    (via the GUI layer, which resolves feature_ref_ids against whatever's
    currently loaded) when it's time to actually evaluate.
    """

    name: str
    primary_datum: DatumDefinition
    secondary_datum: DatumDefinition
    tertiary_datum: DatumDefinition
    base_tolerance_diameter: float
    modifier: str = "RFS"
    mmc_size: float = 0.0
    lmc_size: float = 0.0
    feature_kind: str = "hole"
    features: list = field(default_factory=list)  # list[PatternFeatureDefinition]
    id: str = field(default_factory=_new_id)

    def __post_init__(self):
        if self.modifier not in _MODIFIERS:
            raise ValueError(f"modifier must be one of {_MODIFIERS}, not '{self.modifier}'.")
        if self.feature_kind not in _FEATURE_KINDS:
            raise ValueError(f"feature_kind must be one of {_FEATURE_KINDS}, not '{self.feature_kind}'.")

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name,
            "primary_datum": self.primary_datum.to_dict(),
            "secondary_datum": self.secondary_datum.to_dict(),
            "tertiary_datum": self.tertiary_datum.to_dict(),
            "base_tolerance_diameter": self.base_tolerance_diameter,
            "modifier": self.modifier, "mmc_size": self.mmc_size, "lmc_size": self.lmc_size,
            "feature_kind": self.feature_kind,
            "features": [f.to_dict() for f in self.features],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PositionControlDefinition":
        return cls(
            id=data["id"], name=data["name"],
            primary_datum=DatumDefinition.from_dict(data["primary_datum"]),
            secondary_datum=DatumDefinition.from_dict(data["secondary_datum"]),
            tertiary_datum=DatumDefinition.from_dict(data["tertiary_datum"]),
            base_tolerance_diameter=float(data["base_tolerance_diameter"]),
            modifier=data.get("modifier", "RFS"),
            mmc_size=float(data.get("mmc_size", 0.0)), lmc_size=float(data.get("lmc_size", 0.0)),
            feature_kind=data.get("feature_kind", "hole"),
            features=[PatternFeatureDefinition.from_dict(f) for f in data.get("features", [])],
        )


@dataclass
class DimensionLinkDefinition:
    """Links a Stack Table dimension (by name) to a persistent feature
    reference and a visualization mode - the persistent counterpart of
    the link dict StackLinkMixin currently stores directly on a
    QTableWidgetItem via Qt.UserRole.
    """

    dimension_name: str
    feature_ref_id: str
    mode: str
    id: str = field(default_factory=_new_id)

    def __post_init__(self):
        if self.mode not in _LINK_MODES:
            raise ValueError(f"mode must be one of {_LINK_MODES}, not '{self.mode}'.")

    def to_dict(self) -> dict:
        return {
            "id": self.id, "dimension_name": self.dimension_name,
            "feature_ref_id": self.feature_ref_id, "mode": self.mode,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DimensionLinkDefinition":
        return cls(
            id=data["id"], dimension_name=data["dimension_name"],
            feature_ref_id=data["feature_ref_id"], mode=data["mode"],
        )


@dataclass
class AnnotationSet:
    """The full, persistent set of GD&T annotations for a part. This is
    what gets saved/loaded as a project file - everything else (which
    scene object is highlighted, which slider is at what position) is
    UI-layer state derived from this, not stored here.
    """

    feature_refs: dict = field(default_factory=dict)       # FeatureReference.id -> FeatureReference
    position_controls: list = field(default_factory=list)  # list[PositionControlDefinition]
    dimension_links: list = field(default_factory=list)    # list[DimensionLinkDefinition]
    source_file: str | None = None  # path/name of the STEP file this was authored against, informational

    def add_feature_ref(self, ref: FeatureReference) -> FeatureReference:
        self.feature_refs[ref.id] = ref
        return ref

    def get_feature_ref(self, ref_id: str) -> FeatureReference | None:
        return self.feature_refs.get(ref_id)

    def remove_feature_ref(self, ref_id: str):
        """Also cleans up anything that referenced it:
        - A position control loses just the one pattern feature that
          pointed at it (the control itself still works with what's
          left) - UNLESS ref_id was one of its three datums, in which
          case the whole control is no longer usable and is dropped.
        - Any dimension link pointing at it is dropped.
        """
        self.feature_refs.pop(ref_id, None)

        surviving_controls = []
        for control in self.position_controls:
            datum_ids = (
                control.primary_datum.feature_ref_id,
                control.secondary_datum.feature_ref_id,
                control.tertiary_datum.feature_ref_id,
            )
            if ref_id in datum_ids:
                continue  # a datum this control depends on is gone - drop the whole control
            control.features = [f for f in control.features if f.feature_ref_id != ref_id]
            surviving_controls.append(control)
        self.position_controls = surviving_controls

        self.dimension_links = [dl for dl in self.dimension_links if dl.feature_ref_id != ref_id]

    def to_dict(self) -> dict:
        return {
            "source_file": self.source_file,
            "feature_refs": {ref_id: ref.to_dict() for ref_id, ref in self.feature_refs.items()},
            "position_controls": [pc.to_dict() for pc in self.position_controls],
            "dimension_links": [dl.to_dict() for dl in self.dimension_links],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AnnotationSet":
        if not isinstance(data, dict):
            raise ValueError("Annotation file must be an object.")
        try:
            return cls(
                source_file=data.get("source_file"),
                feature_refs={
                    ref_id: FeatureReference.from_dict(ref_data)
                    for ref_id, ref_data in data.get("feature_refs", {}).items()
                },
                position_controls=[PositionControlDefinition.from_dict(pc) for pc in data.get("position_controls", [])],
                dimension_links=[DimensionLinkDefinition.from_dict(dl) for dl in data.get("dimension_links", [])],
            )
        except (AttributeError, KeyError, TypeError) as exc:
            raise ValueError(f"Invalid annotation file structure: {exc}") from exc

    def save(self, path: str):
        save_json(path, self.to_dict(), previous_validator=type(self).from_dict)

    @classmethod
    def load(cls, path: str) -> "AnnotationSet":
        return cls.from_dict(loads_strict(Path(path).read_text(encoding="utf-8")))

    @classmethod
    def load_previous(cls, path: str) -> "AnnotationSet":
        return cls.load(backup_path(path))
