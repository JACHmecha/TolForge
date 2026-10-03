"""Drawing requests and coverage, separate from measured feature results.

An inventory describes only the controls the user supplied. Recording a
profile/form/orientation control never makes it a supported solver. Control
definitions stay unchanged when a report records their evaluation status.
"""

from math import isfinite


CONTROL_FIELDS = (
    "id", "balloon", "drawing", "revision", "characteristic", "specification",
    "datum_references", "feature_name",
)
SUPPORTED_CHARACTERISTICS = frozenset(("position", "size"))
_REQUIRED_FIELDS = CONTROL_FIELDS[:6]


def normalize_datum_references(value):
    """Compare explicit frame labels conservatively, ignoring case/whitespace."""
    return "".join(value.split()).casefold()


def parse_control_specification(characteristic, specification):
    """Parse supported drawing limits in the measured dataset's length units.

Position accepts one finite nonnegative diameter. Size accepts positive,
ordered diameter limits separated by a colon. Other control types retain
their free-text specification and have no effective solver specification.
"""
    if characteristic not in SUPPORTED_CHARACTERISTICS:
        return None
    if not isinstance(specification, str):
        raise ValueError("Supported drawing specifications must be text in dataset units.")
    try:
        if characteristic == "position":
            value = float(specification)
            if not isfinite(value) or value < 0:
                raise ValueError
            return {"position_tolerance": value}
        values = specification.split(":")
        if len(values) != 2:
            raise ValueError
        lower, upper = (float(value) for value in values)
        if not all(isfinite(value) and value > 0 for value in (lower, upper)) or lower > upper:
            raise ValueError
        return {"size_lower": lower, "size_upper": upper}
    except (ValueError, TypeError, OverflowError) as exc:
        grammar = (
            "one finite nonnegative position diameter, for example 0.2"
            if characteristic == "position" else
            "two positive ordered size limits separated by ':', for example 10:10.2"
        )
        raise ValueError(f"Drawing {characteristic} specification must be {grammar}, in dataset units.") from exc


def validate_drawing_controls(rows):
    """Return copied, normalized engineering requests; reject partial rows.

Blank/incomplete UI rows belong in separate draft recovery, not this list.
An unlinked valid request is retained and will be reported as unevaluated.
Balloon identity is scoped by drawing and revision; control IDs are global.
"""
    if not isinstance(rows, list):
        raise ValueError("Drawing controls must be a list of objects.")
    controls = []
    ids = set()
    balloons = set()
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError(f"Drawing control row {index} must be an object.")
        control = {}
        for name in CONTROL_FIELDS:
            value = row.get(name, "")
            if not isinstance(value, str):
                raise ValueError(f"Drawing control row {index}: {name} must be text.")
            control[name] = value.strip()
            if name in _REQUIRED_FIELDS and not control[name]:
                raise ValueError(f"Drawing control row {index}: {name} is required; keep incomplete work in draft recovery.")
        control["characteristic"] = control["characteristic"].lower()
        if control["id"] in ids:
            raise ValueError(f"Drawing control ID '{control['id']}' must be unique.")
        ids.add(control["id"])
        balloon_key = tuple(normalize_datum_references(control[key]) for key in ("drawing", "revision", "balloon"))
        if balloon_key in balloons:
            raise ValueError(f"Balloon '{control['balloon']}' must be unique within its drawing and revision.")
        balloons.add(balloon_key)
        parse_control_specification(control["characteristic"], control["specification"])
        controls.append(control)
    return controls


def drawing_coverage(controls):
    """Count independent requested dispositions without implying full drawing coverage."""
    evaluated = sum(control["status"] == "evaluated" for control in controls)
    failed = sum(control["status"] == "evaluated" and control["passes"] is False for control in controls)
    requested = len(controls)
    complete = requested > 0 and evaluated == requested
    return {
        "requested": requested,
        "evaluated": evaluated,
        "unevaluated": sum(control["status"] == "unevaluated" for control in controls),
        "unsupported": sum(control["status"] == "unsupported" for control in controls),
        "passed": sum(control["status"] == "evaluated" and control["passes"] is True for control in controls),
        "failed": failed,
        "complete": complete,
        "passes_requested_controls": False if failed else (True if complete else None),
        "inventory_declared": requested > 0,
    }
