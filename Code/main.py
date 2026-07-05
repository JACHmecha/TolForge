"""Punto de entrada rápido. Para más ejemplos, ver examples/."""

from tolstack import Stack, Dimension

if __name__ == "__main__":
    stack = Stack()
    stack.add_dimension(Dimension(name="Base", nominal=25.0, tol_plus=0.10, tol_minus=0.05))
    stack.summary(method="worst_case")
