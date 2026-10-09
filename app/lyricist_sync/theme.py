"""Liquid-glass look: palette, colors and the Qt style sheet for dark and light."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPalette

from . import paths, winfx

ACCENT = '#FF6A01'          # Ax-Easy orange (www.ax-easy.com)
ACCENT_2 = '#FF9A3D'


def system_is_dark():
    d = winfx.apps_use_dark()
    if d is not None:
        return d
    try:
        cs = QGuiApplication.styleHints().colorScheme()
        if cs == Qt.ColorScheme.Light:
            return False
    except Exception:
        pass
    return True  # default dark


class Theme:
    def __init__(self, dark=True):
        self.dark = dark
        if dark:
            self.text, self.sub, self.faint = '#F2F4F8', '#AEB4C0', '#7D8494'
            self.card = (255, 255, 255, 16)
            self.card_top = (255, 255, 255, 26)
            self.card_border = (255, 255, 255, 34)
            self.field = 'rgba(255,255,255,0.07)'
            self.field_hover = 'rgba(255,255,255,0.10)'
            self.field_border = 'rgba(255,255,255,0.13)'
            self.sel = 'rgba(255,106,1,0.30)'
            self.tint = (17, 19, 26, 178)        # over acrylic/mica: keeps text contrast >= 7:1
            self.bg_top, self.bg_bottom = '#1D2029', '#111319'
            self.glow1, self.glow2 = (255, 106, 1, 46), (64, 120, 255, 40)
            self.shadow = (0, 0, 0, 70)
        else:
            self.text, self.sub, self.faint = '#14171F', '#4A5160', '#79808E'
            self.card = (255, 255, 255, 150)
            self.card_top = (255, 255, 255, 205)
            self.card_border = (255, 255, 255, 230)
            self.field = 'rgba(255,255,255,0.70)'
            self.field_hover = 'rgba(255,255,255,0.90)'
            self.field_border = 'rgba(20,25,40,0.13)'
            self.sel = 'rgba(255,106,1,0.20)'
            self.tint = (240, 243, 248, 190)
            self.bg_top, self.bg_bottom = '#EEF1F7', '#DCE2EC'
            self.glow1, self.glow2 = (255, 140, 60, 60), (90, 140, 255, 50)
            self.shadow = (30, 40, 70, 34)
        self.accent = ACCENT
        self.accent2 = ACCENT_2

    def qcolor(self, rgba):
        return QColor(*rgba)

    def palette(self):
        p = QPalette()
        text, sub = QColor(self.text), QColor(self.sub)
        base = QColor(self.bg_bottom)
        for role, col in ((QPalette.Window, QColor(self.bg_top)), (QPalette.WindowText, text), (QPalette.Base, base),
                          (QPalette.AlternateBase, QColor(self.bg_top)), (QPalette.Text, text), (QPalette.Button, QColor(self.bg_top)),
                          (QPalette.ButtonText, text), (QPalette.ToolTipBase, QColor(self.bg_top)), (QPalette.ToolTipText, text),
                          (QPalette.PlaceholderText, QColor(self.faint)), (QPalette.Highlight, QColor(ACCENT)),
                          (QPalette.HighlightedText, QColor('#ffffff')), (QPalette.Link, QColor(ACCENT)),
                          (QPalette.LinkVisited, QColor(ACCENT))):
            p.setColor(role, col)
        p.setColor(QPalette.Disabled, QPalette.Text, QColor(self.faint))
        p.setColor(QPalette.Disabled, QPalette.WindowText, QColor(self.faint))
        p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(self.faint))
        return p

    def qss(self):
        chev = paths.resource('res', 'chevron_%s.svg' % ('dark' if self.dark else 'light')).replace('\\', '/')
        check = paths.resource('res', 'check.svg').replace('\\', '/')
        menu_bg = 'rgba(30,33,42,0.97)' if self.dark else 'rgba(250,251,253,0.98)'
        return f"""
* {{ color: {self.text}; outline: none; }}
QWidget {{ background: transparent; }}
QLabel#h1 {{ font-size: 15px; font-weight: 600; }}
QLabel#sub, QLabel#hint {{ color: {self.sub}; }}
QLabel#footer {{ color: {self.sub}; font-size: 12px; }}
QLabel#title {{ font-size: 13px; font-weight: 600; }}
QLineEdit, QPlainTextEdit, QComboBox, QDoubleSpinBox {{
  background: {self.field}; border: 1px solid {self.field_border}; border-radius: 10px;
  padding: 6px 10px; selection-background-color: {ACCENT}; selection-color: #fff; }}
QPlainTextEdit {{ padding: 8px 10px; font-size: 13px; }}
QLineEdit:hover, QComboBox:hover, QPlainTextEdit:hover {{ background: {self.field_hover}; }}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border: 1px solid {ACCENT}; }}
QComboBox {{ padding-right: 26px; min-height: 20px; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url({chev}); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {menu_bg}; border: 1px solid {self.field_border}; border-radius: 10px;
  padding: 4px; selection-background-color: {self.sel}; selection-color: {self.text}; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 6px; border: 1px solid {self.field_border}; background: {self.field}; }}
QCheckBox::indicator:hover {{ border: 1px solid {ACCENT}; }}
QCheckBox::indicator:checked {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {ACCENT_2}, stop:1 {ACCENT});
  border: 1px solid rgba(255,255,255,0.25); image: url({check}); }}
QTableView {{ background: transparent; border: none; gridline-color: transparent; font-size: 13px;
  selection-background-color: transparent; alternate-background-color: transparent; }}
QTableView::item {{ padding: 4px 8px; border: none; }}
QHeaderView {{ background: transparent; border: none; }}
QHeaderView::section {{ background: transparent; color: {self.sub}; border: none; padding: 4px 8px; font-size: 12px; font-weight: 600; }}
QTableCornerButton::section {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: rgba(128,128,128,0.35); border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: rgba(128,128,128,0.55); }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px 4px; }}
QScrollBar::handle:horizontal {{ background: rgba(128,128,128,0.35); border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; border: none; width: 0; height: 0; }}
QMenu {{ background: {menu_bg}; border: 1px solid {self.field_border}; border-radius: 12px; padding: 6px; }}
QMenu::item {{ padding: 7px 18px; border-radius: 8px; }}
QMenu::item:selected {{ background: {self.sel}; }}
QMenu::separator {{ height: 1px; background: {self.field_border}; margin: 4px 8px; }}
QToolTip {{ background: {menu_bg}; color: {self.text}; border: 1px solid {self.field_border}; border-radius: 8px; padding: 5px 8px; }}
QProgressBar {{ background: {self.field}; border: 1px solid {self.field_border}; border-radius: 7px; height: 14px; text-align: center; font-size: 11px; }}
QProgressBar::chunk {{ border-radius: 6px; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {ACCENT_2}, stop:1 {ACCENT}); }}
QMessageBox {{ background: {self.bg_top}; }}
QLabel#h2 {{ font-size: 14px; font-weight: 600; }}
QTextBrowser#exportList, QTextBrowser#askList {{ background: {self.field}; border: 1px solid {self.field_border};
  border-radius: 10px; padding: 8px 10px; font-size: 13px; }}
QLineEdit#inlineEdit {{ border: 1px solid {ACCENT}; border-radius: 7px; padding: 2px 8px; background: {self.field_hover}; }}
QLineEdit#editText {{ font-size: 14px; padding: 8px 12px; }}
"""


def apply_platform_style(qapp):
    """macOS: Fusion under the app's style sheets. The native macOS style ignores parts of them (check box
    indicators drawn over their labels, fixed button paddings that clip text); Windows keeps its native style."""
    import sys
    if sys.platform == 'darwin' and qapp.style().name().lower() != 'fusion':
        qapp.setStyle('Fusion')


def ui_font():
    import sys
    if sys.platform == 'darwin':   # San Francisco (the system font); 12 pt fits the layout made for Segoe UI 10 pt
        f = QFont()
        f.setPointSizeF(12)
        return f
    fams = set(QFontDatabase.families())
    for name in ('Segoe UI Variable Text', 'Segoe UI Variable', 'Segoe UI', 'Inter', 'Noto Sans', 'DejaVu Sans'):
        if name in fams:
            f = QFont(name)
            f.setPointSizeF(10)
            f.setHintingPreference(QFont.PreferNoHinting)
            return f
    return QFont()


def display_family():
    fams = set(QFontDatabase.families())
    for name in ('Segoe UI Variable Display', 'Segoe UI Variable', 'Segoe UI', 'Inter', 'Noto Sans'):
        if name in fams:
            return name
    return QFont().family()
