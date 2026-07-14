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
    p = QPalette()
    for role, colour in (
        (QPalette.ColorRole.Window, theme.window), (QPalette.ColorRole.WindowText, theme.text),
        (QPalette.ColorRole.Base, theme.base), (QPalette.ColorRole.AlternateBase, theme.alternate),
        (QPalette.ColorRole.ToolTipBase, theme.surface), (QPalette.ColorRole.ToolTipText, theme.text),
        (QPalette.ColorRole.Text, theme.text), (QPalette.ColorRole.Button, theme.surface),
        (QPalette.ColorRole.ButtonText, theme.text), (QPalette.ColorRole.BrightText, theme.danger),
        (QPalette.ColorRole.Link, theme.accent), (QPalette.ColorRole.Highlight, theme.accent),
        (QPalette.ColorRole.HighlightedText, theme.accent_text), (QPalette.ColorRole.PlaceholderText, theme.muted),
    ):
        p.setColor(role, QColor(colour))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(theme.muted))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(theme.muted))
    app.setPalette(p)
    app.setStyleSheet(f"""
    QMainWindow, QDialog, QWidget {{ background-color:{theme.window}; color:{theme.text}; }}
    QToolBar, QStatusBar, QMenuBar, QMenu {{ background-color:{theme.alternate}; border:none; }}
    QToolBar {{ spacing:6px; padding:4px; border-bottom:1px solid {theme.border}; }}
    QLineEdit,QPlainTextEdit,QTextEdit,QTreeView,QListWidget,QTableWidget,QComboBox {{ background:{theme.base}; color:{theme.text}; border:1px solid {theme.border}; border-radius:4px; selection-background-color:{theme.accent}; selection-color:{theme.accent_text}; }}
    QLineEdit,QComboBox {{ padding:5px 7px; min-height:22px; }}
    QTreeView::item,QListWidget::item {{ padding:3px; }}
    QTreeView::item:selected,QListWidget::item:selected {{ background:{theme.accent}; color:{theme.accent_text}; }}
    QPushButton,QToolButton {{ background:{theme.surface}; color:{theme.text}; border:1px solid {theme.border}; border-radius:4px; padding:5px 9px; }}
    QPushButton:hover,QToolButton:hover {{ background:{theme.surface_hover}; }}
    QPushButton:pressed,QToolButton:pressed,QToolButton:checked {{ background:{theme.accent}; color:{theme.accent_text}; }}
    QPushButton:disabled,QToolButton:disabled {{ color:{theme.muted}; }}
    QTabWidget::pane {{ border:1px solid {theme.border}; }}
    QTabBar::tab {{ background:{theme.alternate}; color:{theme.muted}; border:1px solid {theme.border}; padding:7px 12px; }}
    QTabBar::tab:selected {{ background:{theme.window}; color:{theme.text}; }}
    QHeaderView::section {{ background:{theme.surface}; color:{theme.text}; border:0; border-right:1px solid {theme.border}; border-bottom:1px solid {theme.border}; padding:6px; }}
    QTableWidget {{ gridline-color:{theme.border}; }}
    QScrollBar:vertical {{ background:{theme.alternate}; width:13px; }} QScrollBar:horizontal {{ background:{theme.alternate}; height:13px; }}
    QScrollBar::handle {{ background:{theme.border}; min-height:28px; min-width:28px; border-radius:5px; }} QScrollBar::handle:hover {{ background:{theme.surface_hover}; }}
    QScrollBar::add-line,QScrollBar::sub-line {{ width:0; height:0; }}
    QSplitter::handle {{ background:{theme.border}; }} QSplitter::handle:hover {{ background:{theme.surface_hover}; }}
    QToolTip {{ background:{theme.surface}; color:{theme.text}; border:1px solid {theme.border}; padding:4px; }}
    QComboBox QAbstractItemView {{ background:{theme.base}; color:{theme.text}; selection-background-color:{theme.accent}; }}
    QLabel {{ background:transparent; }}
    QFrame#previewToolbarOverlay {{ background-color:{theme.alternate}; border:1px solid {theme.border}; border-radius:9px; }}
    QFrame#previewToolbarOverlay QToolButton {{ background:transparent; border:0; }}
    QFrame#previewToolbarOverlay QToolButton:hover {{ background:{theme.surface_hover}; }}
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

