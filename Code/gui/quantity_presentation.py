"""Length formatting for the GUI, without converting or changing report data."""


def report_length_unit(report):
    """Use the evaluated snapshot, never a subsequently edited project unit."""
    if report is None or report.evidence is None:
        return None
    units = report.evidence.to_dict().get("input_snapshot", {}).get("units", {})
    unit = units.get("length") if isinstance(units, dict) else None
    return unit.strip() if isinstance(unit, str) and unit.strip() else None


def display_length(value, unit=None, *, signed=False):
    """Keep the usual four decimals, but never display a nonzero length as zero."""
    number = float(value)
    text = format(number, "+.4f" if signed else ".4f")
    if number != 0 and float(text) == 0:
        text = format(number, "+.6g" if signed else ".6g")
    return f"{text} {unit}" if unit else text


def full_length(value, unit=None, *, signed=False):
    """Round-trip representation of the evaluated float for copying or inspection."""
    number = float(value)
    text = repr(number)
    if signed and not text.startswith("-"):
        text = "+" + text
    return f"{text} {unit}" if unit else text
