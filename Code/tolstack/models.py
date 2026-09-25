"""
Data models for tolerance stack-up analysis.

These dataclasses hold no calculation logic — they just represent the
input data (Dimension) and the results (StackResult, MonteCarloResult)
of the different analysis methods.
"""

from dataclasses import dataclass
from math import isfinite
import numpy as np


@dataclass
class Dimension:
    """Represents a single dimension within the tolerance chain.

    cpk: target process capability for Monte Carlo sampling.
        - None (default): uniform sampling over [nominal-tol_minus, nominal+tol_plus].
          This is the most pessimistic scenario (equivalent to a very
          incapable process, where a part right at the tolerance limit
          is just as likely as one at nominal).
        - float (e.g. 1.33): sampling from a sign-scaled normal distribution,
          where sigma is derived from Cpk so the tolerance limit sits at
          3*Cpk standard deviations from nominal, matching the standard
          manufacturing convention for a centered, symmetric process.
          For asymmetric tolerances this is a sampling parameter, not a
          measured process Cpk; the resulting mean need not equal nominal.
    """
    name: str
    nominal: float
    tol_plus: float
    tol_minus: float
    sign: str = "+"
    cpk: float | None = None


def finite_number(value, label: str) -> float:
    """Convert external numeric input and reject booleans, NaN and infinity."""
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{label} must be a finite number.")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be a finite number.") from exc
    if not isfinite(number):
        raise ValueError(f"{label} must be a finite number.")
    return number


def parse_optional_cpk(value, label: str = "Cpk") -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    number = finite_number(value, label)
    if number <= 0:
        raise ValueError(f"{label} must be greater than 0.")
    return number


def validated_dimension(dimension: Dimension, label: str | None = None) -> Dimension:
    """Return validated plain input without mutating the caller's dimension."""
    label = label or f"Dimension '{dimension.name}'"
    if not isinstance(dimension.name, str) or not dimension.name.strip():
        raise ValueError(f"{label}: name must not be empty.")
    nominal = finite_number(dimension.nominal, f"{label}: nominal")
    plus = finite_number(dimension.tol_plus, f"{label}: positive tolerance")
    minus = finite_number(dimension.tol_minus, f"{label}: negative tolerance")
    if plus < 0 or minus < 0:
        raise ValueError(f"{label}: tolerance magnitudes must be nonnegative.")
    if isinstance(dimension.sign, (bool, np.bool_)):
        raise ValueError(f"{label}: sign must be '+' or '-'.")
    if dimension.sign in ("+", 1, "+1"):
        sign = "+"
    elif dimension.sign in ("-", -1, "-1"):
        sign = "-"
    else:
        raise ValueError(f"{label}: sign must be '+' or '-'.")
    return Dimension(
        dimension.name.strip(), nominal, plus, minus, sign,
        parse_optional_cpk(dimension.cpk, f"{label}: Cpk"),
    )


@dataclass
class StackResult:
    """Result of a Worst Case or RSS analysis."""
    nominal: float
    upper_limit: float
    lower_limit: float


@dataclass
class MonteCarloResult:
    """Result of a Monte Carlo analysis."""
    samples: np.ndarray
    mean: float
    std_dev: float
    minimum: float
    maximum: float


@dataclass
class FitAssessment:
    """Result of comparing a stack result against a target value.

    Convention: positive margin = gap (clearance), negative margin =
    interference. This matches the standard convention in fit analysis,
    where the sign of the stack itself (via each Dimension's `sign`)
    determines what "positive" means for your specific assembly.

    verdict:
        - "gap": the entire result range is >= target (guaranteed clearance).
        - "interference": the entire result range is <= target (guaranteed interference).
        - "mixed": the range straddles the target (some assemblies gap,
          some interfere) — only possible for worst_case/rss, since those
          report a range rather than a probability.

    interference_probability: only populated for Monte Carlo results.
        Fraction of samples below target. None for worst_case/rss, since
        those methods don't produce a distribution to compute this from.
    """
    target: float
    verdict: str
    margin_min: float
    margin_max: float
    interference_probability: float | None = None
