#!/usr/bin/env python3
"""Flatpak & Snap Package Manager - Entry Point"""

import sys
import os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt
from ui import MainWindow

APP_ID = "io.github.sametkarakus68.PackageManager"

# QMenu stylesheet applied at QApplication level — this fixes the native
# edit context menu (clic droit sur texte sélectionné) in flatpak.
# IMPORTANT: Do NOT call self.setStyleSheet() on MainWindow — it overrides this.
_QMENU_DARK = """
QMenu {
    background-color: #2a2a2e;
    color: #ffffff;
    border: 1px solid #404040;
    border-radius: 4px;
    padding: 2px 0;
}
QMenu::item {
    background-color: transparent;
    padding: 6px 30px 6px 20px;
    border-radius: 2px;
}
QMenu::item:selected {
    background-color: #4a9eff;
    color: #000000;
}
QMenu::item:disabled {
    color: #666666;
}
QMenu::separator {
    background-color: #404040;
    height: 1px;
    margin: 4px 8px;
}
"""

_QMENU_LIGHT = """
QMenu {
    background-color: #ffffff;
    color: #1a1a1a;
    border: 1px solid #cccccc;
    border-radius: 4px;
    padding: 2px 0;
}
QMenu::item {
    background-color: transparent;
    padding: 6px 30px 6px 20px;
    border-radius: 2px;
}
QMenu::item:selected {
    background-color: #4a9eff;
    color: #ffffff;
}
QMenu::item:disabled {
    color: #999999;
}
QMenu::separator {
    background-color: #e0e0e0;
    height: 1px;
    margin: 4px 8px;
}
"""


def _detect_system_theme():
    """Detect if the system prefers dark mode."""
    import configparser
    kdeglobals = os.path.expanduser("~/.config/kdeglobals")
    if os.path.exists(kdeglobals):
        try:
            config = configparser.ConfigParser(interpolation=None)
            config.read(kdeglobals)
            if "General" in config:
                scheme = config["General"].get("ColorScheme", "")
                if scheme.lower() in ("breezedark", "breeze-dark", "dark"):
                    return True
        except Exception:
            pass
    return False


def main():
    app = QApplication(sys.argv)

    # Set Fusion style and ColorScheme hint
    app.setStyle("Fusion")
    if _detect_system_theme():
        app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    else:
        app.styleHints().setColorScheme(Qt.ColorScheme.Light)

    # Apply QMenu stylesheet at APPLICATION level only.
    # Do NOT call self.setStyleSheet() on MainWindow — it overrides this.
    app.setStyleSheet(_QMENU_DARK if _detect_system_theme() else _QMENU_LIGHT)

    app.setApplicationName("Package Manager")
    app.setDesktopFileName(APP_ID)

    # Icon path: try Flatpak path first, then .deb system path, then local dev path
    icon_paths = [
        f"/app/share/icons/hicolor/256x256/apps/{APP_ID}.png",  # Flatpak
        "/usr/share/icons/hicolor/256x256/apps/pkg-manager.png",  # .deb
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png"),  # Dev
    ]
    icon_path = next((p for p in icon_paths if os.path.exists(p)), "")
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
