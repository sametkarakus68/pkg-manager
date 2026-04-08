#!/usr/bin/env python3
"""Flatpak & Snap Package Manager - Core Logic"""

import os
import subprocess
import configparser
import glob
import re
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

LOG_DIR = os.path.expanduser("~/.local/share/pkg-manager")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "pkg-manager.log")

DESKTOP_DIRS = [
    "/usr/share/applications",
    "/usr/local/share/applications",
    os.path.expanduser("~/.local/share/applications"),
    "/var/lib/flatpak/exports/share/applications",
    "/var/lib/snapd/desktop/applications",
]

logger = logging.getLogger("pkg-manager")
logger.setLevel(logging.DEBUG)
_fh = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(message)s"))
logger.addHandler(_fh)


def _is_flatpak_sandbox():
    return os.path.exists("/.flatpak-info")


def _run_cmd(cmd, **kwargs):
    if _is_flatpak_sandbox():
        cmd = ["flatpak-spawn", "--host"] + cmd
    return subprocess.run(cmd, **kwargs)


@dataclass
class Package:
    pkg_id: str
    name: str
    version: str
    pkg_type: str
    description: str = ""
    size: str = ""
    launch_cmd: str = ""
    has_desktop_entry: bool = False
    is_duplicate: bool = False
    duplicate_group: str = ""
    install_date: str = ""
    size_bytes: int = 0
    origin: str = ""


class PackageManager:
    def _parse_size(self, size_str):
        if not size_str:
            return 0, 0
        size_str = size_str.replace(",", ".").replace("\xa0", " ").strip()
        try:
            parts = size_str.split()
            val = float(parts[0])
            unit = parts[1].lower() if len(parts) > 1 else "mo"
            if unit in ("go", "gb"):
                return int(val * 1024 * 1024 * 1024), val
            elif unit in ("to", "tb"):
                return int(val * 1024 * 1024 * 1024 * 1024), val
            elif unit in ("mo", "mb"):
                return int(val * 1024 * 1024), val
            elif unit in ("ko", "kb"):
                return int(val * 1024), val
            else:
                return int(val), val
        except (ValueError, IndexError):
            return 0, 0

    def _get_flatpak_install_date(self, app_id):
        path = f"/var/lib/flatpak/app/{app_id}"
        try:
            mtime = os.path.getmtime(path)
            return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
        except OSError:
            return ""

    def _get_snap_install_date(self, snap_name):
        pattern = f"/var/lib/snapd/snaps/{snap_name}_*.snap"
        snaps = glob.glob(pattern)
        if snaps:
            try:
                mtime = os.path.getmtime(max(snaps, key=os.path.getmtime))
                return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
            except OSError:
                pass
        return ""

    def list_flatpaks(self):
        try:
            result = _run_cmd(
                [
                    "flatpak",
                    "list",
                    "--app",
                    "--columns=application,name,version,description,size,origin",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            return []

        packages = []
        lines = result.stdout.strip().splitlines()
        if not lines:
            return []
        for line in lines:
            parts = line.split("\t")
            if len(parts) < 6:
                continue
            pkg_id, name, version, desc, size, origin = (
                parts[0],
                parts[1],
                parts[2],
                parts[3],
                parts[4],
                parts[5],
            )
            size_str = size.strip()
            size_bytes, _ = self._parse_size(size_str)
            packages.append(
                Package(
                    pkg_id=pkg_id,
                    name=name,
                    version=version,
                    pkg_type="flatpak",
                    description=desc.strip()
                    if desc.strip()
                    else "No description available",
                    size=size_str,
                    launch_cmd=f"flatpak run {pkg_id}",
                    has_desktop_entry=self._flatpak_has_desktop(pkg_id) or self._user_shortcut_exists(pkg_id),
                    install_date=self._get_flatpak_install_date(pkg_id),
                    size_bytes=size_bytes,
                    origin=origin.strip(),
                )
            )
        return packages

    def _get_snap_size(self, snap_name):
        pattern = f"/var/lib/snapd/snaps/{snap_name}_*.snap"
        snaps = glob.glob(pattern)
        if snaps:
            latest = max(snaps, key=os.path.getmtime)
            try:
                size_bytes = os.path.getsize(latest)
                if size_bytes > 1024 * 1024 * 1024:
                    size_str = f"{size_bytes / (1024**3):.1f} Go"
                elif size_bytes > 1024 * 1024:
                    size_str = f"{size_bytes / (1024**2):.1f} Mo"
                else:
                    size_str = f"{size_bytes / 1024:.1f} Ko"
                return size_str, size_bytes
            except OSError:
                pass
        return "", 0

    def _get_snap_description(self, snap_name):
        try:
            result = _run_cmd(
                ["snap", "info", snap_name],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.splitlines():
                if line.startswith("summary:"):
                    desc = line[len("summary:") :].strip()
                    if desc:
                        return desc
        except (
            subprocess.CalledProcessError,
            FileNotFoundError,
            subprocess.TimeoutExpired,
        ):
            pass
        return "Snap package"

    def list_snaps(self):
        try:
            result = _run_cmd(
                ["snap", "list"],
                capture_output=True,
                text=True,
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            return []

        packages = []
        lines = result.stdout.strip().splitlines()
        if len(lines) < 2:
            return []

        for line in lines[1:]:
            parts = line.split()
            if len(parts) < 3:
                continue
            name, version = parts[0], parts[1]
            if name == "core":
                continue
            has_desktop = self._snap_has_desktop(name) or self._user_shortcut_exists(name)
            if not has_desktop:
                continue
            size_str, size_bytes = self._get_snap_size(name)
            description = self._get_snap_description(name)
            packages.append(
                Package(
                    pkg_id=name,
                    name=name,
                    version=version,
                    pkg_type="snap",
                    description=description,
                    size=size_str,
                    launch_cmd=f"snap run {name}",
                    has_desktop_entry=has_desktop,
                    install_date=self._get_snap_install_date(name),
                    size_bytes=size_bytes,
                )
            )
        return packages

    def uninstall_flatpak(self, pkg_id, delete_data=False):
        cmd = ["flatpak", "uninstall", "-y", "--noninteractive", pkg_id]
        if delete_data:
            cmd.insert(3, "--delete-data")
        logger.info(f"[FLATPAK] Uninstall {pkg_id} (delete_data={delete_data})")
        result = _run_cmd(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            logger.info(f"[FLATPAK] {pkg_id} uninstalled successfully")
            # Remove any user-created shortcut to avoid orphans
            self._remove_user_shortcut_by_id(pkg_id)
        else:
            logger.error(f"[FLATPAK] {pkg_id} uninstall failed: {result.stderr.strip()}")
        return (
            result.returncode == 0,
            result.stderr.strip() if result.returncode != 0 else "",
        )

    def uninstall_snap(self, name):
        logger.info(f"[SNAP] Uninstall {name}")
        result = _run_cmd(
            ["pkexec", "snap", "remove", name],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            logger.info(f"[SNAP] {name} uninstalled successfully")
            # Remove any user-created shortcut to avoid orphans
            self._remove_user_shortcut_by_id(name)
        else:
            logger.error(f"[SNAP] {name} uninstall failed: {result.stderr.strip()}")
        return (
            result.returncode == 0,
            result.stderr.strip() if result.returncode != 0 else "",
        )

    def launch_package(self, pkg):
        """Launch a package. Uses flatpak-spawn --host when inside sandbox."""
        cmd = pkg.launch_cmd.split()
        if _is_flatpak_sandbox():
            cmd = ["flatpak-spawn", "--host"] + cmd
        logger.info(f"[LAUNCH] Launching {pkg.name}: {' '.join(cmd)}")
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def install_flatpak(self, pkg_id, remote="flathub"):
        logger.info(f"[FLATPAK] Install {pkg_id} from {remote}")
        result = _run_cmd(
            ["flatpak", "install", "-y", "--noninteractive", remote, pkg_id],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            logger.info(f"[FLATPAK] {pkg_id} installed successfully")
        else:
            logger.error(f"[FLATPAK] {pkg_id} install failed: {result.stderr.strip()}")
        return (
            result.returncode == 0,
            result.stderr.strip() if result.returncode != 0 else "",
        )

    def install_snap(self, name):
        logger.info(f"[SNAP] Install {name}")
        result = _run_cmd(
            ["pkexec", "snap", "install", name],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            logger.info(f"[SNAP] {name} installed successfully")
        else:
            logger.error(f"[SNAP] {name} install failed: {result.stderr.strip()}")
        return (
            result.returncode == 0,
            result.stderr.strip() if result.returncode != 0 else "",
        )

    def reinstall_flatpak(self, pkg_id, remote="flathub"):
        """Uninstall then reinstall a flatpak package. Returns (success, logs)."""
        logs = []
        logger.info(f"[REINSTALL] Starting reinstall of {pkg_id} from remote={remote}")

        logs.append(f"[{pkg_id}] Uninstalling...")
        logger.info(f"[REINSTALL] Uninstalling {pkg_id}")
        ok, err = self.uninstall_flatpak(pkg_id)
        logs.append(f"  OK: {ok} | stderr: {err}" if err else f"  OK: {ok}")
        if not ok:
            logger.error(f"[REINSTALL] Uninstall failed: {err}")
            return False, logs + [f"  ERROR: Uninstall failed: {err}"]
        logs.append(f"[{pkg_id}] Uninstalled successfully")

        logs.append(f"[{pkg_id}] Installing from {remote}...")
        logger.info(f"[REINSTALL] Installing {pkg_id} from {remote}")
        ok, err = self.install_flatpak(pkg_id, remote)
        logs.append(f"  OK: {ok} | stderr: {err}" if err else f"  OK: {ok}")
        if not ok:
            logger.error(f"[REINSTALL] Install failed: {err}")
            return False, logs + [f"  ERROR: Install failed: {err}"]

        logs.append(f"[{pkg_id}] Reinstalled successfully")
        logger.info(f"[REINSTALL] {pkg_id} reinstalled successfully")
        return True, logs

    def reinstall_snap(self, name):
        """Uninstall then reinstall a snap package. Returns (success, logs)."""
        logs = []
        logger.info(f"[REINSTALL] Starting reinstall of snap {name}")

        logs.append(f"[{name}] Uninstalling...")
        logger.info(f"[REINSTALL] Uninstalling {name}")
        ok, err = self.uninstall_snap(name)
        logs.append(f"  OK: {ok} | stderr: {err}" if err else f"  OK: {ok}")
        if not ok:
            logger.error(f"[REINSTALL] Snap uninstall failed: {err}")
            return False, logs + [f"  ERROR: Uninstall failed: {err}"]
        logs.append(f"[{name}] Uninstalled successfully")

        logs.append(f"[{name}] Installing...")
        logger.info(f"[REINSTALL] Installing {name}")
        ok, err = self.install_snap(name)
        logs.append(f"  OK: {ok} | stderr: {err}" if err else f"  OK: {ok}")
        if not ok:
            logger.error(f"[REINSTALL] Snap install failed: {err}")
            return False, logs + [f"  ERROR: Install failed: {err}"]

        logs.append(f"[{name}] Reinstalled successfully")
        logger.info(f"[REINSTALL] {name} reinstalled successfully")
        return True, logs

    def _flatpak_has_desktop(self, app_id):
        """Check if flatpak exports a .desktop entry. Works both inside and outside sandbox."""
        paths = [
            f"/var/lib/flatpak/exports/share/applications/{app_id}.desktop",
            os.path.expanduser(
                f"~/.local/share/flatpak/exports/share/applications/{app_id}.desktop"
            ),
        ]
        if any(os.path.exists(p) for p in paths):
            return True
        # Inside flatpak sandbox: check host via flatpak-spawn
        if _is_flatpak_sandbox():
            result = _run_cmd(
                ["flatpak", "info", "--show-location", app_id],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                # flatpak exists, it should have a desktop export
                return True
        return False

    def _snap_has_desktop(self, snap_name):
        pattern = f"/var/lib/snapd/desktop/applications/{snap_name}_*.desktop"
        return len(glob.glob(pattern)) > 0

    def has_valid_launcher_shortcut(self, pkg):
        """Check if a valid launcher shortcut exists by scanning all desktop files.
        Works across all DEs (KDE, GNOME, Cinnamon, XFCE, etc.).

        For flatpak: looks for 'flatpak' + 'run' + pkg_id in the Exec line
          (ignores extra args like --branch=stable --arch=x86_64 --command=xxx).
        For snap: looks for '/snap/bin/<name>' or 'snap run <name>'.
        """
        all_dirs = DESKTOP_DIRS
        for d in all_dirs:
            if not os.path.isdir(d):
                continue
            for f in glob.glob(os.path.join(d, "*.desktop")):
                config = configparser.ConfigParser(interpolation=None)
                try:
                    config.read(f)
                    if "Desktop Entry" not in config:
                        continue
                    entry = config["Desktop Entry"]
                    if entry.get("Type") != "Application":
                        continue
                    if entry.get("NoDisplay", "false").lower() == "true":
                        continue
                    if entry.get("Hidden", "false").lower() == "true":
                        continue
                    exec_line = entry.get("Exec", "")
                except Exception:
                    continue

                if pkg.pkg_type == "flatpak":
                    parts = exec_line.split()
                    has_flatpak_cmd = any("flatpak" in p for p in parts)
                    has_run = "run" in parts
                    has_pkg_id = pkg.pkg_id in exec_line
                    if has_flatpak_cmd and has_run and has_pkg_id:
                        logger.debug(f"[SHORTCUT] Valid flatpak shortcut: {f}")
                        return True
                elif pkg.pkg_type == "snap":
                    snap_bin = f"/snap/bin/{pkg.pkg_id}"
                    snap_run = f"snap run {pkg.pkg_id}"
                    if snap_bin in exec_line or snap_run in exec_line:
                        logger.debug(f"[SHORTCUT] Valid snap shortcut: {f}")
                        return True
        return False

    def ensure_launcher_shortcut(self, pkg):
        """Create a clean user .desktop shortcut in ~/.local/share/applications/.
        Always creates/overwrites to ensure a working shortcut regardless of
        DE-specific issues with flatpak/snap exported .desktop files.
        """
        logger.info(f"[SHORTCUT] Ensuring launcher for {pkg.pkg_id} ({pkg.pkg_type})")
        ok, msg = self._create_user_desktop_entry(pkg)
        if ok:
            logger.info(f"[SHORTCUT] Launcher ensured for {pkg.pkg_id}: {msg}")
        else:
            logger.warning(f"[SHORTCUT] Failed to create launcher for {pkg.pkg_id}: {msg}")
        return ok, msg

    # ── Shortcut helpers (merged from ShortcutManager) ──

    _USER_DIR = os.path.expanduser("~/.local/share/applications")

    def _parse_desktop_file(self, path):
        config = configparser.ConfigParser(interpolation=None)
        try:
            config.read(path)
            if "Desktop Entry" not in config:
                return None
            entry = config["Desktop Entry"]
            if entry.get("Type") != "Application":
                return None
            if entry.get("NoDisplay", "false").lower() == "true":
                return None
            if entry.get("Hidden", "false").lower() == "true":
                return None
            return {
                "path": path,
                "name": entry.get("Name", ""),
                "exec": entry.get("Exec", ""),
                "icon": entry.get("Icon", ""),
                "comment": entry.get("Comment", ""),
            }
        except Exception:
            return None

    def _normalize_exec(self, exec_line):
        parts = exec_line.strip().split()
        skip_codes = {"%f","%F","%u","%U","%i","%c","%k","%d","%D","%n","%N","%v","%m"}
        return " ".join(p for p in parts if p not in skip_codes and not p.startswith("%"))

    def _find_hidden_shortcut(self, pkg):
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", pkg.pkg_id)
        filepath = os.path.join(self._USER_DIR, f"{safe_name}.desktop")
        if not os.path.exists(filepath):
            return None
        config = configparser.ConfigParser(interpolation=None)
        try:
            config.read(filepath)
            if "Desktop Entry" in config and config["Desktop Entry"].get("Hidden", "false").lower() == "true":
                return filepath
        except Exception:
            pass
        return None

    def _unhide_shortcut(self, filepath):
        config = configparser.ConfigParser(interpolation=None)
        try:
            config.read(filepath)
            if "Desktop Entry" in config:
                config["Desktop Entry"].pop("Hidden", None)
                with open(filepath, "w") as f:
                    config.write(f)
                return True, ""
        except Exception as e:
            return False, str(e)
        return False, "Not a valid desktop file"

    def _read_app_desktop_field(self, pkg, field, default=None):
        if pkg.pkg_type == "flatpak":
            paths = [
                f"/var/lib/flatpak/exports/share/applications/{pkg.pkg_id}.desktop",
                os.path.expanduser(f"~/.local/share/flatpak/exports/share/applications/{pkg.pkg_id}.desktop"),
            ]
        elif pkg.pkg_type == "snap":
            paths = glob.glob(f"/var/lib/snapd/desktop/applications/{pkg.pkg_id}_*.desktop")
        else:
            paths = []
        for path in paths:
            if not os.path.exists(path):
                continue
            config = configparser.ConfigParser(interpolation=None)
            try:
                config.read(path)
                if "Desktop Entry" in config:
                    val = config["Desktop Entry"].get(field)
                    if val:
                        return val
            except Exception:
                continue
        return default

    def _create_user_desktop_entry(self, pkg, icon=None):
        if not os.path.exists(self._USER_DIR):
            os.makedirs(self._USER_DIR, exist_ok=True)

        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", pkg.pkg_id)
        filepath = os.path.join(self._USER_DIR, f"{safe_name}.desktop")

        # Unhide if DE hid it
        hidden = self._find_hidden_shortcut(pkg)
        if hidden:
            ok, err = self._unhide_shortcut(hidden)
            if ok:
                return True, "Shortcut unhidden"
            return False, f"Failed to unhide: {err}"

        # Skip if valid user shortcut already exists
        if os.path.exists(filepath):
            entry = self._parse_desktop_file(filepath)
            if entry and self._normalize_exec(entry["exec"]) == self._normalize_exec(pkg.launch_cmd):
                return False, "User shortcut already exists"

        app_name = self._read_app_desktop_field(pkg, "Name", pkg.name)
        app_icon = self._read_app_desktop_field(pkg, "Icon", pkg.pkg_id if icon is None else icon)
        app_categories = self._read_app_desktop_field(pkg, "Categories", "Utility;")

        content = f"""[Desktop Entry]
Type=Application
Name={app_name}
Comment={pkg.description}
Exec={pkg.launch_cmd}
Icon={app_icon}
Terminal=false
Categories={app_categories}
"""
        try:
            with open(filepath, "w") as f:
                f.write(content)
            os.chmod(filepath, 0o755)
            logger.info(f"[SHORTCUT] Created: {filepath}")
            return True, ""
        except Exception as e:
            return False, str(e)

    def _user_shortcut_exists(self, pkg_id):
        """Check if a user-created shortcut exists for this package."""
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", pkg_id)
        filepath = os.path.join(self._USER_DIR, f"{safe_name}.desktop")
        exists = os.path.exists(filepath)
        # Also check if it was hidden by DE
        if not exists:
            hidden_path = self._find_hidden_shortcut_by_id(pkg_id)
            return hidden_path is not None
        return exists

    def _find_hidden_shortcut_by_id(self, pkg_id):
        """Find a Hidden=true shortcut for a package by ID."""
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", pkg_id)
        filepath = os.path.join(self._USER_DIR, f"{safe_name}.desktop")
        if not os.path.exists(filepath):
            return None
        config = configparser.ConfigParser(interpolation=None)
        try:
            config.read(filepath)
            if "Desktop Entry" in config and config["Desktop Entry"].get("Hidden", "false").lower() == "true":
                return filepath
        except Exception:
            pass
        return None

    def _remove_user_shortcut_by_id(self, pkg_id):
        """Remove user shortcut for a package (called on uninstall to prevent orphans)."""
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", pkg_id)
        filepath = os.path.join(self._USER_DIR, f"{safe_name}.desktop")
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                logger.info(f"[SHORTCUT] Removed orphan shortcut: {filepath}")
            except Exception as e:
                logger.warning(f"[SHORTCUT] Failed to remove {filepath}: {e}")

    def _has_launcher_entry(self, pkg):
        """Check if a valid launcher entry exists (flatpak/snap export OR user shortcut)."""
        return self.has_valid_launcher_shortcut(pkg)


class ShortcutManager:
    """Kept for backward compatibility. Only used for duplicate detection."""
    DESKTOP_DIRS = DESKTOP_DIRS
    USER_DIR = os.path.expanduser("~/.local/share/applications")

    def _extract_canonical_name(self, pkg):
        """Extract a canonical name for duplicate detection.
        Tries multiple strategies to match the same app across flatpak/snap.
        """
        if pkg.pkg_type == "flatpak":
            parts = pkg.pkg_id.split(".")
            last = parts[-1].lower() if parts else ""

            # Known app mappings (flatpak last-segment → canonical)
            common_names = {
                "firefox": "firefox",
                "vlc": "vlc",
                "discord": "discord",
                "spotify": "spotify",
                "code": "vscode",
                "telegram": "telegram",
                "signal": "signal",
                "steam": "steam",
                "obs": "obs",
                "gimp": "gimp",
                "inkscape": "inkscape",
                "audacity": "audacity",
                "blender": "blender",
                "thunderbird": "thunderbird",
                "libreoffice": "libreoffice",
                "chromium": "chromium",
                "brave": "brave",
                "telegramdesktop": "telegram",
                "4ktube": "4ktube",
                "youtube-downloader-4ktube": "4ktube",
                "youtube-downloader": "4ktube",
                "bottles": "bottles",
                "lutris": "lutris",
                "heroic": "heroic",
            }
            if last in common_names:
                return common_names[last]
            # Check partial matches
            for key, canon in common_names.items():
                if key in last or last in key:
                    return canon
            # Fallback: try to extract a simple name
            # Remove common prefixes like "youtube-downloader-"
            clean = re.sub(r"^(youtube-downloader-|video-downloader-|music-downloader-)", "", last)
            if clean and clean != last:
                return clean
            return last
        else:
            # Snap: pkg_id is the snap name
            snap = pkg.pkg_id.lower().strip()
            common_names = {
                "firefox": "firefox",
                "vlc": "vlc",
                "discord": "discord",
                "spotify": "spotify",
                "code": "vscode",
                "telegram": "telegram",
                "signal": "signal",
                "steam": "steam",
                "obs": "obs",
                "gimp": "gimp",
                "inkscape": "inkscape",
                "audacity": "audacity",
                "blender": "blender",
                "thunderbird": "thunderbird",
                "libreoffice": "libreoffice",
                "chromium": "chromium",
                "brave": "brave",
                "telegram-desktop": "telegram",
                "telegramdesktop": "telegram",
                "4ktube": "4ktube",
                "4k-video-downloader": "4ktube",
                "youtube-dl": "youtube-dl",
                "bottles": "bottles",
                "lutris": "lutris",
                "heroic": "heroic",
            }
            if snap in common_names:
                return common_names[snap]
            for key, canon in common_names.items():
                if key in snap or snap in key:
                    return canon
            return snap

    def detect_duplicates(self, packages):
        flatpaks = [p for p in packages if p.pkg_type == "flatpak"]
        snaps = [p for p in packages if p.pkg_type == "snap"]

        if not flatpaks or not snaps:
            return {}

        fp_names = {self._extract_canonical_name(p): p for p in flatpaks}
        snap_names = {self._extract_canonical_name(p): p for p in snaps}

        common = set(fp_names.keys()) & set(snap_names.keys())
        groups = {}
        for name in common:
            fp = fp_names[name]
            sp = snap_names[name]
            group_id = f"dup_{name}"
            fp.is_duplicate = True
            fp.duplicate_group = group_id
            sp.is_duplicate = True
            sp.duplicate_group = group_id
            groups[group_id] = [fp, sp]

        return groups
