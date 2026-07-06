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

__all__ = [
    "Stack",
    "Dimension",
    "StackResult",
    "MonteCarloResult",
    "FitAssessment",
    "DimensionBank",
    "DimensionTemplate",
]
