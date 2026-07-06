"""
Calculation logic for the tolerance stack-up.

Contains the Stack class, which manages a list of Dimension objects and
offers the three analysis methods: worst_case, rss, and monte_carlo.
"""

from dataclasses import dataclass, field
import numpy as np

from .models import Dimension, StackResult, MonteCarloResult, FitAssessment

# Valid methods for summary(); normalized to lowercase before comparing.
_VALID_METHODS = ("worst_case", "rss", "monte_carlo")


@dataclass
class Stack:
    dimensions: list[Dimension] = field(default_factory=list)

    def add_dimension(self, dimension: Dimension):
        """Adds a dimension to the chain."""
        self.dimensions.append(dimension)

    def remove_dimension(self, name: str):
        """Removes a dimension by name."""
        self.dimensions = [
            d for d in self.dimensions if d.name != name
        ]

    def nominal(self):
        """Calculates the resulting nominal dimension."""
        return sum(d.sign * d.nominal for d in self.dimensions)

    def worst_case(self) -> StackResult:
        """Calculates the Worst Case limits of the stack-up."""
        nominal = self.nominal()
        upper = nominal
        lower = nominal

        for d in self.dimensions:
            if d.sign > 0:
                upper += d.tol_plus
                lower -= d.tol_minus
            else:
                upper += d.tol_minus
                lower -= d.tol_plus

        return StackResult(nominal=nominal, upper_limit=upper, lower_limit=lower)

    def rss(self) -> StackResult:
        """Calculates the RSS limits of the stack-up."""
        nominal = self.nominal()
        upper_rss = 0.0
        lower_rss = 0.0

        for d in self.dimensions:
            if d.sign > 0:
                upper_rss += d.tol_plus**2
                lower_rss += d.tol_minus**2
            else:
                upper_rss += d.tol_minus**2
                lower_rss += d.tol_plus**2

        upper_rss = upper_rss**0.5
        lower_rss = lower_rss**0.5

        return StackResult(
            nominal=nominal,
            upper_limit=nominal + upper_rss,
            lower_limit=nominal - lower_rss
        )

    def monte_carlo(self, iterations=10000, default_cpk: float | None = None) -> MonteCarloResult:
        """Runs a Monte Carlo analysis of the stack-up.

        Per dimension, the sampling depends on `Dimension.cpk`:
        - `cpk is None` (default): uniform distribution over the entire
          tolerance range. This is the most pessimistic case and doesn't
          represent a real manufacturing process.
        - `cpk` set (e.g. 1.33, 1.67, 2.0): split normal distribution,
          calibrated so the tolerance limit sits at `3 * cpk` standard
          deviations from nominal, following the standard Cpk definition.

        `default_cpk`: if a dimension doesn't carry its own `cpk`, this
        value is applied instead of falling back to uniform. Useful for
        running the whole stack under a single homogeneous process
        assumption without editing every Dimension.
        """
        samples = np.zeros(iterations)

        for d in self.dimensions:
            cpk = d.cpk if d.cpk is not None else default_cpk

            if cpk is None:
                values = np.random.uniform(
                    d.nominal - d.tol_minus,
                    d.nominal + d.tol_plus,
                    iterations
                )
            else:
                if cpk <= 0:
                    raise ValueError(
                        f"Cpk for '{d.name}' must be > 0, not {cpk}."
                    )
                sigma_plus = d.tol_plus / (3 * cpk)
                sigma_minus = d.tol_minus / (3 * cpk)

                z = np.random.standard_normal(iterations)
                offsets = np.where(z >= 0, z * sigma_plus, z * sigma_minus)
                values = d.nominal + offsets

            samples += d.sign * values

        return MonteCarloResult(
            samples=samples,
            mean=np.mean(samples),
            std_dev=np.std(samples),
            minimum=np.min(samples),
            maximum=np.max(samples)
        )

    def summary(self, method: str = "worst_case", default_cpk: float | None = None):
        """Prints a summary of the stack.

        Note: `method` is normalized to lowercase, so "RSS", "rss", and
        "Rss" are equivalent. Invalid methods raise ValueError instead of
        failing silently with an undefined result.
        """
        method = method.lower()

        if method not in _VALID_METHODS:
            raise ValueError(
                f"Method '{method}' not recognized. Use one of: {_VALID_METHODS}"
            )

        print("----- STACK SUMMARY -----")

        for d in self.dimensions:
            sign = "+" if d.sign > 0 else "-"
            print(
                f"{sign} {d.name:15}"
                f"{d.nominal:8.3f}"
                f"  +{d.tol_plus:.3f}"
                f"  -{d.tol_minus:.3f}"
            )

        if method == "monte_carlo":
            result = self.monte_carlo(default_cpk=default_cpk)
            print("-------------------------")
            print(f"Mean      : {result.mean:.3f}")
            print(f"Std Dev   : {result.std_dev:.3f}")
            print(f"Minimum   : {result.minimum:.3f}")
            print(f"Maximum   : {result.maximum:.3f}")
            return

        result = self.worst_case() if method == "worst_case" else self.rss()

        print("-------------------------")
        print(f"Nominal : {result.nominal:.3f}")
        print(f"Maximum : {result.upper_limit:.3f}")
        print(f"Minimum : {result.lower_limit:.3f}")
        print(f"+Tol    : {result.upper_limit - result.nominal:.3f}")
        print(f"-Tol    : {result.nominal - result.lower_limit:.3f}")

    def assess_fit(self, result, target: float = 0.0) -> FitAssessment:
        """Compares a stack result against a target and classifies the fit.

        Convention: positive margin = gap, negative margin = interference.
        `result` can be a StackResult (worst_case/rss) or a MonteCarloResult.

        For StackResult: classifies the whole range as "gap", "interference",
        or "mixed" (straddles target — some assemblies gap, some interfere).

        For MonteCarloResult: additionally computes the fraction of samples
        that fall below target (interference_probability), which is the
        actual point of running Monte Carlo for a fit analysis instead of
        just worst_case/rss — you get a probability, not just a verdict.
        """
        if isinstance(result, MonteCarloResult):
            interference_probability = float(np.mean(result.samples < target))

            if interference_probability == 0.0:
                verdict = "gap"
            elif interference_probability == 1.0:
                verdict = "interference"
            else:
                verdict = "mixed"

            return FitAssessment(
                target=target,
                verdict=verdict,
                margin_min=result.minimum - target,
                margin_max=result.maximum - target,
                interference_probability=interference_probability,
            )

        elif isinstance(result, StackResult):
            if result.lower_limit >= target:
                verdict = "gap"
            elif result.upper_limit <= target:
                verdict = "interference"
            else:
                verdict = "mixed"

            return FitAssessment(
                target=target,
                verdict=verdict,
                margin_min=result.lower_limit - target,
                margin_max=result.upper_limit - target,
                interference_probability=None,
            )

        else:
            raise TypeError(
                f"assess_fit() expects a StackResult or MonteCarloResult, "
                f"got {type(result).__name__}."
            )
