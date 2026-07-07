import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

from tolstack import Stack, Dimension


def test_monte_carlo_accepts_string_signs():
    stack = Stack()
    stack.add_dimension(Dimension(name="A", nominal=10.0, tol_plus=1.0, tol_minus=1.0, sign="+"))
    stack.add_dimension(Dimension(name="B", nominal=5.0, tol_plus=0.5, tol_minus=0.5, sign="-"))

    result = stack.monte_carlo(iterations=50)

    assert result.samples.shape == (50,)
    assert result.mean is not None
