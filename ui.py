#!/usr/bin/env python3
"""Flatpak & Snap Package Manager - PyQt6 GUI"""

import os
import sys
import json
import threading
import subprocess
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLineEdit,
    QLabel,
    QTabWidget,
    QScrollArea,
    QFrame,
    QCheckBox,
    QFileDialog,
    QMessageBox,
    QSizePolicy,
    QProgressBar,
    QComboBox,
    QDialog,
    QTextEdit,
    QListWidget,
    QListWidgetItem,
)
from PyQt6.QtCore import (
    Qt,
    QTimer,
    pyqtSignal,
    QObject,
    QPropertyAnimation,
    QEasingCurve,
    QSize,
    QThread,
)
from PyQt6.QtGui import QFont, QColor, QIcon, QPalette

from core import PackageManager, ShortcutManager, Package


class WorkerSignals(QObject):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)
    uninstall_done = pyqtSignal(object)


class ReinstallDialog(QDialog):
    """Dialog showing reinstall progress with log output."""
    log_signal = pyqtSignal(str)
    done_signal = pyqtSignal(int, int, list)

    def __init__(self, packages, parent=None):
        super().__init__(parent)
        self.pkgs = packages if isinstance(packages, list) else [packages]
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowTitle("Reinstall Packages")
        self.setMinimumSize(550, 400)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        self.status_label = QLabel(f"Reinstalling {len(self.pkgs)} package(s)...")
        self.status_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(self.status_label)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet("""
            QTextEdit {
                background-color: #1a1a2e;
                color: #e0e0e0;
                font-family: monospace;
                font-size: 12px;
                border: 1px solid #404040;
                border-radius: 4px;
                padding: 8px;
            }
        """)
        layout.addWidget(self.log_area, 1)

        self.button_box = QHBoxLayout()
        self.button_box.addStretch()
        self.done_btn = QPushButton("Done")
        self.done_btn.setStyleSheet("""
            QPushButton {
                background-color: #4a9eff;
                color: #000000;
                border: none;
                border-radius: 4px;
                padding: 8px 24px;
                font-weight: bold;
                font-size: 13px;
            }
        """)
        self.done_btn.setEnabled(False)
        self.done_btn.clicked.connect(self.accept)
        self.button_box.addWidget(self.done_btn)
        layout.addLayout(self.button_box)

        self._log("")

        # Connect signals to UI slots (thread-safe)
        self.log_signal.connect(self._append_log)
        self.done_signal.connect(self._on_worker_done)

    def _log(self, msg):
        """Thread-safe: emits signal to update UI from main thread."""
        self.log_signal.emit(msg)

    def _append_log(self, msg):
        """Actually update the UI (must be called from main thread)."""
        self.log_area.append(msg)
        self.log_area.verticalScrollBar().setValue(
            self.log_area.verticalScrollBar().maximum()
        )

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(50, self._start_reinstall)

    def _start_reinstall(self):
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        pkg_mgr = self.parent().pkg_mgr
        errors = []
        ok_count = 0

        for pkg in self.pkgs:
            self._log(f"─────────────────────────────")
            self._log(f"📦 {pkg.name} ({pkg.pkg_type})")

            if pkg.pkg_type == "flatpak":
                remote = pkg.origin or "flathub"
                ok, logs = pkg_mgr.reinstall_flatpak(pkg.pkg_id, remote)
            elif pkg.pkg_type == "snap":
                ok, logs = pkg_mgr.reinstall_snap(pkg.pkg_id)
            else:
                logs = [f"  SKIP: unsupported type {pkg.pkg_type}"]
                ok = False

            for line in logs:
                self._log(f"  {line}")
            if ok:
                ok_count += 1
                # Check / create launcher shortcut after successful reinstall
                self._log(f"  🔍 Checking launcher shortcut...")
                shortcut_ok, shortcut_msg = pkg_mgr.ensure_launcher_shortcut(pkg)
                self._log(f"     {shortcut_msg}")
                self._log(f"  ✅ Done")
            else:
                errors.append(pkg.name)

        self._log(f"─────────────────────────────")
        if errors:
            self._log(f"⚠ {ok_count}/{len(self.pkgs)} succeeded")
            self._log(f"Failed: {', '.join(errors)}")
        else:
            self._log(f"✅ All {ok_count}/{len(self.pkgs)} reinstalled successfully")

        # Signal main thread that we're done
        self.done_signal.emit(ok_count, len(self.pkgs), errors)

    def _on_worker_done(self, ok_count, total, errors):
        """Called from main thread when worker finishes."""
        self.status_label.setText("Reinstall complete")
        self.done_btn.setEnabled(True)
        # Refresh package list
        if hasattr(self.parent(), "_refresh_packages_async"):
            self.parent()._refresh_packages_async()


class Toast(QFrame):
    def __init__(self, message, toast_type="info", parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedHeight(48)
        self.setFixedWidth(500)

        border_color = {
            "info": "#4a9eff",
            "success": "#4caf50",
            "error": "#f44336",
            "warning": "#ff9800",
        }.get(toast_type, "#4a9eff")
        self.setStyleSheet(f"""
            QFrame {{
                background-color: #2a2a2e;
                border: 1px solid {border_color};
                border-radius: 8px;
            }}
            QLabel {{
                color: #ffffff;
                font-size: 13px;
                padding: 0 14px;
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 6, 14, 6)
        icon = {"info": "ℹ", "success": "✓", "error": "✗", "warning": "⚠"}.get(
            toast_type, "ℹ"
        )
        layout.addWidget(QLabel(f"{icon}  {message}"))

        self.animation = QPropertyAnimation(self, b"windowOpacity")
        self.animation.setDuration(300)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutQuad)

    def show_toast(self):
        parent = self.parent()
        if parent:
            pw, ph = parent.width(), parent.height()
            self.move(pw - self.width() - 20, 20)
        self.setWindowOpacity(0)
        self.show()
        self.raise_()
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.start()
        QTimer.singleShot(3500, self.fade_out)

    def fade_out(self):
        self.animation.setStartValue(1.0)
        self.animation.setEndValue(0.0)
        self.animation.finished.connect(self.close)
        self.animation.start()


class InstallWorker(QThread):
    progress = pyqtSignal(int, int, str, str)
    finished = pyqtSignal(list, list)

    def __init__(self, packages, pkg_mgr):
        super().__init__()
        self.packages = packages
        self.pkg_mgr = pkg_mgr
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _pkg_type(self, p):
        return p.get("pkg_type") or p.get("type", "")

    def _pkg_id(self, p):
        return p.get("pkg_id") or p.get("id", "")

    def run(self):
        success = []
        failed = []

        flatpak_pkgs = [p for p in self.packages if self._pkg_type(p) == "flatpak"]
        snap_pkgs = [p for p in self.packages if self._pkg_type(p) == "snap"]

        total = len(self.packages)
        done = 0

        # Install snaps using pkg_mgr method (handles sandbox correctly)
        for pkg in snap_pkgs:
            if self._cancelled:
                break
            self.progress.emit(done, total, pkg.get("name", ""), "Installing snap...")
            ok, err = self.pkg_mgr.install_snap(self._pkg_id(pkg))
            done += 1
            if ok:
                success.append(pkg)
                self._ensure_shortcut(pkg)
            else:
                failed.append((pkg, err))

        # Install flatpaks
        for pkg in flatpak_pkgs:
            if self._cancelled:
                break
            self.progress.emit(done, total, pkg.get("name", "Unknown"), "Installing...")
            ok, err = self.pkg_mgr.install_flatpak(self._pkg_id(pkg))
            done += 1
            if ok:
                success.append(pkg)
                self._ensure_shortcut(pkg)
            else:
                failed.append((pkg, err))

        self.finished.emit(success, failed)

    def _ensure_shortcut(self, pkg_dict):
        """Build Package object from JSON dict and ensure launcher shortcut exists."""
        from core import Package
        pkg = Package(
            pkg_id=self._pkg_id(pkg_dict),
            name=pkg_dict.get("name", "Unknown"),
            version=pkg_dict.get("version", ""),
            pkg_type=self._pkg_type(pkg_dict),
            description=pkg_dict.get("description", ""),
            size=pkg_dict.get("size", ""),
            launch_cmd=pkg_dict.get("launch_cmd", ""),
        )
        self.pkg_mgr.ensure_launcher_shortcut(pkg)


class InstallDialog(QDialog):
    def __init__(
        self, json_data, installed_packages, pkg_mgr, dark_mode=True, parent=None
    ):
        super().__init__(parent)
        self.pkg_mgr = pkg_mgr
        self.json_data = json_data
        self.installed_ids = {(p.pkg_id, p.pkg_type) for p in installed_packages}
        self.worker = None
        self.dark_mode = dark_mode

        self.setWindowTitle("Install from Backup")
        self.setMinimumSize(600, 500)
        self._apply_palette()
        self._build_ui()

    def _apply_palette(self):
        palette = QPalette()
        if self.dark_mode:
            palette.setColor(QPalette.ColorRole.Window, QColor("#1e1e1e"))
            palette.setColor(QPalette.ColorRole.WindowText, QColor("#ffffff"))
            palette.setColor(QPalette.ColorRole.Base, QColor("#2d2d2d"))
            palette.setColor(QPalette.ColorRole.Text, QColor("#ffffff"))
            palette.setColor(QPalette.ColorRole.Button, QColor("#3d3d3d"))
            palette.setColor(QPalette.ColorRole.ButtonText, QColor("#ffffff"))
        else:
            palette.setColor(QPalette.ColorRole.Window, QColor("#f0f0f0"))
            palette.setColor(QPalette.ColorRole.WindowText, QColor("#1a1a1a"))
            palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
            palette.setColor(QPalette.ColorRole.Text, QColor("#1a1a1a"))
            palette.setColor(QPalette.ColorRole.Button, QColor("#e0e0e0"))
            palette.setColor(QPalette.ColorRole.ButtonText, QColor("#1a1a1a"))
        self.setPalette(palette)

    def _theme_color(self, dark, light):
        return dark if self.dark_mode else light

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        missing = []
        for item in self.json_data:
            pkg_id = item.get("id", "")
            pkg_type = item.get("type", "")
            if (pkg_id, pkg_type) not in self.installed_ids:
                missing.append(item)

        if not missing:
            layout.addWidget(
                QLabel("All packages from the backup are already installed.")
            )
            btn = QPushButton("OK")
            btn.setStyleSheet(self._btn_style("#607d8b"))
            btn.clicked.connect(self.accept)
            layout.addWidget(btn)
            return

        header = QLabel(f"{len(missing)} packages to install:")
        header.setStyleSheet(
            f"font-size: 14px; font-weight: bold; color: {self._theme_color('#ffffff', '#1a1a1a')};"
        )
        layout.addWidget(header)

        bg = self._theme_color("#2d2d2d", "#ffffff")
        fg = self._theme_color("#ffffff", "#1a1a1a")
        bd = self._theme_color("#404040", "#cccccc")
        ibd = self._theme_color("#3a3a3a", "#e0e0e0")

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background-color: {bg};
                color: {fg};
                border: 1px solid {bd};
                border-radius: 6px;
                padding: 4px;
            }}
            QListWidget::item {{
                padding: 6px;
                border-bottom: 1px solid {ibd};
                color: {fg};
            }}
            QListWidget::item:selected {{
                background-color: #4a9eff;
                color: #000000;
            }}
        """)
        for item in missing:
            name = item.get("name", "Unknown")
            pkg_type = item.get("type", "?").upper()
            size = item.get("size", "")
            desc = item.get("description", "")[:60]
            text = f"{name}  [{pkg_type}]  {size}  -  {desc}"
            li = QListWidgetItem(text)
            li.setFlags(li.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            li.setCheckState(Qt.CheckState.Checked)
            li.setData(Qt.ItemDataRole.UserRole, item)
            self.list_widget.addItem(li)
        layout.addWidget(self.list_widget)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("Ready")
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {bg};
                border: 1px solid {bd};
                border-radius: 4px;
                height: 20px;
                text-align: center;
                color: {fg};
            }}
            QProgressBar::chunk {{
                background-color: #4a9eff;
                border-radius: 3px;
            }}
        """)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Select packages and click Install")
        self.status_label.setStyleSheet(
            f"color: {self._theme_color('#aaaaaa', '#666666')}; font-size: 12px;"
        )
        layout.addWidget(self.status_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setStyleSheet(self._btn_style("#607d8b"))
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)

        self.install_btn = QPushButton("Install Selected")
        self.install_btn.setStyleSheet(self._btn_style("#4caf50"))
        self.install_btn.clicked.connect(self._start_install)
        btn_row.addWidget(self.install_btn)

        layout.addLayout(btn_row)

    def _btn_style(self, color):
        fg = self._theme_color("#ffffff", "#ffffff")
        return f"""
            QPushButton {{
                background-color: {color};
                color: {fg};
                border: none;
                border-radius: 6px;
                padding: 8px 20px;
                font-weight: bold;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {color}dd;
            }}
        """

    def _get_selected(self):
        selected = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(item.data(Qt.ItemDataRole.UserRole))
        return selected

    def _start_install(self):
        selected = self._get_selected()
        if not selected:
            self.status_label.setText("No packages selected")
            return

        self.install_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.list_widget.setEnabled(False)

        self.worker = InstallWorker(selected, self.pkg_mgr)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_install_finished)
        self.worker.start()

    def _on_progress(self, current, total, name, status):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.progress_bar.setFormat(f"{current}/{total}")
        self.status_label.setText(f"Installing: {name}...")

    def _on_install_finished(self, success, failed):
        total = len(success) + len(failed)
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(total)
        self.progress_bar.setFormat(f"{total}/{total}")

        if failed:
            errors = "\n".join(f"  - {p.get('name', '?')}: {e}" for p, e in failed)
            self.status_label.setText(
                f"Done: {len(success)} succeeded, {len(failed)} failed"
            )
            QMessageBox.warning(
                self,
                "Installation Complete",
                f"Installed: {len(success)}\nFailed: {len(failed)}\n\n{errors}",
            )
        else:
            self.status_label.setText(
                f"All {len(success)} packages installed successfully!"
            )
            QMessageBox.information(
                self,
                "Installation Complete",
                f"All {len(success)} packages installed successfully!",
            )
        for p, e in failed:
            logging.error(f"  FAILED: {p.get('name')} error={e}")
        total = len(success) + len(failed)
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(total)
        self.progress_bar.setFormat(f"{total}/{total}")

        if failed:
            errors = "\n".join(f"  - {p.get('name', '?')}: {e}" for p, e in failed)
            self.status_label.setText(
                f"Done: {len(success)} succeeded, {len(failed)} failed"
            )
            QMessageBox.warning(
                self,
                "Installation Complete",
                f"Installed: {len(success)}\nFailed: {len(failed)}\n\n{errors}",
            )
        else:
            self.status_label.setText(
                f"All {len(success)} packages installed successfully!"
            )
            QMessageBox.information(
                self,
                "Installation Complete",
                f"All {len(success)} packages installed successfully!",
            )

        self.install_btn.setEnabled(True)
        self.cancel_btn.setText("Close")
        self.cancel_btn.clicked.disconnect()
        self.cancel_btn.clicked.connect(self.accept)


class PackageCard(QFrame):
    def __init__(self, pkg: Package, theme_styles=None, parent=None):
        super().__init__(parent)
        self.pkg = pkg
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("packageCard")

        ts = theme_styles or {}
        card_style = ts.get("_card_dup") if pkg.is_duplicate else ts.get("_card_normal")
        if card_style:
            self.setStyleSheet(card_style)

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        top_row = QHBoxLayout()
        self.checkbox = QCheckBox()
        self.checkbox.setStyleSheet(ts.get("_cb_style", ""))
        top_row.addWidget(self.checkbox)

        name_label = QLabel(pkg.name)
        name_label.setStyleSheet(
            f"color: {ts.get('_text', '#ffffff')}; font-size: 15px; font-weight: bold;"
        )
        name_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        top_row.addWidget(name_label)

        type_badge = QLabel(f" {pkg.pkg_type.upper()} ")
        badge_color = "#4a9eff" if pkg.pkg_type == "flatpak" else "#ff9800"
        type_badge.setStyleSheet(f"""
            background-color: {badge_color};
            color: #000000;
            border-radius: 4px;
            font-size: 10px;
            font-weight: bold;
            padding: 2px 6px;
        """)
        top_row.addWidget(type_badge)

        version_label = QLabel(f"v{pkg.version}")
        version_label.setStyleSheet(
            f"color: {ts.get('_subtext', '#888888')}; font-size: 12px;"
        )
        version_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        top_row.addWidget(version_label)

        if pkg.has_desktop_entry:
            desktop_badge = QLabel(" 📌 Launcher")
            desktop_badge.setStyleSheet("color: #4caf50; font-size: 12px;")
            top_row.addWidget(desktop_badge)

        if pkg.is_duplicate:
            dup_badge = QLabel(" ⚠ DUPLICATE")
            dup_badge.setStyleSheet(
                "color: #f44336; font-size: 12px; font-weight: bold;"
            )
            top_row.addWidget(dup_badge)

        top_row.addStretch()
        layout.addLayout(top_row)

        desc_label = QLabel(pkg.description)
        desc_label.setStyleSheet(
            f"color: {ts.get('_desc', '#c0c0c8')}; font-size: 12px;"
        )
        desc_label.setWordWrap(True)
        desc_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(desc_label)

        cmd_label = QLabel(f"  {pkg.launch_cmd}")
        cmd_color = ts.get("_cmd", "#6db3d4")
        cmd_label.setStyleSheet(f"""
            color: {cmd_color};
            font-family: monospace;
            font-size: 12px;
            background: transparent;
            padding: 2px 0;
        """)
        cmd_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(cmd_label)

        size_label = QLabel(f"  {pkg.size}" if pkg.size else "")
        size_label.setStyleSheet(
            f"color: {ts.get('_size', '#909098')}; font-size: 11px; background: transparent;"
        )
        if pkg.size:
            size_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            layout.addWidget(size_label)

        if pkg.install_date:
            date_label = QLabel(f"  Installed: {pkg.install_date}")
            date_label.setStyleSheet(
                f"color: {ts.get('_size', '#909098')}; font-size: 11px; background: transparent;"
            )
            date_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            layout.addWidget(date_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        launch_btn = QPushButton("▶ Launch")
        launch_btn.setStyleSheet("""
            QPushButton {
                background-color: #4a9eff;
                color: #000000;
                border: none;
                border-radius: 4px;
                padding: 6px 16px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #5ab0ff;
            }
            QPushButton:pressed {
                background-color: #3a8eef;
            }
        """)
        launch_btn.clicked.connect(self.on_launch)
        btn_row.addWidget(launch_btn)

        reinstall_btn = QPushButton("🔄 Reinstall")
        reinstall_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196f3;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 6px 16px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #1e88e5;
            }
            QPushButton:pressed {
                background-color: #1565c0;
            }
        """)
        reinstall_btn.clicked.connect(self.on_reinstall)
        btn_row.addWidget(reinstall_btn)

        uninstall_btn = QPushButton("🗑 Uninstall")
        uninstall_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 6px 16px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #e53935;
            }
            QPushButton:pressed {
                background-color: #c62828;
            }
        """)
        uninstall_btn.clicked.connect(self.on_uninstall)
        btn_row.addWidget(uninstall_btn)

        layout.addLayout(btn_row)

    def on_launch(self):
        parent = self.window()
        if hasattr(parent, "on_launch_package"):
            parent.on_launch_package(self.pkg)

    def on_uninstall(self):
        parent = self.window()
        if hasattr(parent, "on_uninstall_package"):
            parent.on_uninstall_package(self.pkg)

    def on_reinstall(self):
        parent = self.window()
        if hasattr(parent, "on_reinstall_package"):
            parent.on_reinstall_package(self.pkg)


class MainWindow(QMainWindow):
    def _run_gsettings(self, schema, key):
        """Run gsettings or equivalent and return stripped output."""
        try:
            result = subprocess.run(
                ["gsettings", "get", schema, key],
                capture_output=True, text=True, timeout=3
            )
            if result.returncode == 0:
                return result.stdout.strip().strip("'\"")
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return ""

    def _detect_gtk_theme_dark(self):
        """Check if a GTK theme name indicates dark mode."""
        schemes = [
            ("org.gnome.desktop.interface", "gtk-theme"),
            ("org.cinnamon.desktop.interface", "gtk-theme"),
            ("org.mate.interface", "gtk-theme"),
            ("com.solus-project.budgie-panel", "gtk-theme"),
            ("io.elementary.stylesheet", "gtk-theme"),
            ("com.deepin.dde.appearance", "gtk-theme"),
            ("com.ubuntu.user-interface", "theme"),
        ]
        for schema, key in schemes:
            val = self._run_gsettings(schema, key)
            if val and "dark" in val.lower():
                return True
        return False

    def _detect_deepin_dark(self):
        """Detect Deepin DDE dark mode via appearance schema."""
        val = self._run_gsettings("com.deepin.dde.appearance", "color-scheme")
        if val == "dark":
            return True
        return False

    def _detect_lxqt_dark(self):
        """Detect LXQt dark mode from config file."""
        conf = os.path.expanduser("~/.config/lxqt/lxqt.conf")
        if not os.path.exists(conf):
            return False
        try:
            with open(conf) as f:
                for line in f:
                    if "theme" in line.lower() and "dark" in line.lower():
                        return True
        except Exception:
            pass
        return False

    def _detect_system_theme(self):
        """Detect system-wide dark mode across all major desktop environments."""
        # GNOME 42+ color-scheme preference
        val = self._run_gsettings("org.gnome.desktop.interface", "color-scheme")
        if val == "prefer-dark":
            return True

        # GNOME / Cinnamon / MATE / Budgie / Pantheon GTK theme
        if self._detect_gtk_theme_dark():
            return True

        # XFCE via xfconf-query
        try:
            result = subprocess.run(
                ["xfconf-query", "-c", "xsettings", "-p", "/Net/ThemeName"],
                capture_output=True, text=True, timeout=3
            )
            if result.returncode == 0 and "dark" in result.stdout.strip().lower():
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # KDE Plasma
        kdeglobals = os.path.expanduser("~/.config/kdeglobals")
        if os.path.exists(kdeglobals):
            try:
                config = configparser.ConfigParser(interpolation=None)
                config.read(kdeglobals)
                if "General" in config:
                    scheme = config["General"].get("ColorScheme", "")
                    if scheme.lower() in ("breezedark", "breeze-dark", "dark"):
                        return True
                    look = config["General"].get("LookAndFeelPackage", "")
                    if "dark" in look.lower():
                        return True
                if "KDE" in config:
                    contrast = config["KDE"].get("contrast", "")
                    try:
                        if float(contrast) < 0:
                            return True
                    except (ValueError, TypeError):
                        pass
            except Exception:
                pass

        # Deepin DDE color-scheme
        if self._detect_deepin_dark():
            return True

        # LXQt theme config
        if self._detect_lxqt_dark():
            return True

        return False

    def __init__(self):
        super().__init__()
        self.pkg_mgr = PackageManager()
        self.shortcut_mgr = ShortcutManager()
        self.packages = []
        self.toast_queue = []
        self.dark_mode = self._detect_system_theme()
        self._signals = WorkerSignals()
        self._signals.uninstall_done.connect(self._on_uninstall_done_signal)
        self._signals.error.connect(lambda msg: self._show_toast(msg, "error"))

        self.setWindowTitle("Flatpak & Snap Package Manager")
        self.setObjectName("io.github.sametkarakus68.PackageManager")
        self.setMinimumSize(900, 700)
        self.resize(1000, 750)

        self._apply_theme()
        self._build_ui()
        self._refresh_packages()

    def _apply_theme(self):
        if self.dark_mode:
            self._apply_dark_palette()
            self._apply_dark_styles()
        else:
            self._apply_light_palette()
            self._apply_light_styles()
        # Do NOT call self.setStyleSheet() here — it overrides the
        # QApplication-level QMenu stylesheet and breaks the edit context menu.
        # QMenu is styled globally in main.py. Window widget colors use
        # individual setStyleSheet() calls on each widget (cards, buttons, etc.)

    def _apply_dark_palette(self):
        # Don't call self.setPalette() — it overrides QApplication palette
        # and breaks QMenu context menus. Use stylesheets instead (done below).
        # The QApplication palette set in main.py handles QMenu colors.
        pass

    def _apply_light_palette(self):
        # Don't call self.setPalette() — it overrides QApplication palette
        # and breaks QMenu context menus. Use stylesheets instead (done below).
        # The QApplication palette set in main.py handles QMenu colors.
        pass

    def _apply_dark_styles(self):
        self._central_style = "background-color: #1e1e22;"
        self._scroll_style = "QScrollArea { border: none; background: transparent; }"
        self._container_style = "background: transparent;"
        self._tab_style = """
            QTabWidget::pane {
                border: 1px solid #404040;
                border-radius: 4px;
                background: transparent;
            }
            QTabBar::tab {
                background-color: #2d2d2d;
                color: #aaaaaa;
                padding: 8px 16px;
                border: 1px solid #404040;
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: #4a9eff;
                color: #000000;
                font-weight: bold;
            }
            QTabBar::tab:hover:!selected {
                background-color: #3d3d3d;
            }
            QLabel {
                background: transparent;
            }
        """
        self._search_style = """
            QLineEdit {
                background-color: #2d2d2d;
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #4a9eff;
            }
        """
        self._card_normal = """
            #packageCard {
                background-color: #2a2a2e;
                border: 1px solid #3a3a40;
                border-radius: 8px;
                padding: 12px;
                margin: 4px 0;
            }
            #packageCard:hover {
                background-color: #32323a;
            }
        """
        self._card_dup = """
            #packageCard {
                background-color: #3a2525;
                border: 1px solid #6b3a3a;
                border-radius: 8px;
                padding: 12px;
                margin: 4px 0;
            }
            #packageCard:hover {
                background-color: #452e2e;
            }
        """
        self._cb_style = """
            QCheckBox {
                color: #ffffff;
                spacing: 8px;
                min-height: 20px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #666666;
                border-radius: 3px;
                background-color: #3a3a3e;
            }
            QCheckBox::indicator:hover {
                border-color: #4a9eff;
                background-color: #4a4a50;
            }
            QCheckBox::indicator:checked {
                background-color: #4a9eff;
                border-color: #4a9eff;
                image: none;
            }
        """
        self._menu_style = """
            QMenu {
                background-color: #2a2a2e;
                color: #ffffff;
                border: 1px solid #404040;
                border-radius: 4px;
                padding: 4px 0;
            }
            QMenu::item {
                background-color: transparent;
                padding: 6px 30px 6px 20px;
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

    def _apply_light_styles(self):
        self._central_style = "background-color: #f5f5f5;"
        self._scroll_style = "QScrollArea { border: none; background: transparent; }"
        self._container_style = "background: transparent;"
        self._tab_style = """
            QTabWidget::pane {
                border: 1px solid #cccccc;
                border-radius: 4px;
                background: transparent;
            }
            QTabBar::tab {
                background-color: #e0e0e0;
                color: #333333;
                padding: 8px 16px;
                border: 1px solid #cccccc;
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: #4a9eff;
                color: #ffffff;
                font-weight: bold;
            }
            QTabBar::tab:hover:!selected {
                background-color: #d0d0d0;
            }
            QLabel {
                background: transparent;
            }
        """
        self._search_style = """
            QLineEdit {
                background-color: #ffffff;
                color: #1a1a1a;
                border: 1px solid #cccccc;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #4a9eff;
            }
        """
        self._card_normal = """
            #packageCard {
                background-color: #ffffff;
                border: 1px solid #d0d0d0;
                border-radius: 8px;
                padding: 12px;
                margin: 4px 0;
            }
            #packageCard:hover {
                background-color: #f0f0f0;
            }
        """
        self._card_dup = """
            #packageCard {
                background-color: #fff0f0;
                border: 1px solid #d0a0a0;
                border-radius: 8px;
                padding: 12px;
                margin: 4px 0;
            }
            #packageCard:hover {
                background-color: #ffe5e5;
            }
        """
        self._cb_style = """
            QCheckBox {
                color: #1a1a1a;
                spacing: 8px;
                min-height: 20px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #999999;
                border-radius: 3px;
                background-color: #ffffff;
            }
            QCheckBox::indicator:hover {
                border-color: #4a9eff;
                background-color: #e8f0ff;
            }
            QCheckBox::indicator:checked {
                background-color: #4a9eff;
                border-color: #4a9eff;
                image: none;
            }
        """
        self._menu_style = """
            QMenu {
                background-color: #ffffff;
                color: #1a1a1a;
                border: 1px solid #cccccc;
                border-radius: 4px;
                padding: 4px 0;
            }
            QMenu::item {
                background-color: transparent;
                padding: 6px 30px 6px 20px;
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

    def _build_ui(self):
        central = QWidget()
        # Do NOT use setStyleSheet on central — it breaks QMenu inheritance
        # from QApplication. Background color is handled via QPalette.
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        top_bar = QHBoxLayout()
        top_bar.setSpacing(12)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search packages...")
        self.search_input.setStyleSheet(self._search_style)
        self.search_input.textChanged.connect(self._on_search)
        top_bar.addWidget(self.search_input, 1)

        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["Sort: Name", "Sort: Size", "Sort: Date"])
        self.sort_combo.setFixedWidth(150)
        self.sort_combo.setStyleSheet("""
            QComboBox {
                background-color: #2d2d2d;
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 13px;
            }
            QComboBox::drop-down {
                border: none;
                padding-right: 8px;
            }
            QComboBox QAbstractItemView {
                background-color: #2d2d2d;
                color: #ffffff;
                selection-background-color: #4a9eff;
                selection-color: #000000;
            }
        """)
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        top_bar.addWidget(self.sort_combo)

        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.setStyleSheet(self._btn_style("#4a9eff"))
        refresh_btn.clicked.connect(self._refresh_packages)
        top_bar.addWidget(refresh_btn)

        export_btn = QPushButton("📤 Export")
        export_btn.setStyleSheet(self._btn_style("#607d8b"))
        export_btn.clicked.connect(self._on_export)
        top_bar.addWidget(export_btn)

        install_btn = QPushButton("📥 Install from JSON")
        install_btn.setStyleSheet(self._btn_style("#4caf50"))
        install_btn.clicked.connect(self._on_install_from_json)
        top_bar.addWidget(install_btn)

        main_layout.addLayout(top_bar)

        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet(self._tab_style)

        self.all_tab = QWidget()
        self.flatpak_tab = QWidget()
        self.snap_tab = QWidget()
        self.dup_tab = QWidget()

        self.dup_tab_label = "⚠ Duplicates"
        self.tab_widget.addTab(self.all_tab, "All")
        self.tab_widget.addTab(self.flatpak_tab, "Flatpak")
        self.tab_widget.addTab(self.snap_tab, "Snap")
        self.tab_widget.addTab(self.dup_tab, self.dup_tab_label)

        self.all_tab.setLayout(QVBoxLayout())
        self.flatpak_tab.setLayout(QVBoxLayout())
        self.snap_tab.setLayout(QVBoxLayout())
        self.dup_tab.setLayout(QVBoxLayout())

        for tab in [self.all_tab, self.flatpak_tab, self.snap_tab, self.dup_tab]:
            tab.layout().setContentsMargins(0, 0, 0, 0)
            tab.layout().setSpacing(0)

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setStyleSheet(
                "QScrollArea { border: none; background: transparent; }"
            )

            container = QWidget()
            container.setLayout(QVBoxLayout())
            container.layout().setAlignment(Qt.AlignmentFlag.AlignTop)
            container.layout().setContentsMargins(8, 8, 8, 8)
            container.layout().setSpacing(4)
            container.setStyleSheet("background: transparent;")

            scroll.setWidget(container)
            tab.layout().addWidget(scroll)
            setattr(self, f"{tab.objectName() or 'tab'}_container", container)

        self.all_container = self.all_tab.layout().itemAt(0).widget().widget()
        self.flatpak_container = self.flatpak_tab.layout().itemAt(0).widget().widget()
        self.snap_container = self.snap_tab.layout().itemAt(0).widget().widget()
        self.dup_container = self.dup_tab.layout().itemAt(0).widget().widget()

        main_layout.addWidget(self.tab_widget, 1)

        bottom_bar = QHBoxLayout()
        self.bulk_label = QLabel("0 selected")
        self.bulk_label.setStyleSheet("color: #888888; font-size: 12px;")
        bottom_bar.addWidget(self.bulk_label)
        bottom_bar.addStretch()

        self.bulk_reinstall_btn = QPushButton("🔄 Reinstall Selected")
        self.bulk_reinstall_btn.setStyleSheet(self._btn_style("#2196f3"))
        self.bulk_reinstall_btn.clicked.connect(self._on_bulk_reinstall)
        bottom_bar.addWidget(self.bulk_reinstall_btn)

        self.bulk_btn = QPushButton("🗑 Uninstall Selected")
        self.bulk_btn.setStyleSheet(self._btn_style("#f44336"))
        self.bulk_btn.clicked.connect(self._on_bulk_uninstall)
        bottom_bar.addWidget(self.bulk_btn)

        main_layout.addLayout(bottom_bar)

        self._update_widgets_theme()

    def _btn_style(self, color):
        return f"""
            QPushButton {{
                background-color: {color};
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {color}dd;
            }}
            QPushButton:pressed {{
                background-color: {color}bb;
            }}
        """

    def _show_toast(self, message, toast_type="info"):
        toast = Toast(message, toast_type, self)
        self.toast_queue.append(toast)
        toast.show_toast()
        QTimer.singleShot(4000, lambda: self._remove_toast(toast))

    def _remove_toast(self, toast):
        if toast in self.toast_queue:
            self.toast_queue.remove(toast)

    def _update_widgets_theme(self):
        # Do NOT use central.setStyleSheet() — it breaks QMenu inheritance
        # from QApplication. Apply background via QPalette instead.
        central = self.centralWidget()
        if central:
            pal = central.palette()
            pal.setColor(QPalette.ColorRole.Window,
                         QColor("#1e1e22" if self.dark_mode else "#f5f5f5"))
            central.setAutoFillBackground(True)
            central.setPalette(pal)
        self.tab_widget.setStyleSheet(self._tab_style)
        self.search_input.setStyleSheet(self._search_style)
        bg = "#2d2d2d" if self.dark_mode else "#ffffff"
        fg = "#ffffff" if self.dark_mode else "#1a1a1a"
        bd = "#555555" if self.dark_mode else "#cccccc"
        self.sort_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {bg};
                color: {fg};
                border: 1px solid {bd};
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 13px;
            }}
            QComboBox::drop-down {{
                border: none;
                padding-right: 8px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {bg};
                color: {fg};
                selection-background-color: #4a9eff;
                selection-color: #000000;
            }}
        """)
        self._populate_tabs()

    def _refresh_packages(self):
        self._show_toast("Scanning installed packages...", "info")

        def worker():
            flatpaks = self.pkg_mgr.list_flatpaks()
            snaps = self.pkg_mgr.list_snaps()
            all_pkgs = flatpaks + snaps
            self.shortcut_mgr.detect_duplicates(all_pkgs)
            self.packages = all_pkgs

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join()

        self._populate_tabs()
        dup_count = sum(1 for p in self.packages if p.is_duplicate)
        self.tab_widget.setTabText(3, f"⚠ Duplicates ({dup_count})")
        self._show_toast(
            f"Found {len(self.packages)} packages ({dup_count} duplicates)", "success"
        )

    def _sort_packages(self, packages):
        idx = self.sort_combo.currentIndex()
        if idx == 0:
            return sorted(packages, key=lambda p: p.name.lower())
        elif idx == 1:
            return sorted(packages, key=lambda p: p.size_bytes, reverse=True)
        elif idx == 2:
            return sorted(packages, key=lambda p: p.install_date or "", reverse=True)
        return packages

    def _populate_tabs(self):
        for container in [
            self.all_container,
            self.flatpak_container,
            self.snap_container,
            self.dup_container,
        ]:
            while container.layout().count():
                item = container.layout().takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

        ts = {
            "_card_normal": self._card_normal,
            "_card_dup": self._card_dup,
            "_cb_style": self._cb_style,
            "_text": "#ffffff" if self.dark_mode else "#1a1a1a",
            "_subtext": "#888888" if self.dark_mode else "#666666",
            "_desc": "#c0c0c8" if self.dark_mode else "#444444",
            "_size": "#909098" if self.dark_mode else "#777777",
            "_cmd": "#6db3d4" if self.dark_mode else "#0077b6",
        }

        sorted_pkgs = self._sort_packages(self.packages)

        for pkg in sorted_pkgs:
            card = PackageCard(pkg, ts)
            card.checkbox.stateChanged.connect(self._update_selection_count)
            self.all_container.layout().addWidget(card)

            if pkg.pkg_type == "flatpak":
                card2 = PackageCard(pkg, ts)
                card2.checkbox.stateChanged.connect(self._update_selection_count)
                self.flatpak_container.layout().addWidget(card2)
            elif pkg.pkg_type == "snap":
                card3 = PackageCard(pkg, ts)
                card3.checkbox.stateChanged.connect(self._update_selection_count)
                self.snap_container.layout().addWidget(card3)

            if pkg.is_duplicate:
                card4 = PackageCard(pkg, ts)
                card4.checkbox.stateChanged.connect(self._update_selection_count)
                self.dup_container.layout().addWidget(card4)

        for container in [
            self.all_container,
            self.flatpak_container,
            self.snap_container,
            self.dup_container,
        ]:
            container.layout().addStretch()

        self._update_selection_count()

    def _update_selection_count(self):
        count = 0
        for container in [self.all_container]:
            for i in range(container.layout().count()):
                item = container.layout().itemAt(i)
                if item and item.widget() and isinstance(item.widget(), PackageCard):
                    if item.widget().checkbox.isChecked():
                        count += 1
        self.bulk_label.setText(f"{count} selected")

    def _on_sort_changed(self):
        self._populate_tabs()
        self._on_search(self.search_input.text())

    def _on_search(self, text):
        for container in [
            self.all_container,
            self.flatpak_container,
            self.snap_container,
            self.dup_container,
        ]:
            for i in range(container.layout().count()):
                item = container.layout().itemAt(i)
                if item and item.widget() and isinstance(item.widget(), PackageCard):
                    card = item.widget()
                    if not text:
                        card.setVisible(True)
                    else:
                        text_lower = text.lower()
                        match = (
                            text_lower in card.pkg.name.lower()
                            or text_lower in card.pkg.description.lower()
                            or text_lower in card.pkg.launch_cmd.lower()
                            or text_lower in card.pkg.pkg_type.lower()
                            or text_lower in card.pkg.version.lower()
                        )
                        card.setVisible(match)

    def on_launch_package(self, pkg):
        try:
            self.pkg_mgr.launch_package(pkg)
            self._show_toast(f"Launched {pkg.name}", "success")
        except Exception as e:
            self._show_toast(f"Failed to launch {pkg.name}: {e}", "error")

    def on_uninstall_package(self, pkg):
        reply = QMessageBox.question(
            self,
            "Confirm Uninstall",
            f"Uninstall {pkg.name} ({pkg.pkg_type})?\nCommand: {pkg.launch_cmd}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._show_toast(f"Uninstalling {pkg.name}...", "info")

        def worker():
            if pkg.pkg_type == "flatpak":
                success, error = self.pkg_mgr.uninstall_flatpak(pkg.pkg_id)
            else:
                success, error = self.pkg_mgr.uninstall_snap(pkg.pkg_id)

            if success:
                self._signals.uninstall_done.emit(pkg)
            else:
                self._signals.error.emit(f"Failed to uninstall {pkg.name}: {error}")

        threading.Thread(target=worker, daemon=True).start()

    def on_reinstall_package(self, pkg):
        """Reinstall a single package (uninstall + install)."""
        if pkg.pkg_type not in ("flatpak", "snap"):
            self._show_toast(f"Reinstall not supported for {pkg.pkg_type}", "error")
            return

        dialog = ReinstallDialog(pkg, self)
        dialog.show()

    def _on_uninstall_success(self, pkg):
        self._show_toast(f"Uninstalled {pkg.name}", "success")
        self._refresh_packages_async()

    def _refresh_packages_async(self):
        def worker():
            flatpaks = self.pkg_mgr.list_flatpaks()
            snaps = self.pkg_mgr.list_snaps()
            all_pkgs = flatpaks + snaps
            self.shortcut_mgr.detect_duplicates(all_pkgs)
            self.packages = all_pkgs
            QTimer.singleShot(0, self._refresh_ui_from_packages)

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_ui_from_packages(self):
        self._populate_tabs()
        self._update_dup_tab_label()

    def _update_dup_tab_label(self):
        dup_count = sum(1 for p in self.packages if p.is_duplicate)
        self.tab_widget.setTabText(3, f"⚠ Duplicates ({dup_count})")

    def _on_bulk_reinstall(self):
        """Bulk reinstall selected packages."""
        selected = []
        for container in [self.all_container, self.flatpak_container,
                          self.snap_container, self.dup_container]:
            if not container:
                continue
            for i in range(container.layout().count()):
                item = container.layout().itemAt(i)
                if item and item.widget():
                    card = item.widget()
                    if hasattr(card, "checkbox") and card.checkbox.isChecked():
                        if card.pkg not in selected:
                            selected.append(card.pkg)

        if not selected:
            self._show_toast("No packages selected", "info")
            return

        dialog = ReinstallDialog(selected, self)
        dialog.show()

    def _on_bulk_uninstall(self):
        selected = []
        for container in [
            self.all_container,
            self.flatpak_container,
            self.snap_container,
            self.dup_container,
        ]:
            for i in range(container.layout().count()):
                item = container.layout().itemAt(i)
                if item and item.widget() and isinstance(item.widget(), PackageCard):
                    card = item.widget()
                    if card.checkbox.isChecked() and card.pkg not in selected:
                        selected.append(card.pkg)

        if not selected:
            self._show_toast("No packages selected", "warning")
            return

        names = "\n".join(f"  • {p.name} ({p.pkg_type})" for p in selected)
        reply = QMessageBox.question(
            self,
            "Confirm Bulk Uninstall",
            f"Uninstall {len(selected)} packages?\n{names}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._show_toast(f"Uninstalling {len(selected)} packages...", "info")

        def worker():
            success_count = 0
            fail_count = 0
            for pkg in selected:
                if pkg.pkg_type == "flatpak":
                    ok, _ = self.pkg_mgr.uninstall_flatpak(pkg.pkg_id)
                else:
                    ok, _ = self.pkg_mgr.uninstall_snap(pkg.pkg_id)
                if ok:
                    success_count += 1
                else:
                    fail_count += 1

            self._signals.uninstall_done.emit((success_count, fail_count))

        threading.Thread(target=worker, daemon=True).start()

    def _on_uninstall_done_signal(self, data):
        if isinstance(data, tuple):
            success_count, fail_count = data
            self._show_toast(
                f"Bulk uninstall: {success_count} succeeded, {fail_count} failed",
                "success" if fail_count == 0 else "warning",
            )
        self._refresh_packages_async()

    def _on_export(self):
        if not self.packages:
            self._show_toast("No packages to export", "warning")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Package List",
            f"packages_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            "JSON Files (*.json);;Text Files (*.txt)",
        )
        if not path:
            return

        try:
            if path.endswith(".json"):
                data = [
                    {
                        "name": p.name,
                        "id": p.pkg_id,
                        "type": p.pkg_type,
                        "version": p.version,
                        "description": p.description,
                        "launch_cmd": p.launch_cmd,
                        "size": p.size,
                        "is_duplicate": p.is_duplicate,
                    }
                    for p in self.packages
                ]
                with open(path, "w") as f:
                    json.dump(data, f, indent=2)
            else:
                with open(path, "w") as f:
                    f.write(
                        f"Package List - {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                    )
                    f.write("=" * 60 + "\n\n")
                    for p in self.packages:
                        f.write(f"Name: {p.name}\n")
                        f.write(f"  ID: {p.pkg_id}\n")
                        f.write(f"  Type: {p.pkg_type}\n")
                        f.write(f"  Version: {p.version}\n")
                        f.write(f"  Description: {p.description}\n")
                        f.write(f"  Launch: {p.launch_cmd}\n")
                        if p.size:
                            f.write(f"  Size: {p.size}\n")
                        if p.is_duplicate:
                            f.write(f"  ⚠ DUPLICATE\n")
                        f.write("\n")

            self._show_toast(f"Exported to {path}", "success")
        except Exception as e:
            self._show_toast(f"Export failed: {e}", "error")

    def _on_install_from_json(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Install from Backup JSON", "", "JSON Files (*.json)"
        )
        if not path:
            return

        try:
            with open(path, "r") as f:
                data = json.load(f)
            if not isinstance(data, list):
                self._show_toast("Invalid JSON format", "error")
                return
        except Exception as e:
            self._show_toast(f"Failed to read JSON: {e}", "error")
            return

        dialog = InstallDialog(data, self.packages, self.pkg_mgr, self.dark_mode, self)
        result = dialog.exec()
        if result == QDialog.DialogCode.Accepted:
            self._show_toast("Installation finished, refreshing...", "info")
            self._refresh_packages()
