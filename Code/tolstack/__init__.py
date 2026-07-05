"""
tolstack — herramienta de análisis de tolerance stack-up.

Uso típico:

    from tolstack import Stack, Dimension

    stack = Stack()
    stack.add_dimension(Dimension(name="Base", nominal=25.0, tol_plus=0.10, tol_minus=0.05))
    stack.summary(method="rss")
"""

from .models import Dimension, StackResult, MonteCarloResult
from .stack import Stack

__all__ = [
    "Dimension",
    "StackResult",
    "MonteCarloResult",
    "Stack",
]

__version__ = "0.1.0"
