"""User-visible geometry, colors and interaction for the nominal preview."""

import math

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QGraphicsLineItem, QGraphicsPathItem, QGraphicsView

from gui.projected_preview import ProjectedPreview


@pytest.fixture
def preview():
    app = QApplication.instance() or QApplication([])
    widget = ProjectedPreview()
    widget.resize(800, 460)
    widget.show()
    app.processEvents()
    yield widget
    widget.close()
    app.processEvents()


def filled_paths(preview):
    return [item for item in preview.scene.items() if isinstance(item, QGraphicsPathItem)
            and item.brush().style() != Qt.NoBrush]


@pytest.mark.parametrize("mode,shade", [("hole-hole", "#67b58a"), ("hole-pin", "#d56868")])
def test_partial_intersection_highlights_opening_or_outside_pin_area(preview, mode, shade):
    preview.set_geometry(4, 2, 1.5, 0, mode, "mm")
    assert preview.valid
    assert preview.overlap_path.contains(QPointF(.375, 0))
    assert not preview.outside_path.contains(QPointF(.375, 0))
    assert preview.outside_path.contains(QPointF(.6, 0))
    assert not preview.overlap_path.contains(QPointF(.6, 0))
    highlighted = [item for item in filled_paths(preview) if item.brush().color().name() == shade]
    assert len(highlighted) == 1
    assert highlighted[0].path() == (preview.overlap_path if mode == "hole-hole" else preview.outside_path)


def test_circle_fills_match_blue_and_orange_legend_and_remain_translucent(preview):
    preview.set_geometry(4, 2, 1.5, 0, "hole-pin", "mm")
    colors = [item.brush().color() for item in filled_paths(preview)]
    for color_name in ("#71b6df", "#ffae5c"):
        candidates = [color for color in colors if color.name() == color_name]
        assert len(candidates) == 1
        assert 0 < candidates[0].alpha() < 255
    assert "Blue: hole" in preview.legend.text()
    assert "Orange: pin" in preview.legend.text()


def test_highlighted_curves_follow_circle_outlines_at_display_precision(preview):
    preview.set_geometry(4, 3, 1, -.5, "hole-pin", "mm")
    # At normalized radii below one, Qt's default path boolean flattening
    # can become visibly polygonal. Sample either side of both curved edges
    # at a gap smaller than a display pixel, away from the intersection.
    for index in range(15):
        angle = -.2 + index * 1.35 / 14
        cosine, sine = math.cos(angle), math.sin(angle)
        assert preview.overlap_path.contains(QPointF(.499 * cosine, .499 * sine))
        assert not preview.overlap_path.contains(QPointF(.501 * cosine, .501 * sine))
        assert preview.outside_path.contains(QPointF(.25 + .374 * cosine, .125 + .374 * sine))
        assert not preview.outside_path.contains(QPointF(.25 + .376 * cosine, .125 + .376 * sine))


@pytest.mark.parametrize("hole,pin,x,overlap_empty,outside_empty", [
    (4, 2, 0, False, True),
    (2, 2, 0, False, True),
    (2, 4, 0, False, False),
    (2, 2, 3, True, False),
])
def test_containment_and_separation_paths(preview, hole, pin, x, overlap_empty, outside_empty):
    preview.set_geometry(hole, pin, x, 0, "hole-pin", "mm")
    assert preview.valid
    assert preview.overlap_path.isEmpty() == overlap_empty
    assert preview.outside_path.isEmpty() == outside_empty
    if hole < pin and x == 0:
        assert not preview.outside_path.contains(QPointF(0, 0))
        assert preview.outside_path.contains(QPointF(.4, 0))


@pytest.mark.parametrize("hole,pin,x,state", [(4, 2, 0, "gap"), (4, 2, 1, "contact"), (2, 4, 0, "interference")])
def test_clearance_labels_explain_sign_and_contact(preview, hole, pin, x, state):
    preview.set_geometry(hole, pin, x, 0, "hole-pin", "mm")
    assert f"({state})" in preview.summary.text()
    assert "Radial clearance" in preview.summary.text()
    assert "mm" in preview.summary.text()


def test_signed_offsets_and_positive_y_are_drawn_in_correct_direction(preview):
    preview.set_geometry(4, 2, -1, 1, "hole-hole", "mm")
    lines = [item for item in preview.scene.items() if isinstance(item, QGraphicsLineItem)
             and item.pen().style() == Qt.DashLine]
    assert len(lines) == 1
    assert lines[0].line().p1() == QPointF(0, 0)
    assert lines[0].line().p2() == QPointF(-.25, -.25)
    assert "X -1, Y +1 mm" in preview.summary.text()
    assert "Positive Y is up" in preview.summary.text()


def test_unit_labels_and_conversion_preserve_geometry(preview):
    preview.set_geometry(4, 3, 1, -.5, "hole-pin", "mm")
    millimeter_paths = (preview.overlap_path, preview.outside_path)
    assert "mm" in preview.summary.text()
    preview.set_geometry(4 / 25.4, 3 / 25.4, 1 / 25.4, -.5 / 25.4, "hole-pin", "in")
    assert " in " in preview.summary.text()
    assert "mm" not in preview.summary.text()
    for actual, expected in zip((preview.overlap_path, preview.outside_path), millimeter_paths):
        actual_rect, expected_rect = actual.boundingRect(), expected.boundingRect()
        assert (actual_rect.x(), actual_rect.y(), actual_rect.width(), actual_rect.height()) == pytest.approx(
            (expected_rect.x(), expected_rect.y(), expected_rect.width(), expected_rect.height()), abs=1e-12)


@pytest.mark.parametrize("values", [
    (0, 2, 0, 0), (2, 0, 0, 0), (-1, 2, 0, 0),
    (math.nan, 2, 0, 0), (2, math.inf, 0, 0),
    (2, 2, math.inf, 0), (2, 2, 0, math.nan),
    (True, 2, 0, 0), (2, 2, 1.5e308, 1.5e308),
])
def test_invalid_geometry_clears_previous_paths_and_shows_input_message(preview, values):
    preview.set_geometry(4, 3, 1, 0, "hole-pin", "mm")
    assert preview.valid
    preview.set_geometry(*values, "hole-pin", "mm")
    assert not preview.valid
    assert not preview.scene.items()
    assert preview.overlap_path.isEmpty()
    assert preview.outside_path.isEmpty()
    assert preview.summary.text()
    assert "Nominal:" not in preview.summary.text()


@pytest.mark.parametrize("scale", [1e-200, 1e200])
def test_tiny_and_huge_lengths_normalize_to_safe_qt_coordinates(preview, scale):
    preview.set_geometry(4 * scale, 3 * scale, scale, -.5 * scale, "hole-pin", "mm")
    assert preview.valid
    rect = preview.scene.sceneRect()
    assert all(math.isfinite(value) and abs(value) < 10 for value in
               (rect.x(), rect.y(), rect.width(), rect.height()))
    assert preview.overlap_path.contains(QPointF(.25, .125))
    assert preview.outside_path.contains(QPointF(.6, .125))
    assert math.isfinite(preview.view.transform().m11())


def test_zoom_is_bounded_and_fit_restores_full_geometry(preview):
    preview.set_geometry(4, 2, 1, 0, "hole-pin", "mm")
    preview.view.fit_geometry()
    baseline = preview.view.transform().m11()
    preview.view.zoom(100)
    maximum = preview.view.transform().m11()
    assert maximum == pytest.approx(baseline * 1.2**12)
    preview.view.zoom(1)
    assert preview.view.transform().m11() == maximum
    preview.view.zoom(-100)
    minimum = preview.view.transform().m11()
    assert minimum == pytest.approx(baseline * 1.2**-8)
    preview.view.zoom(-1)
    assert preview.view.transform().m11() == minimum
    preview.view.fit_geometry()
    assert preview.view.transform().m11() == pytest.approx(baseline)
    assert preview.view._zoom_steps == 0


def test_zoomed_geometry_can_be_panned_with_left_mouse_drag(preview):
    preview.set_geometry(4, 3, 1, 0, "hole-pin", "mm")
    assert preview.view.dragMode() == QGraphicsView.ScrollHandDrag
    preview.view.zoom(6)
    app = QApplication.instance()
    app.processEvents()
    viewport = preview.view.viewport()
    before = (preview.view.horizontalScrollBar().value(), preview.view.verticalScrollBar().value())
    start = QPointF(viewport.rect().center())
    end = start + QPointF(50, 35)
    for kind, point, button, buttons in (
        (QMouseEvent.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton),
        (QMouseEvent.MouseMove, end, Qt.NoButton, Qt.LeftButton),
        (QMouseEvent.MouseButtonRelease, end, Qt.LeftButton, Qt.NoButton),
    ):
        global_point = QPointF(viewport.mapToGlobal(point.toPoint()))
        QApplication.sendEvent(viewport, QMouseEvent(kind, point, global_point, button, buttons, Qt.NoModifier))
    after = (preview.view.horizontalScrollBar().value(), preview.view.verticalScrollBar().value())
    assert after != before


def test_updates_replace_scene_items_instead_of_accumulating_geometry(preview):
    preview.set_geometry(4, 3, 1, 0, "hole-pin", "mm")
    count = len(preview.scene.items())
    for offset in (.5, -.5, 0, 1.5, 0):
        preview.set_geometry(4, 3, offset, 0, "hole-pin", "mm")
        assert len(preview.scene.items()) == count
