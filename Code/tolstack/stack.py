"""
Lógica de cálculo del tolerance stack-up.

Contiene la clase Stack, que administra una lista de Dimension y
ofrece los tres métodos de análisis: worst_case, rss y monte_carlo.
"""

from dataclasses import dataclass, field
import numpy as np

from .models import Dimension, StackResult, MonteCarloResult

# Métodos válidos para summary(); se normalizan a minúsculas antes de comparar.
_VALID_METHODS = ("worst_case", "rss", "monte_carlo")


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

    def worst_case(self) -> StackResult:
        """Calcula los límites Worst Case del stack-up."""
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

    def monte_carlo(self, iterations=10000, default_cpk: float | None = None) -> MonteCarloResult:
        """Realiza un análisis Monte Carlo del stack-up.

        Por dimensión, el muestreo depende de `Dimension.cpk`:
        - `cpk is None` (default): distribución uniforme sobre todo el
          rango de tolerancia. Es el caso más pesimista, no representa
          un proceso de manufactura real.
        - `cpk` definido (ej. 1.33, 1.67, 2.0): distribución normal
          partida (split normal), calibrada para que el límite de
          tolerancia quede a `3 * cpk` desviaciones estándar del
          nominal, siguiendo la definición estándar de Cpk.

        `default_cpk`: si una dimensión no trae su propio `cpk`, se le
        aplica este valor en vez de caer a uniforme. Útil para correr
        el stack completo bajo un supuesto de proceso homogéneo sin
        tener que editar cada Dimension.
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
                        f"Cpk de '{d.name}' debe ser > 0, no {cpk}."
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
        """Imprime un resumen del stack.

        Nota: `method` se normaliza a minúsculas, así que "RSS", "rss"
        o "Rss" son equivalentes. Métodos inválidos lanzan ValueError
        en vez de fallar silenciosamente con un result no definido.
        """
        method = method.lower()

        if method not in _VALID_METHODS:
            raise ValueError(
                f"Método '{method}' no reconocido. Usa uno de: {_VALID_METHODS}"
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
