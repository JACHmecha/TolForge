"""Length display must retain tiny values and the report's captured unit."""

from gui.quantity_presentation import display_length, full_length, report_length_unit
from tolstack import Dimension, Stack
from tolstack.analysis import analyze_stack


def test_small_nonzero_lengths_do_not_round_to_displayed_zero():
    assert display_length(0.000004, "mm") == "4e-06 mm"
    assert display_length(-0.000004, "in", signed=True) == "-4e-06 in"
    assert display_length(0, "mm", signed=True) == "+0.0000 mm"
    assert display_length(1.2345678901234567, "mm") == "1.2346 mm"
    assert full_length(1.2345678901234567, "mm") == "1.2345678901234567 mm"


def test_report_unit_is_captured_without_assuming_or_converting_units():
    context = {"units": {"length": "in", "angle": "deg"}}
    report = analyze_stack(Stack([Dimension("A", 1, 0.1, 0.1)]), report_context=context)
    context["units"]["length"] = "mm"
    assert report_length_unit(report) == "in"
    assert report.result.nominal == 1
    standalone = analyze_stack(Stack([Dimension("A", 1, 0.1, 0.1)]))
    assert report_length_unit(standalone) is None
    assert report_length_unit(None) is None
    assert display_length(1) == "1.0000"
