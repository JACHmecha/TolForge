"""Exact inch relation, finite conversion and explicit supported units."""

import math

import pytest

from tolstack.length_units import convert_length


def test_one_inch_is_exactly_twenty_five_point_four_millimeters():
    assert convert_length(1, "in", "mm") == 25.4
    assert convert_length(25.4, "mm", "in") == 1
    assert convert_length(-1, "in", "mm") == -25.4
    assert convert_length(0, "mm", "in") == 0


@pytest.mark.parametrize("value", [0, -2.34567890123456, .00012345678901234, 1e-200, 1e200])
@pytest.mark.parametrize("source,target", [("mm", "in"), ("in", "mm")])
def test_conversion_roundtrip_preserves_full_float_precision(value, source, target):
    converted = convert_length(value, source, target)
    assert convert_length(converted, target, source) == pytest.approx(value, rel=3e-16, abs=0)


@pytest.mark.parametrize("units", ["mm", "in"])
def test_identical_units_retain_number(units):
    value = 1.2345678901234567
    assert convert_length(value, units, units) == value


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, True, None, "invalid"])
def test_nonfinite_or_invalid_number_rejected_even_without_conversion(value):
    for source, target in (("mm", "in"), ("in", "mm"), ("mm", "mm")):
        with pytest.raises(ValueError, match="finite"):
            convert_length(value, source, target)


@pytest.mark.parametrize("value", [1e308, -1e308])
def test_overflowing_conversion_rejected(value):
    with pytest.raises(ValueError, match="Converted length"):
        convert_length(value, "in", "mm")


@pytest.mark.parametrize("unit", ["cm", "inch", "MM", "", None, 123])
def test_unsupported_units_rejected_for_both_arguments(unit):
    with pytest.raises(ValueError, match="mm or in"):
        convert_length(1, unit, "mm")
    with pytest.raises(ValueError, match="mm or in"):
        convert_length(1, "mm", unit)
