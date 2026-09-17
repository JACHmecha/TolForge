"""tolstack package public API.

Expose core classes from the submodules without executing any
top-level test code when the package is imported. The original
file contained ad-hoc test/demo code that ran on import which
caused unexpected side-effects for consumers (for example the GUI
app). Keep this module lightweight and only export symbols.
"""

from .stack import Stack
from .models import (
    Dimension, StackResult, MonteCarloResult, FitAssessment
)
from .bank import DimensionBank, DimensionTemplate

from .domain import (
    AssemblyConstraint, DatumReference, DatumSystem, Distribution,
    FeatureDefinition, PartDefinition, PartOccurrence, ResponseDefinition,
    RigidTransform, ToleranceDefinition, Units, LinearStackDefinition, StackTerm,
    PositionControlDefinition, PositionPatternMember,
)
from .project import CURRENT_SCHEMA_VERSION, Project
from .gdt import (
    PinHoleClearanceEvaluation, actual_mating_boundary,
    evaluate_pin_hole_clearance, size_limits, size_margin, virtual_condition,
)

__all__ = [
    "Stack",
    "Dimension",
    "StackResult",
    "MonteCarloResult",
    "FitAssessment",
    "DimensionBank",
    "DimensionTemplate",
    "AssemblyConstraint",
    "DatumReference",
    "DatumSystem",
    "Distribution",
    "FeatureDefinition",
    "PartDefinition",
    "PartOccurrence",
    "ResponseDefinition",
    "RigidTransform",
    "ToleranceDefinition",
    "LinearStackDefinition",
    "StackTerm",
    "PositionControlDefinition",
    "PositionPatternMember",
    "Units",
    "CURRENT_SCHEMA_VERSION",
    "Project",
    "PinHoleClearanceEvaluation",
    "actual_mating_boundary",
    "evaluate_pin_hole_clearance",
    "size_limits",
    "size_margin",
    "virtual_condition",
]
