from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, QSettings, QRectF, QSize
from PySide6.QtGui import QColor, QPalette, QPainter, QPixmap, QFont
from PySide6.QtWidgets import QApplication

from .constants import asset_path


@dataclass(frozen=True)
class Theme:
    key: str
    name: str
    window: str
    base: str
    alternate: str
    surface: str
    surface_hover: str
    text: str
    muted: str
    border: str
    accent: str
    accent_text: str
    danger: str
    light: bool = False


THEMES = {
    "catppuccin_mocha": Theme("catppuccin_mocha", "Catppuccin Mocha", "#1e1e2e", "#11111b", "#181825", "#313244", "#45475a", "#cdd6f4", "#a6adc8", "#585b70", "#89b4fa", "#11111b", "#f38ba8"),
    "gruvbox_dark": Theme("gruvbox_dark", "Gruvbox Dark", "#282828", "#1d2021", "#32302f", "#3c3836", "#504945", "#ebdbb2", "#a89984", "#665c54", "#d79921", "#282828", "#fb4934"),
    "tokyo_night": Theme("tokyo_night", "Tokyo Night", "#1a1b26", "#16161e", "#24283b", "#292e42", "#3b4261", "#c0caf5", "#9aa5ce", "#414868", "#7aa2f7", "#16161e", "#f7768e"),
    "dracula": Theme("dracula", "Dracula", "#282a36", "#21222c", "#343746", "#44475a", "#56596c", "#f8f8f2", "#bfbfbf", "#6272a4", "#bd93f9", "#282a36", "#ff5555"),
    "catppuccin_latte": Theme("catppuccin_latte", "Catppuccin Latte", "#eff1f5", "#e6e9ef", "#dce0e8", "#ccd0da", "#bcc0cc", "#4c4f69", "#6c6f85", "#9ca0b0", "#1e66f5", "#eff1f5", "#d20f39", True),
    "gruvbox_light": Theme("gruvbox_light", "Gruvbox Light", "#fbf1c7", "#f2e5bc", "#ebdbb2", "#d5c4a1", "#bdae93", "#3c3836", "#665c54", "#a89984", "#b57614", "#fbf1c7", "#cc241d", True),
}
DEFAULT_THEME = "catppuccin_mocha"


def current_theme_key() -> str:
    value = str(QSettings("Martin Hammond", "ComfyUI Image Browser").value("appearance/theme", DEFAULT_THEME))
    return value if value in THEMES else DEFAULT_THEME


def apply_theme(app: QApplication, key: str | None = None) -> Theme:
    theme = THEMES.get(key or current_theme_key(), THEMES[DEFAULT_THEME])
    app.setStyle("Fusion")

    font = app.font()
    if font.pointSizeF() < 10:
        font.setPointSizeF(10)
    app.setFont(font)

    p = QPalette()
    for role, colour in (
        (QPalette.ColorRole.Window, theme.window),
        (QPalette.ColorRole.WindowText, theme.text),
        (QPalette.ColorRole.Base, theme.base),
        (QPalette.ColorRole.AlternateBase, theme.alternate),
        (QPalette.ColorRole.ToolTipBase, theme.surface),
        (QPalette.ColorRole.ToolTipText, theme.text),
        (QPalette.ColorRole.Text, theme.text),
        (QPalette.ColorRole.Button, theme.surface),
        (QPalette.ColorRole.ButtonText, theme.text),
        (QPalette.ColorRole.BrightText, theme.danger),
        (QPalette.ColorRole.Link, theme.accent),
        (QPalette.ColorRole.Highlight, theme.accent),
        (QPalette.ColorRole.HighlightedText, theme.accent_text),
        (QPalette.ColorRole.PlaceholderText, theme.muted),
    ):
        p.setColor(role, QColor(colour))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(theme.muted))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(theme.muted))
    app.setPalette(p)

    app.setStyleSheet(f"""
    * {{ outline: none; }}
    QMainWindow, QDialog, QWidget {{
        background-color: {theme.window};
        color: {theme.text};
    }}

    QMenuBar {{
        background: {theme.alternate};
        border-bottom: 1px solid {theme.border};
        padding: 2px 6px;
        spacing: 3px;
    }}
    QMenuBar::item {{
        background: transparent;
        border-radius: 5px;
        padding: 4px 8px;
    }}
    QMenuBar::item:selected, QMenuBar::item:pressed {{
        background: {theme.surface};
        color: {theme.text};
    }}
    QMenu {{
        background: {theme.alternate};
        border: 1px solid {theme.border};
        border-radius: 7px;
        padding: 4px;
    }}
    QMenu::item {{
        border-radius: 5px;
        padding: 5px 25px 5px 24px;
        margin: 1px 0;
    }}
    QMenu::item:selected {{
        background: {theme.accent};
        color: {theme.accent_text};
    }}
    QMenu::item:disabled {{ color: {theme.muted}; }}
    QMenu::separator {{
        height: 1px;
        background: {theme.border};
        margin: 4px 7px;
    }}
    QMenu::indicator {{ left: 8px; width: 14px; height: 14px; }}

    QToolBar#mainToolbar {{
        background: {theme.alternate};
        border: 0;
        border-bottom: 1px solid {theme.border};
        spacing: 3px;
        padding: 4px 6px;
    }}
    QToolBar#mainToolbar QToolButton {{
        background: transparent;
        border: 0;
        border-radius: 6px;
        padding: 5px 8px;
    }}
    QToolBar#mainToolbar QToolButton:hover {{ background: {theme.surface}; }}
    QToolBar#mainToolbar QToolButton:pressed {{
        background: {theme.accent};
        color: {theme.accent_text};
    }}

    QStatusBar {{
        background: {theme.alternate};
        color: {theme.muted};
        border-top: 1px solid {theme.border};
        padding: 1px 6px;
    }}
    QStatusBar::item {{ border: 0; }}

    QLineEdit, QPlainTextEdit, QTextEdit, QTreeView, QListWidget,
    QTableWidget, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: {theme.base};
        color: {theme.text};
        border: 1px solid {theme.border};
        border-radius: 6px;
        selection-background-color: {theme.accent};
        selection-color: {theme.accent_text};
    }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        padding: 4px 7px;
        min-height: 20px;
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
    QTreeView:focus, QListWidget:focus, QTableWidget:focus, QComboBox:focus {{
        border: 1px solid {theme.accent};
    }}
    QComboBox::drop-down {{ border: 0; width: 20px; }}
    QComboBox QAbstractItemView {{
        background: {theme.alternate};
        color: {theme.text};
        border: 1px solid {theme.border};
        selection-background-color: {theme.accent};
        padding: 3px;
    }}

    QTreeView, QListWidget, QTableWidget {{ padding: 2px; }}
    QTreeView::item, QListWidget::item {{
        border-radius: 4px;
        padding: 3px;
        margin: 0px;
    }}
    QTreeView::item:hover, QListWidget::item:hover {{ background: {theme.surface}; }}
    QTreeView::item:selected, QListWidget::item:selected {{
        background: {theme.accent};
        color: {theme.accent_text};
    }}

    QPushButton, QToolButton {{
        background: {theme.surface};
        color: {theme.text};
        border: 1px solid {theme.border};
        border-radius: 5px;
        padding: 4px 8px;
        min-height: 19px;
    }}
    QPushButton:hover, QToolButton:hover {{
        background: {theme.surface_hover};
        border-color: {theme.accent};
    }}
    QPushButton:pressed, QToolButton:pressed, QToolButton:checked {{
        background: {theme.accent};
        color: {theme.accent_text};
        border-color: {theme.accent};
    }}
    QPushButton:disabled, QToolButton:disabled {{
        color: {theme.muted};
        background: {theme.alternate};
    }}
    QPushButton#primaryAction {{
        background: {theme.accent};
        color: {theme.accent_text};
        border-color: {theme.accent};
        font-weight: 600;
    }}
    QPushButton#primaryAction:hover {{ background: {theme.surface_hover}; color: {theme.text}; }}

    QFrame#mainActionStrip {{
        background: {theme.alternate};
        border-top: 1px solid {theme.border};
    }}
    QFrame#promptViewBar {{
        background: {theme.surface};
        border: 1px solid {theme.border};
        border-radius: 7px;
    }}
    QLabel#mainImagePreview {{
        background: {theme.base};
        border: 1px solid {theme.border};
        border-radius: 7px;
        color: {theme.muted};
    }}

    QTabWidget::pane {{
        border: 1px solid {theme.border};
        border-radius: 6px;
        top: -1px;
    }}
    QTabBar::tab {{
        background: transparent;
        color: {theme.muted};
        border: 0;
        border-bottom: 2px solid transparent;
        padding: 6px 10px;
        margin-right: 1px;
    }}
    QTabBar::tab:hover {{ color: {theme.text}; background: {theme.surface}; }}
    QTabBar::tab:selected {{
        color: {theme.text};
        border-bottom-color: {theme.accent};
        font-weight: 600;
    }}

    QHeaderView::section {{
        background: {theme.surface};
        color: {theme.text};
        border: 0;
        border-right: 1px solid {theme.border};
        border-bottom: 1px solid {theme.border};
        padding: 5px 6px;
        font-weight: 600;
    }}
    QTableWidget {{ gridline-color: {theme.border}; }}

    QScrollBar:vertical {{ background: transparent; width: 9px; margin: 1px; }}
    QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 1px; }}
    QScrollBar::handle {{
        background: {theme.border};
        min-height: 24px;
        min-width: 24px;
        border-radius: 4px;
    }}
    QScrollBar::handle:hover {{ background: {theme.surface_hover}; }}
    QScrollBar::add-line, QScrollBar::sub-line,
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; width: 0; height: 0; }}

    QSplitter::handle {{ background: {theme.border}; }}
    QSplitter::handle:hover {{ background: {theme.accent}; }}
    QSplitter::handle:horizontal {{ width: 2px; }}
    QSplitter::handle:vertical {{ height: 2px; }}

    QGroupBox {{
        border: 1px solid {theme.border};
        border-radius: 6px;
        margin-top: 8px;
        padding-top: 6px;
        font-weight: 600;
    }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; }}

    QCheckBox, QRadioButton {{ spacing: 5px; }}
    QCheckBox::indicator, QRadioButton::indicator {{ width: 14px; height: 14px; }}

    QToolTip {{
        background: {theme.surface};
        color: {theme.text};
        border: 1px solid {theme.border};
        border-radius: 4px;
        padding: 4px 6px;
    }}
    QLabel {{ background: transparent; }}

    QFrame#previewToolbarOverlay {{
        background-color: {theme.alternate};
        border: 1px solid {theme.border};
        border-radius: 8px;
    }}
    QFrame#previewToolbarOverlay QToolButton {{
        background: transparent;
        border: 0;
        border-radius: 5px;
        padding: 4px 7px;
    }}
    QFrame#previewToolbarOverlay QToolButton:hover {{ background: {theme.surface_hover}; }}
    """)
    return theme


def apply_dark_theme(app: QApplication) -> None:
    apply_theme(app)


def create_splash_pixmap() -> QPixmap:
    """
    Render the branded startup splash using the metaView application icon.
    """
    width = 760
    height = 420

    pixmap = QPixmap(width, height)
    pixmap.fill(QColor("#141414"))

    painter = QPainter(pixmap)

    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        painter.fillRect(0, 0, width, height, QColor("#141414"))
        painter.fillRect(0, height - 8, width, 8, QColor("#3469a5"))

        icon = QPixmap(str(asset_path("metaview.png")))
        if not icon.isNull():
            icon = icon.scaled(
                150,
                150,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            icon_x = 72 + (150 - icon.width()) // 2
            icon_y = 72 + (150 - icon.height()) // 2
            painter.drawPixmap(icon_x, icon_y, icon)

        title_font = QFont("Sans Serif", 36)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(
            QRectF(250, 92, 430, 60),
            Qt.AlignmentFlag.AlignLeft
            | Qt.AlignmentFlag.AlignVCenter,
            "metaView",
        )

        subtitle_font = QFont("Sans Serif", 17)
        painter.setFont(subtitle_font)
        painter.setPen(QColor("#d5d5d5"))
        painter.drawText(
            QRectF(250, 154, 430, 68),
            Qt.AlignmentFlag.AlignLeft
            | Qt.AlignmentFlag.AlignTop,
            "GenAI image browser and metadata analyser.",
        )

        byline_font = QFont("Sans Serif", 12)
        painter.setFont(byline_font)
        painter.setPen(QColor("#9a9a9a"))
        painter.drawText(
            QRectF(72, 320, 616, 36),
            Qt.AlignmentFlag.AlignLeft
            | Qt.AlignmentFlag.AlignVCenter,
            "Broomfield Developments, 2026",
        )

    finally:
        painter.end()

    return pixmap

