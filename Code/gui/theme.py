"""TolForge's application-wide visual language.

The palette mirrors the contextual UI concept: graphite work surfaces,
cool slate borders, a restrained engineering-blue accent, and orange only
for geometry selection/highlight states. Keeping the values here prevents
individual panels from drifting into unrelated shades as the GUI grows.
"""

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


COLORS = {
    "window": "#171B20",
    "viewport": "#1C2228",
    "panel": "#20262C",
    "surface": "#262D34",
    "surface_hover": "#303942",
    "input": "#171C21",
    "border": "#3A434D",
    "border_strong": "#505C67",
    "text": "#E8EDF2",
    "muted": "#AAB5BF",
    "disabled": "#66727D",
    "accent": "#71B6DF",
    "accent_hover": "#8AC7E9",
    "accent_surface": "#263C49",
    "accent_border": "#3F6679",
    "selection": "#FFAE5C",
    "positive": "#67D39A",
    "negative": "#FF7474",
}


STYLESHEET = f"""
QMainWindow, QWidget#appRoot {{
    background-color: {COLORS['window']};
    color: {COLORS['text']};
}}
QWidget {{
    color: {COLORS['text']};
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 12px;
}}
QLabel {{
    background: transparent;
}}
QLabel[role="muted"] {{
    color: {COLORS['muted']};
}}
QLabel[role="status"] {{
    color: {COLORS['accent']};
}}
QFrame#workspaceRail {{
    background: {COLORS['panel']};
    border: 0;
    border-right: 1px solid {COLORS['border']};
}}
QFrame#workspaceRail QPushButton {{
    min-height: 36px;
    padding: 5px 4px;
    color: {COLORS['muted']};
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
}}
QFrame#workspaceRail QPushButton:hover {{
    color: {COLORS['text']};
    background: {COLORS['surface_hover']};
    border-color: #48535E;
}}
QFrame#workspaceRail QPushButton:checked {{
    color: #BFE7FF;
    background: {COLORS['accent_surface']};
    border-color: {COLORS['accent_border']};
}}
QTabWidget#inspectorPanel::pane {{
    background: {COLORS['panel']};
    border: 0;
    border-left: 1px solid {COLORS['border']};
}}
QTabWidget#inspectorPanel QScrollArea,
QTabWidget#inspectorPanel QScrollArea > QWidget > QWidget {{
    background-color: {COLORS['panel']};
}}
QMenuBar {{
    padding: 2px 5px;
    color: {COLORS['muted']};
    background: {COLORS['panel']};
    border-bottom: 1px solid {COLORS['border']};
}}
QMenuBar::item {{
    padding: 5px 8px;
    background: transparent;
    border-radius: 4px;
}}
QMenuBar::item:selected {{
    color: {COLORS['text']};
    background: {COLORS['surface_hover']};
}}
QFrame#viewportToolbar {{
    background: {COLORS['panel']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
}}
QWidget#viewportSurface {{
    background: {COLORS['viewport']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
}}
QFrame#statusStrip {{
    background: {COLORS['panel']};
    border: 0;
    border-top: 1px solid {COLORS['border']};
}}
QFrame[surface="card"] {{
    background: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
}}
QPushButton {{
    min-height: 28px;
    padding: 4px 10px;
    color: {COLORS['text']};
    background: #2A323A;
    border: 1px solid #46515B;
    border-radius: 5px;
}}
QPushButton:hover {{
    background: {COLORS['surface_hover']};
    border-color: #5B6975;
}}
QPushButton:pressed {{
    background: #1C252C;
}}
QPushButton:disabled {{
    color: {COLORS['disabled']};
    background: #20262B;
    border-color: #343D45;
}}
QPushButton[role="primary"] {{
    color: #0E161D;
    background: {COLORS['accent']};
    border-color: {COLORS['accent']};
    font-weight: 600;
}}
QPushButton[role="primary"]:hover {{
    background: {COLORS['accent_hover']};
    border-color: {COLORS['accent_hover']};
}}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    min-height: 27px;
    padding: 2px 7px;
    color: {COLORS['text']};
    background: {COLORS['input']};
    border: 1px solid #49545E;
    border-radius: 5px;
    selection-background-color: #2E617E;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {COLORS['accent']};
}}
QComboBox::drop-down {{
    width: 22px;
    border: 0;
    border-left: 1px solid {COLORS['border']};
}}
QComboBox QAbstractItemView {{
    color: {COLORS['text']};
    background: {COLORS['surface']};
    border: 1px solid {COLORS['border_strong']};
    selection-background-color: #334F60;
    outline: 0;
}}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
    width: 18px;
    background: #283038;
    border: 0;
    border-left: 1px solid {COLORS['border']};
}}
QTableWidget {{
    color: {COLORS['text']};
    background: #1B2026;
    alternate-background-color: #20272E;
    gridline-color: {COLORS['border']};
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
    selection-color: #FFFFFF;
    selection-background-color: #31576D;
}}
QTableWidget::item {{
    padding: 4px;
}}
QHeaderView::section {{
    padding: 6px 5px;
    color: #DCE4EB;
    background: #2A323A;
    border: 0;
    border-right: 1px solid {COLORS['border']};
    border-bottom: 1px solid {COLORS['border']};
}}
QMenu {{
    padding: 5px;
    color: #ECF2F6;
    background: {COLORS['surface']};
    border: 1px solid {COLORS['border_strong']};
    border-radius: 7px;
}}
QMenu::item {{
    min-height: 24px;
    padding: 5px 28px 5px 9px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background: #334550;
}}
QMenu::item:disabled {{
    color: {COLORS['disabled']};
}}
QMenu::separator {{
    height: 1px;
    margin: 4px 5px;
    background: #414B54;
}}
QScrollArea {{
    border: 0;
}}
QScrollBar:vertical {{
    width: 10px;
    margin: 0;
    background: #1B2025;
}}
QScrollBar::handle:vertical {{
    min-height: 28px;
    background: #4A5661;
    border-radius: 5px;
}}
QScrollBar::handle:vertical:hover {{
    background: #5C6A76;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QCheckBox {{
    spacing: 7px;
}}
QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    background: {COLORS['input']};
    border: 1px solid #56626D;
    border-radius: 3px;
}}
QCheckBox::indicator:checked {{
    background: {COLORS['accent']};
    border-color: {COLORS['accent']};
}}
QToolTip {{
    padding: 5px 7px;
    color: {COLORS['text']};
    background: #303840;
    border: 1px solid {COLORS['border_strong']};
}}
"""


def apply_window_theme(window) -> None:
    """Apply the TolForge palette and QSS to one top-level window."""
    window.setStyleSheet(STYLESHEET)


def apply_application_palette(app: QApplication) -> None:
    """Give native dialogs and unstyled Qt internals the same dark baseline."""
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(COLORS["window"]))
    palette.setColor(QPalette.WindowText, QColor(COLORS["text"]))
    palette.setColor(QPalette.Base, QColor(COLORS["input"]))
    palette.setColor(QPalette.AlternateBase, QColor(COLORS["panel"]))
    palette.setColor(QPalette.Text, QColor(COLORS["text"]))
    palette.setColor(QPalette.Button, QColor(COLORS["surface"]))
    palette.setColor(QPalette.ButtonText, QColor(COLORS["text"]))
    palette.setColor(QPalette.Highlight, QColor("#31576D"))
    palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    app.setPalette(palette)


def style_figure(figure) -> None:
    """Apply the dark panel background to a Matplotlib figure."""
    figure.set_facecolor(COLORS["panel"])


def style_axes(axes) -> None:
    """Make a Matplotlib axes readable inside the dark inspector panel."""
    axes.set_facecolor(COLORS["surface"])
    axes.tick_params(colors=COLORS["muted"])
    axes.xaxis.label.set_color(COLORS["muted"])
    axes.yaxis.label.set_color(COLORS["muted"])
    axes.title.set_color(COLORS["text"])
    for spine in axes.spines.values():
        spine.set_color(COLORS["border_strong"])
    axes.grid(color=COLORS["border"], alpha=0.35, linewidth=0.7)
