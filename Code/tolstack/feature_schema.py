"""Pure validation of the geometric fingerprint stored in project JSON."""

from .json_data import require_finite_number


SIGNATURE_KINDS = ("circle", "cylinder", "plane", "point", "generic")


def _require_vector(value, label: str) -> None:
    # Arrays are accepted by the in-memory signature; persisted vectors are
    # lists. Check components before conversion can coerce text or booleans.
    if isinstance(value, (str, bytes, dict)):
        raise ValueError(f"{label} must have exactly three finite coordinates.")
    try:
        if len(value) != 3:
            raise ValueError(f"{label} must have exactly three finite coordinates.")
        for component in value:
            require_finite_number(component, label)
    except TypeError as exc:
        raise ValueError(f"{label} must have exactly three finite coordinates.") from exc


def validate_feature_signature_data(data: dict) -> None:
    """Validate known fields without removing optional or legacy extra fields."""
    if not isinstance(data, dict):
        raise ValueError("Feature signature must be an object.")
    kind = data.get("kind")
    if kind not in SIGNATURE_KINDS:
        raise ValueError(f"Unknown signature kind '{kind}', expected one of {SIGNATURE_KINDS}.")
    _require_vector(data.get("center"), "Signature center")
    normal = data.get("normal")
    if normal is not None:
        _require_vector(normal, "Signature normal")
    radius = data.get("radius")
    if radius is not None:
        require_finite_number(radius, "Signature radius")
        if kind in ("circle", "cylinder") and radius <= 0:
            raise ValueError("Circle/cylinder signature radius must be positive.")
    count = data.get("point_count", 0)
    require_finite_number(count, "Signature point_count")
    if count < 0 or count != int(count):
        raise ValueError("Signature point_count must be a nonnegative integer.")
    diagonal = data.get("bbox_diagonal", 0.0)
    require_finite_number(diagonal, "Signature bbox_diagonal")
    if diagonal < 0:
        raise ValueError("Signature bbox_diagonal must be nonnegative.")
