"""Validated CAD circle projection for the projected-interference plane.

Offsets retain the signed A-to-B displacement in a stable right-handed basis.
The plane follows circle A's axis; tilted circle pairs outside the supported
angular allowance are rejected rather than treated as projected circles.
"""

from collections.abc import Mapping
from dataclasses import dataclass, fields
from math import atan2, degrees

import numpy as np

from .models import finite_number


_WORLD_AXES = {
    "X": np.array([1.0, 0.0, 0.0]),
    "Y": np.array([0.0, 1.0, 0.0]),
    "Z": np.array([0.0, 0.0, 1.0]),
}
_MIN_REFERENCE_PROJECTION = 1e-8


@dataclass(frozen=True)
class CircleProjection:
    """Immutable projection metadata; every length uses the source CAD unit.

    ``reference_axis`` is the actual world axis used, which can differ from
    ``requested_reference_axis`` when the requested axis is nearly normal to
    the plane. ``origin`` is circle A's center. The normal's dominant component
    is positive, making the basis independent of equivalent normal signs.
    """

    origin: tuple[float, float, float]
    normal: tuple[float, float, float]
    x_axis: tuple[float, float, float]
    y_axis: tuple[float, float, float]
    offset_x: float
    offset_y: float
    axis_angle_deg: float
    axial_separation: float
    requested_reference_axis: str
    reference_axis: str
    diameter_a: float
    diameter_b: float

    def to_dict(self) -> dict:
        """Return plain, JSON-serializable values for captured provenance."""
        return {
            "origin": list(self.origin),
            "normal": list(self.normal),
            "x_axis": list(self.x_axis),
            "y_axis": list(self.y_axis),
            "offset_x": self.offset_x,
            "offset_y": self.offset_y,
            "axis_angle_deg": self.axis_angle_deg,
            "axial_separation": self.axial_separation,
            "requested_reference_axis": self.requested_reference_axis,
            "reference_axis": self.reference_axis,
            "diameter_a": self.diameter_a,
            "diameter_b": self.diameter_b,
        }

    @classmethod
    def from_dict(cls, data) -> "CircleProjection":
        """Validate a saved projection snapshot without reconstructing CAD.

        The original B center is not part of a snapshot, so offsets and axial
        separation can only be checked for finite values here. The captured
        plane must remain an orthonormal, right-handed basis with truthful
        reference-axis metadata and the supported 0.1-degree angular limit.
        """
        expected = {field.name for field in fields(cls)}
        if not isinstance(data, Mapping) or set(data) != expected:
            raise ValueError("Projection frame must contain exactly the captured projection fields.")
        vectors = {name: _vector(data[name], f"Projection {name}")
                   for name in ("origin", "normal", "x_axis", "y_axis")}
        normal, x_axis, y_axis = (vectors[name] for name in ("normal", "x_axis", "y_axis"))
        for name, vector in (("normal", normal), ("x_axis", x_axis), ("y_axis", y_axis)):
            if (np.any(np.abs(vector) > 1 + 1e-9) or
                    not np.isclose(np.linalg.norm(vector), 1, rtol=0, atol=1e-9)):
                raise ValueError(f"Projection {name} must be a unit vector.")
        if any(abs(float(np.dot(first, second))) > 1e-9
               for first, second in ((normal, x_axis), (normal, y_axis), (x_axis, y_axis))):
            raise ValueError("Projection basis axes must be orthogonal.")
        if not np.allclose(np.cross(x_axis, y_axis), normal, rtol=0, atol=1e-9):
            raise ValueError("Projection basis must be right-handed.")

        references = {}
        for name in ("requested_reference_axis", "reference_axis"):
            value = data[name]
            if not isinstance(value, str) or value not in _WORLD_AXES:
                raise ValueError(f"Projection {name} must be X, Y or Z.")
            references[name] = value
        expected_x, expected_y, chosen_axis = _projection_basis(normal, references["requested_reference_axis"])
        if chosen_axis != references["reference_axis"]:
            raise ValueError("Projection reference axis does not match its requested axis or fallback.")
        if (not np.allclose(x_axis, expected_x, rtol=0, atol=1e-9) or
                not np.allclose(y_axis, expected_y, rtol=0, atol=1e-9)):
            raise ValueError("Projection basis does not match its reference axis.")

        scalars = {name: finite_number(data[name], f"Projection {name}")
                   for name in ("offset_x", "offset_y", "axis_angle_deg", "axial_separation",
                                "diameter_a", "diameter_b")}
        if not 0 <= scalars["axis_angle_deg"] <= 0.1:
            raise ValueError("Projection axis angle must be from 0 to 0.1 degrees; tilt is not modeled.")
        if scalars["diameter_a"] <= 0 or scalars["diameter_b"] <= 0:
            raise ValueError("Projection circle diameters must be greater than 0.")
        return cls(**{name: tuple(float(component) for component in vector)
                      for name, vector in vectors.items()}, **references, **scalars)


def validate_projection_frame(data) -> dict:
    """Return a validated JSON-safe projection snapshot for persistence."""
    return CircleProjection.from_dict(data).to_dict()


def _vector(value, label: str) -> np.ndarray:
    try:
        vector = np.asarray(value, dtype=object)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must contain three finite numbers.") from exc
    if vector.shape != (3,):
        raise ValueError(f"{label} must contain three finite numbers.")
    return np.array([finite_number(component, label) for component in vector])


def _unit_vector(value, label: str) -> np.ndarray:
    vector = _vector(value, label)
    scale = float(np.max(np.abs(vector)))
    if scale == 0:
        raise ValueError(f"{label} must have a nonzero direction.")
    scaled = vector / scale
    return scaled / np.linalg.norm(scaled)


def _circle(circle, label: str) -> tuple[np.ndarray, np.ndarray, float]:
    if not isinstance(circle, Mapping):
        raise ValueError(f"{label} must provide a center, normal and radius.")
    try:
        center = _vector(circle["center"], f"{label} center")
        normal = _unit_vector(circle["normal"], f"{label} normal")
        radius = finite_number(circle["radius"], f"{label} radius")
    except KeyError as exc:
        raise ValueError(f"{label} must provide a center, normal and radius.") from exc
    if radius <= 0:
        raise ValueError(f"{label} radius must be greater than 0.")
    return center, normal, finite_number(2 * radius, f"{label} diameter")


def _projection_basis(normal: np.ndarray, reference_axis: str) -> tuple[np.ndarray, np.ndarray, str]:
    choices = [reference_axis] + [axis for axis in _WORLD_AXES if axis != reference_axis]
    for chosen_axis in choices:
        world_axis = _WORLD_AXES[chosen_axis]
        # A double cross product avoids losing the tiny parallel component
        # to subtraction when the selected axis is almost normal to the plane.
        projected_axis = np.cross(normal, np.cross(world_axis, normal))
        length = float(np.linalg.norm(projected_axis))
        if length > _MIN_REFERENCE_PROJECTION:
            x_axis = projected_axis / length
            break
    y_axis = np.cross(normal, x_axis)
    y_axis /= np.linalg.norm(y_axis)
    return x_axis, y_axis, chosen_axis


def projection_from_circles(
    circle_a, circle_b, reference_axis: str = "X", max_axis_angle_deg: float = 0.1,
) -> CircleProjection:
    """Project fitted circles into a common plane with signed local X/Y.

    ``circle_a`` and ``circle_b`` use the Measure tab's ``center``, ``normal``
    and ``radius`` fields. Opposing normals describe equivalent axes. The
    angular difference must not exceed ``max_axis_angle_deg`` (default 0.1
    degrees); this allowance does not model tilt. X is the selected world axis
    projected into circle A's plane; Y is normal cross X. If the selected axis
    is nearly perpendicular to the plane, fall back in world X/Y/Z order and
    expose that choice in the result.
    """
    if not isinstance(reference_axis, str) or reference_axis not in _WORLD_AXES:
        raise ValueError("Projection reference axis must be X, Y or Z.")
    allowance = finite_number(max_axis_angle_deg, "Maximum circle-axis angle")
    if not 0 <= allowance <= 90:
        raise ValueError("Maximum circle-axis angle must be from 0 to 90 degrees.")
    center_a, normal_a, diameter_a = _circle(circle_a, "Circle A")
    center_b, normal_b, diameter_b = _circle(circle_b, "Circle B")
    angle = degrees(atan2(float(np.linalg.norm(np.cross(normal_a, normal_b))),
                         abs(float(np.dot(normal_a, normal_b)))))
    if angle > allowance:
        raise ValueError(
            f"Circle axes differ by {angle:.6g} degrees; projected interference "
            f"supports at most {allowance:.6g} degrees. Tilt is not modeled."
        )

    normal = normal_a.copy()
    if normal[int(np.argmax(np.abs(normal)))] < 0:
        normal = -normal
    x_axis, y_axis, chosen_axis = _projection_basis(normal, reference_axis)
    with np.errstate(over="ignore", invalid="ignore"):
        delta = center_b - center_a
        if not np.all(np.isfinite(delta)):
            raise ValueError("Circle-center displacement exceeds the finite numeric range.")
        offset_x = finite_number(np.dot(delta, x_axis), "Projected offset X")
        offset_y = finite_number(np.dot(delta, y_axis), "Projected offset Y")
        axial_separation = finite_number(np.dot(delta, normal), "Axial separation")
    as_tuple = lambda vector: tuple(float(component) for component in vector)
    return CircleProjection(
        as_tuple(center_a), as_tuple(normal), as_tuple(x_axis), as_tuple(y_axis),
        offset_x, offset_y, angle, axial_separation, reference_axis, chosen_axis,
        diameter_a, diameter_b,
    )
