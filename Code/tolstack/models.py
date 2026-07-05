"""
Modelos de datos para el análisis de tolerance stack-up.

Estas dataclasses no contienen lógica de cálculo, solo representan
los datos de entrada (Dimension) y los resultados (StackResult,
MonteCarloResult) de los distintos métodos de análisis.
"""

from dataclasses import dataclass
import numpy as np


@dataclass
class Dimension:
    """Representa una dimensión individual dentro de la cadena de tolerancias."""
    name: str
    nominal: float
    tol_plus: float
    tol_minus: float
    sign: int = 1


@dataclass
class StackResult:
    """Resultado de un análisis Worst Case o RSS."""
    nominal: float
    upper_limit: float
    lower_limit: float


@dataclass
class MonteCarloResult:
    """Resultado de un análisis Monte Carlo."""
    samples: np.ndarray
    mean: float
    std_dev: float
    minimum: float
    maximum: float
