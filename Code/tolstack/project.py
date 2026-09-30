"""Versioned TolForge project aggregate and JSON persistence."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, TypeVar
from .workflow import validate_study
from .json_data import (
    dumps_strict, loads_strict, require_finite_number, require_text, validate_json_value,
)

from .domain import (
    AssemblyConstraint, DatumReference, DatumSystem, Distribution,
    FeatureDefinition, PartDefinition, PartOccurrence, ResponseDefinition,
    RigidTransform, ToleranceDefinition, Units, new_id,
    LinearStackDefinition, StackTerm,
    PositionControlDefinition, PositionPatternMember, validate_entity,
)


CURRENT_SCHEMA_VERSION = 1
T = TypeVar("T")


@dataclass
class Project:
    """The single source of truth for an engineering analysis project."""

    name: str
    units: Units = field(default_factory=Units)
    id: str = field(default_factory=new_id)
    schema_version: int = CURRENT_SCHEMA_VERSION
    parts: dict[str, PartDefinition] = field(default_factory=dict)
    occurrences: dict[str, PartOccurrence] = field(default_factory=dict)
    features: dict[str, FeatureDefinition] = field(default_factory=dict)
    tolerances: dict[str, ToleranceDefinition] = field(default_factory=dict)
    stacks: dict[str, LinearStackDefinition] = field(default_factory=dict)
    datum_references: dict[str, DatumReference] = field(default_factory=dict)
    datum_systems: dict[str, DatumSystem] = field(default_factory=dict)
    position_controls: dict[str, PositionControlDefinition] = field(default_factory=dict)
    constraints: dict[str, AssemblyConstraint] = field(default_factory=dict)
    responses: dict[str, ResponseDefinition] = field(default_factory=dict)
    study: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self._validate_header()

    def _validate_header(self) -> None:
        require_text(self.name, "Project name")
        require_text(self.id, "Project id")
        validate_entity(self.units, Units)
        if type(self.schema_version) is not int or self.schema_version != CURRENT_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported project schema {self.schema_version}; "
                f"this build supports {CURRENT_SCHEMA_VERSION}."
            )

    @staticmethod
    def _add(collection: dict[str, T], entity: T) -> T:
        if not isinstance(collection, dict):
            raise ValueError("Project entity collections must be objects keyed by id.")
        entity_id = getattr(entity, "id")
        if entity_id in collection:
            raise ValueError(f"Duplicate entity id '{entity_id}'.")
        collection[entity_id] = entity
        return entity

    def add_part(self, entity: PartDefinition) -> PartDefinition:
        validate_entity(entity, PartDefinition)
        return self._add(self.parts, entity)

    def add_occurrence(self, entity: PartOccurrence) -> PartOccurrence:
        validate_entity(entity, PartOccurrence)
        if entity.part_definition_id not in self.parts:
            raise ValueError(f"Unknown part definition '{entity.part_definition_id}'.")
        return self._add(self.occurrences, entity)

    def add_feature(self, entity: FeatureDefinition) -> FeatureDefinition:
        validate_entity(entity, FeatureDefinition)
        if entity.part_definition_id not in self.parts:
            raise ValueError(f"Unknown part definition '{entity.part_definition_id}'.")
        return self._add(self.features, entity)

    def add_tolerance(self, entity: ToleranceDefinition) -> ToleranceDefinition:
        validate_entity(entity, ToleranceDefinition)
        if entity.feature_id is not None and entity.feature_id not in self.features:
            raise ValueError(f"Unknown feature '{entity.feature_id}'.")
        return self._add(self.tolerances, entity)

    def add_stack(self, entity: LinearStackDefinition) -> LinearStackDefinition:
        validate_entity(entity, LinearStackDefinition)
        self._validate_stack(entity)
        return self._add(self.stacks, entity)

    def _validate_stack(self, stack: LinearStackDefinition) -> None:
        for term in stack.terms:
            if term.tolerance_id not in self.tolerances:
                raise ValueError(
                    f"Stack '{stack.id}' references unknown tolerance '{term.tolerance_id}'."
                )
        if stack.response_id is not None and stack.response_id not in self.responses:
            raise ValueError(
                f"Stack '{stack.id}' references unknown response '{stack.response_id}'."
            )

    def add_datum_reference(self, entity: DatumReference) -> DatumReference:
        validate_entity(entity, DatumReference)
        if entity.feature_id not in self.features:
            raise ValueError(f"Unknown feature '{entity.feature_id}'.")
        return self._add(self.datum_references, entity)

    def add_datum_system(self, entity: DatumSystem) -> DatumSystem:
        validate_entity(entity, DatumSystem)
        missing = set(entity.datum_reference_ids) - self.datum_references.keys()
        if missing:
            raise ValueError(f"Unknown datum references: {sorted(missing)}.")
        return self._add(self.datum_systems, entity)

    def add_position_control(
        self, entity: PositionControlDefinition
    ) -> PositionControlDefinition:
        validate_entity(entity, PositionControlDefinition)
        self._validate_position_control(entity)
        return self._add(self.position_controls, entity)

    def _validate_position_control(self, control: PositionControlDefinition) -> None:
        if control.datum_system_id not in self.datum_systems:
            raise ValueError(
                f"Position control '{control.id}' references an unknown datum system."
            )
        for member in control.members:
            if member.feature_id not in self.features:
                raise ValueError(
                    f"Position member '{member.id}' references an unknown feature."
                )
            for tolerance_id in (
                member.size_tolerance_id,
                member.position_x_tolerance_id,
                member.position_y_tolerance_id,
            ):
                if tolerance_id not in self.tolerances:
                    raise ValueError(
                        f"Position member '{member.id}' references unknown tolerance "
                        f"'{tolerance_id}'."
                    )

    def add_constraint(self, entity: AssemblyConstraint) -> AssemblyConstraint:
        validate_entity(entity, AssemblyConstraint)
        self._validate_occurrence_feature_pair(entity.occurrence_a_id, entity.feature_a_id)
        self._validate_occurrence_feature_pair(entity.occurrence_b_id, entity.feature_b_id)
        return self._add(self.constraints, entity)

    def add_response(self, entity: ResponseDefinition) -> ResponseDefinition:
        validate_entity(entity, ResponseDefinition)
        self._validate_occurrence_feature_pair(entity.occurrence_a_id, entity.feature_a_id)
        self._validate_occurrence_feature_pair(entity.occurrence_b_id, entity.feature_b_id)
        return self._add(self.responses, entity)

    def _validate_occurrence_feature_pair(self, occurrence_id: str, feature_id: str) -> None:
        occurrence = self.occurrences.get(occurrence_id)
        if occurrence is None:
            raise ValueError(f"Unknown occurrence '{occurrence_id}'.")
        feature = self.features.get(feature_id)
        if feature is None:
            raise ValueError(f"Unknown feature '{feature_id}'.")
        if feature.part_definition_id != occurrence.part_definition_id:
            raise ValueError(
                f"Feature '{feature_id}' does not belong to occurrence '{occurrence_id}'."
            )

    def validate(self) -> None:
        """Validate current entity content, collection identity and references."""
        self._validate_header()
        for name, entity_type in (
            ("parts", PartDefinition), ("occurrences", PartOccurrence),
            ("features", FeatureDefinition), ("tolerances", ToleranceDefinition),
            ("stacks", LinearStackDefinition), ("datum_references", DatumReference),
            ("datum_systems", DatumSystem), ("position_controls", PositionControlDefinition),
            ("constraints", AssemblyConstraint), ("responses", ResponseDefinition),
        ):
            collection = getattr(self, name)
            if not isinstance(collection, dict):
                raise ValueError(f"Project {name} must be an object keyed by entity id.")
            for entity_id, entity in collection.items():
                require_text(entity_id, f"{name} collection id")
                validate_entity(entity, entity_type)
                if entity_id != entity.id:
                    raise ValueError(f"{name} collection key '{entity_id}' does not match entity id '{entity.id}'.")
        validate_json_value(self.study, "Study settings")
        if isinstance(self.study, dict):
            for key in ("lower_limit", "upper_limit"):
                if key in self.study:
                    require_finite_number(self.study[key], f"Study {key}")
        validate_study(self.study)

        for occurrence in self.occurrences.values():
            if occurrence.part_definition_id not in self.parts:
                raise ValueError(f"Occurrence '{occurrence.id}' references an unknown part.")
        for feature in self.features.values():
            if feature.part_definition_id not in self.parts:
                raise ValueError(f"Feature '{feature.id}' references an unknown part.")
        for tolerance in self.tolerances.values():
            if tolerance.feature_id is not None and tolerance.feature_id not in self.features:
                raise ValueError(f"Tolerance '{tolerance.id}' references an unknown feature.")
        for stack in self.stacks.values():
            self._validate_stack(stack)
        for datum in self.datum_references.values():
            if datum.feature_id not in self.features:
                raise ValueError(f"Datum '{datum.id}' references an unknown feature.")
        for datum_system in self.datum_systems.values():
            missing = set(datum_system.datum_reference_ids) - self.datum_references.keys()
            if missing:
                raise ValueError(f"Datum system '{datum_system.id}' has unknown references.")
        for control in self.position_controls.values():
            self._validate_position_control(control)
        for constraint in self.constraints.values():
            self._validate_occurrence_feature_pair(constraint.occurrence_a_id, constraint.feature_a_id)
            self._validate_occurrence_feature_pair(constraint.occurrence_b_id, constraint.feature_b_id)
        for response in self.responses.values():
            self._validate_occurrence_feature_pair(response.occurrence_a_id, response.feature_a_id)
            self._validate_occurrence_feature_pair(response.occurrence_b_id, response.feature_b_id)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "name": self.name,
            "units": asdict(self.units),
            "parts": _collection_to_list(self.parts),
            "occurrences": _collection_to_list(self.occurrences),
            "features": _collection_to_list(self.features),
            "tolerances": _collection_to_list(self.tolerances),
            "stacks": _collection_to_list(self.stacks),
            "datum_references": _collection_to_list(self.datum_references),
            "datum_systems": _collection_to_list(self.datum_systems),
            "position_controls": _collection_to_list(self.position_controls),
            "constraints": _collection_to_list(self.constraints),
            "responses": _collection_to_list(self.responses),
            "study": dict(self.study),
        }

    @classmethod
    def from_dict(cls, raw_data: dict[str, Any]) -> "Project":
        data = migrate_project_data(raw_data)
        project = cls(
            schema_version=data["schema_version"], id=data["id"], name=data["name"],
            units=Units(**data.get("units", {})),
            parts=_load_collection(data.get("parts", []), PartDefinition),
            occurrences=_load_collection(
                data.get("occurrences", []), PartOccurrence,
                transform=lambda item: {
                    **item,
                    "transform": RigidTransform(
                        translation=tuple(item.get("transform", {}).get("translation", (0, 0, 0))),
                        rotation=tuple(item.get("transform", {}).get("rotation", (1, 0, 0, 0))),
                    ),
                },
            ),
            features=_load_collection(data.get("features", []), FeatureDefinition),
            tolerances=_load_collection(
                data.get("tolerances", []), ToleranceDefinition,
                transform=lambda item: {
                    **item, "distribution": Distribution(**item.get("distribution", {})),
                },
            ),
            stacks=_load_collection(
                data.get("stacks", []), LinearStackDefinition,
                transform=lambda item: {
                    **item,
                    "terms": [StackTerm(**term) for term in item.get("terms", [])],
                },
            ),
            datum_references=_load_collection(data.get("datum_references", []), DatumReference),
            datum_systems=_load_collection(data.get("datum_systems", []), DatumSystem),
            position_controls=_load_collection(
                data.get("position_controls", []), PositionControlDefinition,
                transform=lambda item: {
                    **item,
                    "members": [
                        PositionPatternMember(**member)
                        for member in item.get("members", [])
                    ],
                },
            ),
            constraints=_load_collection(data.get("constraints", []), AssemblyConstraint),
            responses=_load_collection(data.get("responses", []), ResponseDefinition),
            study=data.get("study", {}),
        )
        project.validate()
        return project

    def save(self, path: str | Path) -> None:
        # Complete validation and serialization before opening the destination.
        payload = dumps_strict(self.to_dict())
        Path(path).write_text(payload, encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "Project":
        return cls.from_dict(loads_strict(Path(path).read_text(encoding="utf-8")))


def _collection_to_list(collection: dict[str, Any]) -> list[dict[str, Any]]:
    return [asdict(entity) for entity in collection.values()]


def _load_collection(items: list[dict[str, Any]], cls: type[T], transform=None) -> dict[str, T]:
    if not isinstance(items, list):
        raise ValueError(f"Project {cls.__name__} collection must be a list.")
    result: dict[str, T] = {}
    for raw_item in items:
        if not isinstance(raw_item, dict):
            raise ValueError(f"Project {cls.__name__} entries must be objects.")
        try:
            item = transform(dict(raw_item)) if transform else dict(raw_item)
            entity = cls(**item)
        except (TypeError, AttributeError, KeyError) as exc:
            raise ValueError(f"Invalid {cls.__name__} data: {exc}") from exc
        if entity.id in result:
            raise ValueError(f"Duplicate entity id '{entity.id}' in project file.")
        result[entity.id] = entity
    return result


def migrate_project_data(raw_data: dict[str, Any]) -> dict[str, Any]:
    """Return current-schema data without mutating caller-owned input."""

    if not isinstance(raw_data, dict):
        raise ValueError("Project file must be an object.")
    validate_json_value(raw_data, "Project file")
    data = dict(raw_data)
    version = data.get("schema_version", 0)
    if type(version) is not int:
        raise ValueError("Project schema version must be an integer.")
    if version == CURRENT_SCHEMA_VERSION:
        for key in ("id", "name"):
            require_text(data.get(key), f"Project {key}")
        if not isinstance(data.get("units", {}), dict):
            raise ValueError("Project units must be an object.")
        if set(data.get("units", {})) - {"length", "angle"}:
            raise ValueError("Project units contain unknown fields.")
        return data
    if version == 0:
        raise ValueError(
            "This is not a versioned TolForge project file. Dimension-bank and "
            "annotation JSON files must be imported explicitly, not opened as projects."
        )
    raise ValueError(
        f"Project schema {version} is newer than this build supports "
        f"({CURRENT_SCHEMA_VERSION})."
    )
