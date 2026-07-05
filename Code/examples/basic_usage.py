"""
Ejemplo básico de uso del paquete tolstack.

Ejecutar desde la raíz del repo con:
    python examples/basic_usage.py
"""

import sys
from pathlib import Path

# Permite ejecutar el ejemplo directamente sin instalar el paquete
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tolstack import Stack, Dimension


def main():
    stack = Stack()

    stack.add_dimension(
        Dimension(name="Base", nominal=25.0, tol_plus=0.10, tol_minus=0.05, sign=1)
    )
    stack.add_dimension(
        Dimension(name="Spacer", nominal=12.5, tol_plus=0.05, tol_minus=0.05, sign=1)
    )
    stack.add_dimension(
        Dimension(name="Bearing", nominal=40.0, tol_plus=0.20, tol_minus=0.10, sign=-1)
    )

    stack.summary(method="monte_carlo")


if __name__ == "__main__":
    main()
