"""Main entry point for the keyboard PCB tool application."""

import sys
import os

# Ensure the package directory is on sys.path so internal absolute imports work
# (from models.xxx import ..., from gui.xxx import ..., etc.)
_pkg_dir = os.path.dirname(os.path.abspath(__file__))
if _pkg_dir not in sys.path:
    sys.path.insert(0, _pkg_dir)

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QPalette, QColor
from PyQt5.QtCore import Qt

# Enable high-DPI scaling
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)


def setup_dark_palette(app):
    """Configure a dark theme palette for the application."""
    palette = QPalette()

    background_color = QColor(53, 53, 53)
    foreground_color = QColor(220, 220, 220)

    palette.setColor(QPalette.Window, QColor(45, 45, 45))
    palette.setColor(QPalette.WindowText, foreground_color)
    palette.setColor(QPalette.Button, background_color)
    palette.setColor(QPalette.ButtonText, foreground_color)
    palette.setColor(QPalette.Base, QColor(35, 35, 35))
    palette.setColor(QPalette.AlternateBase, background_color)
    palette.setColor(QPalette.Text, foreground_color)
    palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.HighlightedText, Qt.black)
    palette.setColor(QPalette.ToolTipBase, Qt.white)
    palette.setColor(QPalette.ToolTipText, Qt.white)

    app.setPalette(palette)


def main():
    """Main entry point for the application."""
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    setup_dark_palette(app)

    from gui.main_window import MainWindow
    window = MainWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
