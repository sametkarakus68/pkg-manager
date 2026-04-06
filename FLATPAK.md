# Flatpak Packaging Guide

## Prerequisites

```bash
# Install flatpak-builder and flatpak
sudo apt install flatpak flatpak-builder  # Debian/Ubuntu
sudo dnf install flatpak flatpak-builder   # Fedora
sudo pacman -S flatpak flatpak-builder     # Arch

# Add Flathub remote (if not already added)
flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo

# Install the KDE 6.8 runtime and SDK
flatpak install flathub org.kde.Platform//6.8
flatpak install flathub org.kde.Sdk//6.8
```

## Build Locally

```bash
# Build the flatpak
flatpak-builder --force-clean --install-deps-from=flathub build-dir io.github.sametkarakus68.PackageManager.yml

# Install locally
flatpak-builder --force-clean --install --user build-dir io.github.sametkarakus68.PackageManager.yml

# Run
flatpak run io.github.sametkarakus68.PackageManager
```

## Debug

```bash
# Run with shell access
flatpak run --command=sh io.github.sametkarakus68.PackageManager

# Check logs
flatpak run io.github.sametkarakus68.PackageManager 2>&1 | tee flatpak.log
```

## Export as Single File Bundle

```bash
# Build and export to .flatpak file
flatpak-builder --force-clean --repo=repo build-dir io.github.sametkarakus68.PackageManager.yml
flatpak build-bundle repo pkg-manager.flatpak io.github.sametkarakus68.PackageManager

# Share the .flatpak file - others can install with:
flatpak install --user pkg-manager.flatpak
```

## Submit to Flathub

1. **Fork** https://github.com/flathub/flathub on GitHub

2. **Create a new repo** for your app source (if not already on GitHub):
   ```bash
   # Push your project to GitHub
   git remote add origin https://github.com/samet/pkg-manager.git
   git push -u origin main
   ```

3. **Create a release tarball** or use a git commit URL in the manifest:
   Update `io.github.sametkarakus68.PackageManager.yml` to use a source URL:
   ```yaml
   modules:
     - name: pkg-manager
       sources:
         - type: git
           url: https://github.com/samet/pkg-manager.git
           tag: "1.0.0"
   ```

4. **Submit a PR** to flathub/flathub with your manifest file renamed to `io.github.sametkarakus68.PackageManager.json` (JSON format)

5. **Flathub bots** will auto-build and test your submission

6. **After merge**, your app appears on https://flathub.org

## Convert YAML to JSON (for Flathub submission)

```bash
# Install python-flatpak
pip3 install pyyaml

# Convert
python3 -c "
import yaml, json
with open('io.github.sametkarakus68.PackageManager.yml') as f:
    data = yaml.safe_load(f)
with open('io.github.sametkarakus68.PackageManager.json', 'w') as f:
    json.dump(data, f, indent=2)
"
```

## Important Notes

### Permissions
The manifest requests these permissions:
- `--filesystem=/var/lib/flatpak` - Read installed flatpak list
- `--filesystem=/var/lib/snapd` - Read installed snap list
- `--system-talk-name=org.freedesktop.PolicyKit1` - Polkit authentication for snap operations

### Limitations
- **Snap management inside Flatpak**: Snap CLI (`snap`) may not work inside a Flatpak sandbox since snapd requires root. The app can still **list** installed snaps (reading `/var/lib/snapd`), but **installing/removing snaps** via `pkexec` may not work from within the Flatpak.
- **Flatpak management**: Listing and uninstalling flatpaks works. Installing new flatpaks from within a flatpak requires `--talk-name=org.freedesktop.Flatpak` to delegate to the host.

### Recommended: Host Delegation
For full functionality, consider using `flatpak-spawn --host` to run commands on the host:
```python
# Instead of: subprocess.run(["flatpak", "list", ...])
# Use: subprocess.run(["flatpak-spawn", "--host", "flatpak", "list", ...])
```

## Directory Structure

```
pkg-manager/
├── main.py                          # Entry point
├── core.py                          # Package logic
├── ui.py                            # PyQt6 GUI
├── requirements.txt                 # Python deps
├── io.github.sametkarakus68.PackageManager.yml  # Flatpak manifest
└── flatpak/
    ├── io.github.sametkarakus68.PackageManager.desktop     # Desktop entry
    └── io.github.sametkarakus68.PackageManager.metainfo.xml # AppStream metadata
```
