"""Koyu, sade tema. Knight Online'dan hafifçe esinlenen soluk altın vurgu rengi."""

BG = "#17191d"
PANEL = "#1f2227"
PANEL_2 = "#262a30"
BORDER = "#343940"
TEXT = "#e4e4e4"
MUTED = "#9aa1a9"
ACCENT = "#c9a45c"
ACCENT_DARK = "#8f7440"
GREEN = "#6cc08b"
RED = "#e0707a"
BLUE = "#7aa7d8"

QSS = f"""
* {{
    font-family: "Segoe UI", "Noto Sans", Arial, sans-serif;
    font-size: 10pt;
    color: {TEXT};
}}
QMainWindow, QDialog, QWidget#Root {{ background: {BG}; }}
QWidget {{ background: transparent; }}
QToolTip {{ background: {PANEL_2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px; }}

/* Sol menü */
QListWidget#Nav {{
    background: {PANEL}; border: none; border-right: 1px solid {BORDER};
    padding-top: 8px; outline: 0;
}}
QListWidget#Nav::item {{ padding: 10px 16px; margin: 1px 8px; border-radius: 6px; color: {MUTED}; }}
QListWidget#Nav::item:hover {{ background: {PANEL_2}; color: {TEXT}; }}
QListWidget#Nav::item:selected {{ background: {PANEL_2}; color: {ACCENT}; border-left: 3px solid {ACCENT}; }}
QLabel#Brand {{ color: {ACCENT}; font-size: 12pt; font-weight: 600; padding: 14px 16px 4px 16px; background: {PANEL}; }}
QLabel#BrandSub {{ color: {MUTED}; font-size: 8.5pt; padding: 0 16px 10px 16px; background: {PANEL}; }}
QWidget#NavPanel {{ background: {PANEL}; border-right: 1px solid {BORDER}; }}

QLabel#PageTitle {{ font-size: 15pt; font-weight: 600; padding-bottom: 2px; }}
QLabel#Muted, QLabel[muted="true"] {{ color: {MUTED}; }}
QLabel#Section {{ font-size: 11pt; font-weight: 600; color: {TEXT}; padding-top: 6px; }}

/* Kartlar */
QFrame#Card {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px; }}
QLabel#CardTitle {{ color: {MUTED}; font-size: 9pt; }}
QLabel#CardValue {{ font-size: 14pt; font-weight: 600; }}
QLabel#CardSub {{ color: {MUTED}; font-size: 8.5pt; }}
QFrame#Box {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px; }}

QGroupBox {{
    background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px;
    margin-top: 14px; padding: 12px 10px 10px 10px;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {ACCENT}; font-weight: 600; }}

/* Girişler */
QLineEdit, QSpinBox, QDoubleSpinBox, QDateEdit, QComboBox, QPlainTextEdit {{
    background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 5px;
    padding: 5px 7px; selection-background-color: {ACCENT_DARK};
}}
QLineEdit:focus, QSpinBox:focus, QDateEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{ border: 1px solid {ACCENT}; }}
QLineEdit[invalid="true"] {{ border: 1px solid {RED}; }}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{ color: {MUTED}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {PANEL_2}; border: 1px solid {BORDER}; selection-background-color: {ACCENT_DARK}; }}
QSpinBox::up-button, QSpinBox::down-button, QDateEdit::up-button, QDateEdit::down-button {{ width: 16px; }}
QCalendarWidget QWidget {{ background: {PANEL_2}; }}
QCalendarWidget QAbstractItemView:enabled {{ background: {PANEL_2}; selection-background-color: {ACCENT_DARK}; }}

/* Butonlar */
QPushButton, QToolButton {{
    background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 14px;
}}
QPushButton:hover, QToolButton:hover {{ border-color: {ACCENT_DARK}; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton:disabled {{ color: {MUTED}; border-color: {PANEL_2}; }}
QPushButton#Primary {{ background: {ACCENT}; color: #1b1b1b; border: 1px solid {ACCENT}; font-weight: 600; }}
QPushButton#Primary:hover {{ background: #d6b46e; }}
QPushButton#Primary:disabled {{ background: {ACCENT_DARK}; color: #2a2a2a; }}
QPushButton#Danger {{ border-color: #6a3a3f; color: {RED}; }}
QPushButton#Danger:hover {{ background: #3a2326; }}
QPushButton[seg="true"] {{ border-radius: 0; padding: 5px 12px; }}
QPushButton[seg="true"]:checked {{ background: {ACCENT_DARK}; color: {TEXT}; border-color: {ACCENT}; }}
QToolButton#Mini {{ padding: 3px 6px; font-size: 8.5pt; color: {MUTED}; }}

QRadioButton, QCheckBox {{ spacing: 6px; }}

/* Tablolar */
QTableWidget, QTableView {{
    background: {PANEL}; alternate-background-color: #22252b; border: 1px solid {BORDER};
    border-radius: 6px; gridline-color: {BORDER}; selection-background-color: #3b3527; selection-color: {TEXT};
}}
QHeaderView::section {{
    background: {PANEL_2}; color: {MUTED}; padding: 6px; border: none; border-bottom: 1px solid {BORDER};
    border-right: 1px solid {BORDER}; font-weight: 600;
}}
QTableCornerButton::section {{ background: {PANEL_2}; border: none; }}

QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 6px; top: -1px; background: {BG}; }}
QTabBar::tab {{ background: {PANEL}; border: 1px solid {BORDER}; padding: 7px 18px; margin-right: 2px;
               border-top-left-radius: 6px; border-top-right-radius: 6px; color: {MUTED}; }}
QTabBar::tab:selected {{ background: {PANEL_2}; color: {ACCENT}; border-bottom-color: {PANEL_2}; }}

QScrollBar:vertical {{ background: {PANEL}; width: 11px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 24px; }}
QScrollBar:horizontal {{ background: {PANEL}; height: 11px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 5px; min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollArea {{ border: none; }}
QSplitter::handle {{ background: {BG}; }}
QMessageBox QLabel {{ min-width: 280px; }}
"""
