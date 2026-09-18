import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

from matplotlib.figure import Figure

from gui.theme import COLORS, STYLESHEET, style_axes, style_figure


def test_tolforge_theme_uses_reference_palette():
    assert COLORS["window"] == "#171B20"
    assert COLORS["panel"] == "#20262C"
    assert COLORS["accent"] == "#71B6DF"
    assert COLORS["selection"] == "#FFAE5C"
    assert 'QPushButton[role="primary"]' in STYLESHEET
    assert "QMenu::item:selected" in STYLESHEET


def test_matplotlib_theme_matches_inspector_surfaces():
    figure = Figure()
    style_figure(figure)
    axes = figure.add_subplot(111)
    axes.set_title("Analysis")
    style_axes(axes)

    assert figure.get_facecolor()[:3] == (32 / 255, 38 / 255, 44 / 255)
    assert axes.get_facecolor()[:3] == (38 / 255, 45 / 255, 52 / 255)
