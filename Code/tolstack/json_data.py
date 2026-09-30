"""Validation and strict JSON for persisted engineering data (no GUI)."""

from math import isfinite
from numbers import Real
import json


def require_text(value, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must not be empty.")


def require_finite_number(value, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a finite number.")
    try:
        finite = isfinite(value)
    except (TypeError, ValueError, OverflowError):
        finite = False
    if not finite:
        raise ValueError(f"{label} must be finite.")


def validate_json_value(value, label: str = "JSON data", _ancestors=None) -> None:
    """Require JSON-compatible content and finite numbers at every depth.

    Arbitrary metadata remains supported: this checks persistence safety rather
    than assigning engineering meaning to unknown metadata fields.
    """
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, (int, float)):
        require_finite_number(value, label)
        return
    if not isinstance(value, (dict, list, tuple)):
        raise ValueError(f"{label} contains unsupported JSON value {type(value).__name__}.")
    ancestors = set() if _ancestors is None else _ancestors
    if id(value) in ancestors:
        raise ValueError(f"{label} contains circular data.")
    ancestors.add(id(value))
    try:
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ValueError(f"{label} object keys must be text.")
                validate_json_value(item, f"{label}.{key}", ancestors)
        else:
            for index, item in enumerate(value):
                validate_json_value(item, f"{label}[{index}]", ancestors)
    finally:
        ancestors.remove(id(value))


def dumps_strict(data) -> str:
    validate_json_value(data)
    return json.dumps(data, indent=2, allow_nan=False)


def _reject_constant(value):
    raise ValueError(f"JSON number '{value}' must be finite.")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON object key '{key}'.")
        result[key] = value
    return result


def loads_strict(text: str):
    data = json.loads(text, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
    validate_json_value(data)
    return data
