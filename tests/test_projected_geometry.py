"""Independent CAD projection cases for the supported circular plane model."""

import json
import math
from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from tolstack.eclipse import ToleranceInput
from tolstack.projected_geometry import (
    CircleProjection, projection_from_circles, validate_projection_frame,
)
from tolstack.projected_interference import PinHoleInputs, radial_clearance_bounds


def circle(center=(0, 0, 0), normal=(0, 0, 1), radius=1):
    return {"center": center, "normal": normal, "radius": radius}


def test_signed_offsets_opposing_normals_and_serializable_provenance():
    result = projection_from_circles(circle((1, 2, 3)), circle((4, -2, 8), (0, 0, -2)))
    assert result.origin == (1, 2, 3)
    assert result.normal == (0, 0, 1)
    assert result.x_axis == (1, 0, 0)
    assert result.y_axis == (0, 1, 0)
    assert result.offset_x == 3
    assert result.offset_y == -4
    assert result.axial_separation == 5
    assert result.axis_angle_deg == 0
    assert result.diameter_a == result.diameter_b == 2
    assert json.loads(json.dumps(result.to_dict())) == result.to_dict()
    with pytest.raises(FrozenInstanceError):
        result.offset_x = 9


def test_equivalent_normal_signs_preserve_stable_signed_basis():
    a, b = circle(), circle((0, -1, 10))
    original = projection_from_circles(a, b)
    a["normal"] = (0, 0, -1)
    b["normal"] = (0, 0, -1)
    reversed_axes = projection_from_circles(a, b)
    assert reversed_axes == original


def test_axial_translation_leaves_xy_offsets_unchanged():
    before = projection_from_circles(circle(), circle((.3, -.7, 0)))
    after = projection_from_circles(circle(), circle((.3, -.7, 100)))
    assert (after.offset_x, after.offset_y) == (before.offset_x, before.offset_y)
    assert after.axial_separation == 100


def test_signed_y_displacement_preserves_anisotropic_clearance_bounds():
    result = projection_from_circles(circle(radius=2), circle((0, 1, 0)))
    quantity = lambda value, plus=0, minus=0: ToleranceInput("Input", value, plus, minus)
    inputs = PinHoleInputs(quantity(result.diameter_a), quantity(result.diameter_b),
                           quantity(result.offset_x, .2, .2), quantity(result.offset_y))
    assert radial_clearance_bounds(inputs) == pytest.approx((1 - math.hypot(.2, 1), 0))
    assert result.offset_x == 0
    assert result.offset_y == 1


def test_rotated_plane_has_right_handed_orthonormal_basis():
    normal = np.array([1., 2., 3.])
    normal /= np.linalg.norm(normal)
    a = circle((1, 2, 3), normal)
    frame = projection_from_circles(a, a, reference_axis="Z")
    x, y = np.array(frame.x_axis), np.array(frame.y_axis)
    delta = x * -2 + y * 4 + normal * 6
    result = projection_from_circles(a, circle(np.array(a["center"]) + delta, normal), "Z")
    assert result.offset_x == pytest.approx(-2)
    assert result.offset_y == pytest.approx(4)
    assert result.axial_separation == pytest.approx(6)
    np.testing.assert_allclose(np.cross(result.x_axis, result.y_axis), result.normal)
    np.testing.assert_allclose(np.array([result.x_axis, result.y_axis, result.normal]) @
                               np.array([result.x_axis, result.y_axis, result.normal]).T,
                               np.eye(3), atol=1e-15)


@pytest.mark.parametrize("normal,requested,chosen", [
    ((1, 0, 0), "X", "Y"), ((1, 1e-12, 0), "X", "Y"),
    ((0, 1, 0), "Y", "X"), ((0, 0, 1), "Z", "X"),
])
def test_parallel_reference_axis_falls_back_and_records_choice(normal, requested, chosen):
    result = projection_from_circles(circle(normal=normal), circle(normal=normal), requested)
    assert result.requested_reference_axis == requested
    assert result.reference_axis == chosen
    assert np.dot(result.x_axis, result.normal) == pytest.approx(0, abs=1e-15)


def test_nearly_parallel_usable_reference_remains_orthogonal():
    a = circle(normal=(1, 2e-8, 0))
    result = projection_from_circles(a, a)
    assert result.reference_axis == "X"
    assert np.dot(result.x_axis, result.normal) == pytest.approx(0, abs=1e-15)
    np.testing.assert_allclose(np.cross(result.x_axis, result.y_axis), result.normal, atol=1e-15)


@pytest.mark.parametrize("angle", [.1001, 1, 45, 90])
def test_tilt_outside_supported_allowance_is_rejected(angle):
    tilted = (math.sin(math.radians(angle)), 0, math.cos(math.radians(angle)))
    with pytest.raises(ValueError, match="Tilt is not modeled"):
        projection_from_circles(circle(), circle(normal=tilted))


def test_small_axis_fit_difference_is_reported_without_averaging_plane():
    angle = .05
    tilted = (math.sin(math.radians(angle)), 0, math.cos(math.radians(angle)))
    result = projection_from_circles(circle(), circle((1, 2, 3), tilted))
    assert result.axis_angle_deg == pytest.approx(angle)
    assert result.normal == (0, 0, 1)
    assert (result.offset_x, result.offset_y) == (1, 2)


def test_axis_angle_boundary_is_supported():
    angle = math.radians(.1)
    tilted = (math.sin(angle), 0, math.cos(angle))
    result = projection_from_circles(circle(), circle(normal=tilted))
    assert result.axis_angle_deg == pytest.approx(.1)


@pytest.mark.parametrize("bad", [
    None, {}, {"center": (0, 0, 0)},
    circle(center=(0, 0)), circle(center=((0, 0, 0),)),
    circle(center=(0, math.nan, 0)), circle(center=(0, math.inf, 0)),
    circle(center=(False, 0, 0)), circle(normal=(0, 0, 0)),
    circle(normal=(math.inf, 0, 1)), circle(normal=(0, 1)),
    circle(radius=0), circle(radius=-1), circle(radius=math.nan), circle(radius=True),
])
@pytest.mark.parametrize("slot", ["A", "B"])
def test_malformed_or_degenerate_circle_is_rejected(bad, slot):
    with pytest.raises(ValueError):
        projection_from_circles(bad if slot == "A" else circle(),
                                bad if slot == "B" else circle())


@pytest.mark.parametrize("axis", ["", "x", "W", None, True])
def test_invalid_reference_axis_is_rejected(axis):
    with pytest.raises(ValueError, match="reference axis"):
        projection_from_circles(circle(), circle(), reference_axis=axis)


@pytest.mark.parametrize("limit", [-1, 91, math.nan, math.inf, True])
def test_invalid_axis_angle_allowance_is_rejected(limit):
    with pytest.raises(ValueError):
        projection_from_circles(circle(), circle(), max_axis_angle_deg=limit)


@pytest.mark.parametrize("scale", [1e-300, 1e300])
def test_finite_normal_scaling_does_not_change_basis(scale):
    result = projection_from_circles(circle(normal=(0, 0, scale)), circle())
    assert result.normal == (0, 0, 1)
    assert result.axis_angle_deg == 0


def test_unrepresentable_center_displacement_is_rejected():
    with pytest.raises(ValueError, match="displacement exceeds"):
        projection_from_circles(circle((-1e308, 0, 0)), circle((1e308, 0, 0)))


@pytest.mark.parametrize("normal,reference", [
    ((0, 0, 1), "X"), ((1, 0, 0), "X"), ((1, 2, 3), "Y"), ((1, 2e-8, 0), "X"),
])
def test_saved_projection_snapshot_round_trip_preserves_shape_and_values(normal, reference):
    projection = projection_from_circles(circle((1, 2, 3), normal),
                                        circle((4, -2, 8), normal), reference)
    snapshot = json.loads(json.dumps(projection.to_dict()))
    assert CircleProjection.from_dict(snapshot) == projection
    assert validate_projection_frame(snapshot) == snapshot
    validated = validate_projection_frame(snapshot)
    validated["origin"][0] = 99
    assert snapshot["origin"][0] == 1


@pytest.mark.parametrize("bad", [None, [], {}, {"offset_x": 0}])
def test_malformed_saved_snapshot_is_rejected(bad):
    with pytest.raises(ValueError, match="captured projection fields"):
        validate_projection_frame(bad)


def test_unknown_saved_projection_field_is_rejected():
    snapshot = projection_from_circles(circle(), circle()).to_dict()
    snapshot["extra"] = 0
    with pytest.raises(ValueError, match="captured projection fields"):
        validate_projection_frame(snapshot)


@pytest.mark.parametrize("field", [
    "origin", "normal", "x_axis", "y_axis", "offset_x", "offset_y",
    "axis_angle_deg", "axial_separation", "diameter_a", "diameter_b",
])
@pytest.mark.parametrize("bad", [math.nan, math.inf, True])
def test_nonfinite_or_boolean_saved_snapshot_values_are_rejected(field, bad):
    snapshot = projection_from_circles(circle(), circle()).to_dict()
    snapshot[field] = [bad, 0, 0] if field in ("origin", "normal", "x_axis", "y_axis") else bad
    with pytest.raises(ValueError):
        validate_projection_frame(snapshot)


@pytest.mark.parametrize("field", ["normal", "x_axis", "y_axis"])
def test_saved_basis_must_use_unit_vectors(field):
    snapshot = projection_from_circles(circle(), circle()).to_dict()
    snapshot[field] = [2 * component for component in snapshot[field]]
    with pytest.raises(ValueError, match="unit vector"):
        validate_projection_frame(snapshot)


def test_large_finite_nonunit_saved_basis_is_rejected_without_overflow():
    snapshot = projection_from_circles(circle(), circle()).to_dict()
    snapshot["normal"] = [1e308, 1e308, 1e308]
    with np.errstate(over="raise", invalid="raise"):
        with pytest.raises(ValueError, match="unit vector"):
            validate_projection_frame(snapshot)


def test_saved_basis_must_be_orthogonal():
    snapshot = projection_from_circles(circle(), circle()).to_dict()
    snapshot["y_axis"] = [math.sqrt(.5), math.sqrt(.5), 0]
    with pytest.raises(ValueError, match="orthogonal"):
        validate_projection_frame(snapshot)


def test_saved_basis_must_be_right_handed():
    snapshot = projection_from_circles(circle(), circle()).to_dict()
    snapshot["y_axis"] = [0, -1, 0]
    with pytest.raises(ValueError, match="right-handed"):
        validate_projection_frame(snapshot)


@pytest.mark.parametrize("field,value", [
    ("reference_axis", "W"), ("requested_reference_axis", True),
    ("reference_axis", "Y"), ("requested_reference_axis", "Y"),
    ("axis_angle_deg", -.01), ("axis_angle_deg", .1001),
    ("diameter_a", 0), ("diameter_b", -1),
])
def test_saved_projection_metadata_must_describe_supported_frame(field, value):
    snapshot = projection_from_circles(circle(), circle()).to_dict()
    snapshot[field] = value
    with pytest.raises(ValueError):
        validate_projection_frame(snapshot)


def test_saved_orthonormal_basis_must_match_selected_reference():
    snapshot = projection_from_circles(circle(), circle()).to_dict()
    snapshot["x_axis"], snapshot["y_axis"] = [0, 1, 0], [-1, 0, 0]
    with pytest.raises(ValueError, match="does not match its reference axis"):
        validate_projection_frame(snapshot)
