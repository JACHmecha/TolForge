from dataclasses import dataclass, field
import numpy as np

@dataclass
class Dimension:
    name: str
    nominal: float
    tol_plus: float
    tol_minus: float
    sign: int = 1


@dataclass
class StackResult:
    nominal: float
    upper_limit: float
    lower_limit: float

@dataclass
class MonteCarloResult:
    samples: np.ndarray
    mean: float
    std_dev: float
    minimum: float
    maximum: float

@dataclass
class Stack:
    dimensions: list[Dimension] = field(default_factory=list)

    def add_dimension(self, dimension: Dimension):
        """Añade una dimensión a la cadena."""
        self.dimensions.append(dimension)

    def remove_dimension(self, name: str):
        """Elimina una dimensión por nombre."""
        self.dimensions = [
            d for d in self.dimensions if d.name != name
        ]

    def nominal(self):
        """Calcula la dimensión nominal resultante."""
        return sum(d.sign * d.nominal for d in self.dimensions)

    def worst_case(self):
        """
        Calcula los límites Worst Case del stack-up.
        """

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

        return StackResult(
            nominal=nominal,
            upper_limit=upper,
            lower_limit=lower
        )
    
    def rss(self):
        """Calcula los límites RSS del stack-up."""

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
    
    def monte_carlo(self, iterations=10000):
        """Realiza un análisis Monte Carlo del stack-up."""

        samples = np.zeros(iterations)

        for d in self.dimensions:

            values = np.random.uniform(
                d.nominal - d.tol_minus,
                d.nominal + d.tol_plus,
                iterations
            )

            samples += d.sign * values

        return MonteCarloResult(
            samples=samples,
            mean=np.mean(samples),
            std_dev=np.std(samples),
            minimum=np.min(samples),
            maximum=np.max(samples)
        )

    def summary(self, method="worst_case"):
        """Imprime un resumen del stack."""

        print("----- STACK SUMMARY -----")

        for d in self.dimensions:

            sign = "+" if d.sign > 0 else "-"

            print(
                f"{sign} {d.name:15}"
                f"{d.nominal:8.3f}"
                f"  +{d.tol_plus:.3f}"
                f"  -{d.tol_minus:.3f}"
            )

        if method == "worst_case":
            result = self.worst_case()
        elif method == "rss":
            result = self.rss()
        elif method == "monte_carlo":
            result = self.monte_carlo()
            print("-------------------------")
            print(f"Mean      : {result.mean:.3f}")
            print(f"Std Dev   : {result.std_dev:.3f}")
            print(f"Minimum   : {result.minimum:.3f}")
            print(f"Maximum   : {result.maximum:.3f}")
            return

        print("-------------------------")
        print(f"Nominal : {result.nominal:.3f}")
        print(f"Maximum : {result.upper_limit:.3f}")
        print(f"Minimum : {result.lower_limit:.3f}")
        print(f"+Tol    : {result.upper_limit - result.nominal:.3f}")
        print(f"-Tol    : {result.nominal - result.lower_limit:.3f}")


# ==========================================================
# Ejemplo de uso
# ==========================================================

stack = Stack()

stack.add_dimension(
    Dimension(
        name="Base",
        nominal=25.0,
        tol_plus=0.10,
        tol_minus=0.05,
        sign=1
    )
)

stack.add_dimension(
    Dimension(
        name="Spacer",
        nominal=12.5,
        tol_plus=0.05,
        tol_minus=0.05,
        sign=1
    )
)

stack.add_dimension(
    Dimension(
        name="Bearing",
        nominal=40.0,
        tol_plus=0.20,
        tol_minus=0.10,
        sign=-1
    )
)

stack.summary(method="Monte_Carlo")