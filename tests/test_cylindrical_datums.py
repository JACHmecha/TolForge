import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))
from gui.app import TolstackWindow  # registers local OCCT DLL paths on Windows
from gui.step_load_worker import StepLoadWorker
from tolstack.gdt import DatumFeature, build_datum_reference_frame
from tolstack.features import signature_from_points, FeatureSignature, match_signature
from tolstack import PartDefinition, Project
from test_offset_preview import window, face


@pytest.mark.parametrize("radius,height,angle", [(2, 12, 2 * np.pi), (12, 2, 2 * np.pi), (3, 6, np.pi / 2)])
def test_real_step_cylinder_recognition_is_independent_of_shape_proportions(tmp_path, radius, height, angle):
    pytest.importorskip("OCC.Core.BRepPrimAPI")
    from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCC.Core.gp import gp_Ax2, gp_Pnt, gp_Dir
    from compas_occ.brep import OCCBrep
    axis = np.array([1, 2, 3], dtype=float)
    axis /= np.linalg.norm(axis)
    point = np.array([17, -8, 5], dtype=float)
    shape = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*point), gp_Dir(*axis)), radius, height, angle).Shape()
    path = tmp_path / "rotated-cylinder.step"
    OCCBrep.from_shape(shape).to_step(str(path))
    result = StepLoadWorker(str(path), 0.4)._load()
    assert len(result.face_surfaces) == len(result.face_meshes)
    cylinders = [surface for surface in result.face_surfaces if surface["kind"] == "cylinder"]
    assert len(cylinders) == 1
    surface = cylinders[0]
    assert surface["radius"] == pytest.approx(radius)
    np.testing.assert_allclose(np.abs(np.dot(surface["direction"], axis)), 1, atol=1e-10)
    np.testing.assert_allclose(np.cross(np.asarray(surface["point"]) - point, axis), 0, atol=1e-9)
    assert any(surface["kind"] == "plane" for surface in result.face_surfaces)


def test_conical_surface_is_not_misidentified_as_a_cylinder():
    pytest.importorskip("OCC.Core.BRepPrimAPI")
    from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeCone
    from compas_occ.brep import OCCBrep
    faces = OCCBrep.from_shape(BRepPrimAPI_MakeCone(4, 2, 8).Shape()).faces
    kinds = [StepLoadWorker._recognize_surface(face)["kind"] for face in faces]
    assert "other" in kinds
    assert "cylinder" not in kinds


@pytest.mark.parametrize("axis_first", [True, False])
def test_frame_origin_lies_on_axis_and_locating_plane(axis_first):
    axis = DatumFeature([2, 3, 100], [0, 0, 1], "axis")
    plane = DatumFeature([20, 30, 4], [0, 0, 1])
    clock = DatumFeature([9, 0, 0], [1, 0, 0])
    frame = build_datum_reference_frame(axis, plane, clock) if axis_first else build_datum_reference_frame(plane, axis, clock)
    np.testing.assert_allclose(frame.origin, [2, 3, 4])
    np.testing.assert_allclose(frame.z_axis, [0, 0, 1])
    np.testing.assert_allclose(frame.x_axis, [1, 0, 0])
    np.testing.assert_allclose(np.cross(frame.x_axis, frame.y_axis), frame.z_axis)


def test_axis_frame_transforms_with_the_part():
    rotation = np.array([[0, 0, 1], [1, 0, 0], [0, 1, 0]], dtype=float)
    translation = np.array([-3, 8, 13])
    features = [DatumFeature(rotation @ p + translation, rotation @ d, kind)
                for p, d, kind in [([2, 3, 10], [0, 0, 1], "axis"),
                                   ([0, 0, 4], [0, 0, 1], "plane"),
                                   ([0, 0, 0], [1, 0, 0], "plane")]]
    frame = build_datum_reference_frame(*features)
    np.testing.assert_allclose(frame.origin, rotation @ [2, 3, 4] + translation)
    np.testing.assert_allclose(frame.z_axis, rotation @ [0, 0, 1])


def test_ambiguous_or_unsupported_axial_frames_are_rejected():
    axis = DatumFeature([0, 0, 0], [0, 0, 1], "axis")
    end_plane = DatumFeature([0, 0, 4], [0, 0, 1])
    side_plane = DatumFeature([0, 0, 0], [1, 0, 0])
    with pytest.raises(ValueError, match="does not fix rotation"):
        build_datum_reference_frame(axis, end_plane, end_plane)
    with pytest.raises(ValueError, match="perpendicular"):
        build_datum_reference_frame(axis, side_plane, end_plane)
    with pytest.raises(ValueError, match="axis/axis"):
        build_datum_reference_frame(axis, axis, side_plane)


def cylinder_info():
    angles = np.linspace(0, 2 * np.pi, 32, endpoint=False)
    points = np.array([[2 + 3 * np.cos(a), 3 + 3 * np.sin(a), z] for z in [4, 14] for a in angles])
    return {"type": "face", "index": 7, "points": points,
            "surface": {"kind": "cylinder", "point": [2, 3, 0], "direction": [0, 0, 1], "radius": 3}}


def test_cylinder_signature_roundtrip_and_axis_station_invariance():
    info = cylinder_info()
    sig = signature_from_points("face", info["points"], surface=info["surface"])
    assert sig.kind == "cylinder"
    np.testing.assert_allclose(sig.center, [2, 3, 9])
    restored = FeatureSignature.from_dict(sig.to_dict())
    moved_station = dict(info["surface"], point=[2, 3, 200], direction=[0, 0, -1])
    same = signature_from_points("face", info["points"][::2], surface=moved_station)
    assert match_signature(restored, [same]).matched_index == 0
    plane = signature_from_points("face", face()["points"])
    assert match_signature(restored, [plane]).matched_index is None


def test_gui_uses_cylinder_axis_and_restores_it_from_project(window):
    part = window.project.add_part(PartDefinition("Cylinder"))
    window._active_part_id = part.id
    info = cylinder_info()
    assert window._set_datum_from_info("Primary", info)
    assert window._datum_slot["Primary"]["kind"] == "axis"
    np.testing.assert_allclose(window._datum_slot["Primary"]["direction"], [0, 0, 1])
    assert window.project.features[info["feature_id"]].kind == "cylinder"
    assert "Cylinder" in window.selection_geometry_label.text()
    assert any(obj.options["name"] == "Datum A axis" for obj in window._datum_visual_objects)
    end = face(4)
    side = dict(face(), points=np.array([[0, 0, 0], [0, 2, 0], [0, 2, 2], [0, 0, 2]]))
    window._set_datum_from_info("Secondary", end)
    window._set_datum_from_info("Tertiary", side)
    window.build_datum_frame()
    np.testing.assert_allclose(window._current_drf.origin, [2, 3, 4])
    window._project_sync_datums_from_ui()
    window.project = Project.from_dict(window.project.to_dict())
    reloaded = dict(info, points=info["points"].copy())
    reloaded.pop("feature_id")
    window._step_entity_info = {1: reloaded, 2: end, 3: side}
    window._project_reattach_features()
    window._project_restore_datums()
    assert window._datum_slot["Primary"]["kind"] == "axis"
    np.testing.assert_allclose(window._current_drf.origin, [2, 3, 4])


def test_unrecognized_curved_faces_are_rejected_instead_of_fitted_as_planes(window):
    info = cylinder_info()
    info["surface"] = {"kind": "other"}
    assert window._gdt_extract_datum_geometry(info) == (None, None, None)
    info.pop("surface")
    assert window._gdt_extract_datum_geometry(info) == (None, None, None)
