"""
Data models for tolerance stack-up analysis.

These dataclasses hold no calculation logic — they just represent the
input data (Dimension) and the results (StackResult, MonteCarloResult)
of the different analysis methods.
"""

from dataclasses import dataclass
import numpy as np


@dataclass
class Dimension:
    """Represents a single dimension within the tolerance chain.

    cpk: target process capability for Monte Carlo sampling.
        - None (default): uniform sampling over [nominal-tol_minus, nominal+tol_plus].
          This is the most pessimistic scenario (equivalent to a very
          incapable process, where a part right at the tolerance limit
          is just as likely as one at nominal).
        - float (e.g. 1.33): sampling from a split normal distribution,
          where sigma is derived from Cpk so the tolerance limit sits at
          3*Cpk standard deviations from nominal, matching the standard
          manufacturing definition of Cpk.
    """
    name: str
    nominal: float
    tol_plus: float
    tol_minus: float
    sign: int = 1
    cpk: float | None = None


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
