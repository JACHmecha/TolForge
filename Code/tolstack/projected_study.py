"""Validation of saved Projected interference inputs, independent of Qt."""

from .json_data import require_finite_number, validate_json_value


INPUT_NAMES = ("handle", "sticker", "offset_x", "offset_y")


def validate_projection_config(projection) -> None:
    """Validate CAD projection metadata shared by saves and raw drafts."""
    validate_json_value(projection, "Projected interference projection")
    if not isinstance(projection, dict) or projection.get("reference_axis") not in ("X", "Y", "Z"):
        raise ValueError("Projected interference projection must have reference_axis X, Y or Z.")
    if projection.get("source_units", "mm") != "mm":
        raise ValueError("Projected interference CAD projection source units must be mm.")
    if projection.get("frame") is not None:
        from .projected_geometry import validate_projection_frame
        validate_projection_frame(projection["frame"])


def validate_projected_interference(settings) -> None:
    """Validate the optional schema-1 study block; samples are never saved.

    Empty/incomplete editors belong in recovery drafts. An untouched module
    omits this block so legacy projects remain saveable without positive sizes.
    """
    if not isinstance(settings, dict):
        raise ValueError("Projected interference settings must be an object.")
    validate_json_value(settings, "Projected interference")
    if settings.get("mode") not in ("hole-hole", "hole-pin"):
        raise ValueError("Projected interference mode must be hole-hole or hole-pin.")
    if settings.get("units") not in ("mm", "in"):
        raise ValueError("Projected interference units must be mm or in.")
    seed = settings.get("seed")
    if seed is not None and (type(seed) is not int or not 0 <= seed <= 2**32 - 1):
        raise ValueError("Projected interference seed must be an integer from 0 to 4294967295, or null.")
    iterations = settings.get("iterations")
    if type(iterations) is not int or not 100 <= iterations <= 1000000:
        raise ValueError("Projected interference iterations must be an integer from 100 to 1000000.")
    threshold = settings.get("threshold")
    require_finite_number(threshold, "Projected interference threshold")
    if not 0 <= threshold <= 100:
        raise ValueError("Projected interference threshold must be from 0 to 100%.")
    inputs = settings.get("inputs")
    if not isinstance(inputs, dict) or set(inputs) != set(INPUT_NAMES):
        raise ValueError("Projected interference inputs must include both diameters and X/Y offsets.")
    for name in INPUT_NAMES:
        entry = inputs[name]
        if not isinstance(entry, dict):
            raise ValueError(f"Projected interference {name} must be an object.")
        for field in ("nominal", "tol_plus", "tol_minus"):
            require_finite_number(entry.get(field), f"Projected interference {name} {field}")
        nominal, plus, minus = (entry[field] for field in ("nominal", "tol_plus", "tol_minus"))
        if plus < 0 or minus < 0:
            raise ValueError(f"Projected interference {name} tolerance magnitudes must be nonnegative.")
        require_finite_number(nominal - minus, f"Projected interference {name} lower limit")
        require_finite_number(nominal + plus, f"Projected interference {name} upper limit")
        if name in ("handle", "sticker") and nominal - minus <= 0:
            raise ValueError("Projected interference diameters and their full tolerance ranges must be positive.")
        cpk = entry.get("cpk")
        if cpk is not None:
            require_finite_number(cpk, f"Projected interference {name} Cpk")
            if cpk <= 0:
                raise ValueError(f"Projected interference {name} Cpk must be positive or null.")
    projection = settings.get("projection")
    if projection is not None:
        validate_projection_config(projection)
