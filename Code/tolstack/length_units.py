"""Explicit length conversion for the projected-interference workspace."""

from .models import finite_number


LENGTH_UNITS = ("mm", "in")


def convert_length(value, source: str, target: str) -> float:
    if source not in LENGTH_UNITS or target not in LENGTH_UNITS:
        raise ValueError("Length units must be mm or in.")
    number = finite_number(value, "Length")
    converted = number if source == target else number / 25.4 if source == "mm" else number * 25.4
    return finite_number(converted, "Converted length")
