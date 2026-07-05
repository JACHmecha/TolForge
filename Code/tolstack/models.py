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
    """Representa una dimensión individual dentro de la cadena de tolerancias.

    cpk: capacidad de proceso objetivo para el muestreo Monte Carlo.
        - None (default): muestreo uniforme en [nominal-tol_minus, nominal+tol_plus].
          Es el escenario más pesimista (equivale a un proceso muy poco
          capaz, donde una pieza en el límite de tolerancia es tan probable
          como una en el nominal).
        - float (ej. 1.33): muestreo con distribución normal partida (split
          normal), donde sigma se deriva del Cpk para que el límite de
          tolerancia quede a 3*Cpk desviaciones estándar del nominal, igual
          que en la definición estándar de Cpk en manufactura.
    """
    name: str
    nominal: float
    tol_plus: float
    tol_minus: float
    sign: int = 1
    cpk: float | None = None



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
