"""
Clean flat dark style - no decorations, functional.
"""

STYLE = """
* {
    font-family: -apple-system, "Segoe UI", "Helvetica Neue", sans-serif;
    font-size: 13px;
    color: #e8e8e8;
}

QMainWindow, QDialog {
    background: #0d0d0d;
}

QWidget {
    background: transparent;
}

/* ── Sidebar ──────────────────────────────────────────────────── */
#sidebar {
    background: #111111;
    border-right: 1px solid #222;
    min-width: 200px;
    max-width: 240px;
}

/* ── Top bar ──────────────────────────────────────────────────── */
#topbar {
    background: #0d0d0d;
    border-bottom: 1px solid #1e1e1e;
}

/* ── Bottom bar ───────────────────────────────────────────────── */
#bottombar {
    background: #111111;
    border-top: 1px solid #222;
}

/* ── Buttons ──────────────────────────────────────────────────── */
QPushButton {
    background: #1e1e1e;
    color: #c0c0c0;
    border: 1px solid #2e2e2e;
    border-radius: 3px;
    padding: 5px 12px;
}
QPushButton:hover   { background: #252525; color: #e8e8e8; }
QPushButton:pressed { background: #2a2a2a; }
QPushButton:disabled { color: #444; border-color: #1e1e1e; }

/* Record button - standalone style set in code */

/* ── Labels ───────────────────────────────────────────────────── */
QLabel { background: transparent; color: #e8e8e8; }

QLabel#title {
    font-size: 14px;
    font-weight: 600;
    color: #e8e8e8;
}

QLabel#section {
    font-size: 11px;
    color: #555;
    padding: 8px 12px 2px 12px;
    text-transform: uppercase;
    letter-spacing: 1px;
}

QLabel#status {
    font-size: 12px;
    color: #666;
}

QLabel#live_badge {
    font-size: 11px;
    color: #f59e0b;
}

/* ── Inputs ───────────────────────────────────────────────────── */
QComboBox {
    background: #1a1a1a;
    color: #c0c0c0;
    border: 1px solid #2a2a2a;
    border-radius: 3px;
    padding: 4px 8px;
}
QComboBox::drop-down { border: none; width: 16px; }
QComboBox QAbstractItemView {
    background: #1e1e1e;
    color: #c0c0c0;
    border: 1px solid #333;
    selection-background-color: #2a2a2a;
    outline: none;
}

QLineEdit {
    background: transparent;
    color: #e8e8e8;
    border: none;
    border-bottom: 1px solid #2a2a2a;
    border-radius: 0;
    padding: 4px 2px;
    font-size: 14px;
    font-weight: 600;
}
QLineEdit:focus { border-bottom-color: #3b82f6; }

/* ── Text areas ───────────────────────────────────────────────── */
QTextEdit, QPlainTextEdit {
    background: #0d0d0d;
    color: #d8d8d8;
    border: none;
    padding: 12px;
    font-size: 13px;
    line-height: 1.6;
    selection-background-color: #2a3a5a;
}

/* ── Tabs ─────────────────────────────────────────────────────── */
QTabWidget::pane {
    border: none;
    border-top: 1px solid #1e1e1e;
    background: #0d0d0d;
}
QTabBar {
    background: #0d0d0d;
}
QTabBar::tab {
    background: transparent;
    color: #555;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 8px 16px;
    font-size: 12px;
}
QTabBar::tab:selected {
    color: #e8e8e8;
    border-bottom-color: #3b82f6;
}
QTabBar::tab:hover { color: #aaa; }

/* ── Progress ─────────────────────────────────────────────────── */
QProgressBar {
    background: #1a1a1a;
    border: none;
    border-radius: 1px;
    height: 2px;
}
QProgressBar::chunk {
    background: #3b82f6;
    border-radius: 1px;
}

/* ── List ─────────────────────────────────────────────────────── */
QListWidget {
    background: transparent;
    border: none;
    outline: none;
}
QListWidget::item {
    color: #aaa;
    padding: 6px 12px;
    border-bottom: 1px solid #1a1a1a;
}
QListWidget::item:selected { background: #1e1e1e; color: #e8e8e8; }
QListWidget::item:hover    { background: #161616; color: #ccc; }

/* ── Scrollbars ───────────────────────────────────────────────── */
QScrollBar:vertical {
    background: transparent;
    width: 5px;
}
QScrollBar::handle:vertical {
    background: #333;
    border-radius: 2px;
    min-height: 20px;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical { background: transparent; }

/* ── Status bar ───────────────────────────────────────────────── */
QStatusBar {
    background: #0d0d0d;
    color: #444;
    font-size: 11px;
    border-top: 1px solid #1a1a1a;
}

/* ── Splitter ─────────────────────────────────────────────────── */
QSplitter::handle {
    background: #1e1e1e;
    width: 1px;
    height: 1px;
}

/* ── Menus ────────────────────────────────────────────────────── */
QMenu {
    background: #1e1e1e;
    color: #c0c0c0;
    border: 1px solid #333;
    border-radius: 3px;
    padding: 3px;
}
QMenu::item { padding: 6px 18px; }
QMenu::item:selected { background: #2a2a2a; }
QMenu::separator { height: 1px; background: #2a2a2a; margin: 3px 0; }

/* ── Message box ──────────────────────────────────────────────── */
QMessageBox {
    background: #161616;
}
QMessageBox QLabel { color: #c0c0c0; }
"""

SPEAKER_COLORS = [
    "#5b8af0",   # blue
    "#4ade80",   # green
    "#fb923c",   # orange
    "#f472b6",   # pink
    "#a78bfa",   # violet
    "#38bdf8",   # sky
    "#fbbf24",   # amber
    "#f87171",   # red
]
