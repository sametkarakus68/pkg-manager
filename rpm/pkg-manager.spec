Name:           pkg-manager
Version:        1.0.0
Release:        1%{?dist}
Summary:        Flatpak & Snap Package Manager
License:        MIT
URL:            https://github.com/sametkarakus68/PackageManager
Source0:        %{name}-%{version}.tar.gz
Source1:        pkg-manager.desktop
Source2:        icon.png

BuildArch:      noarch

%description
Modern PyQt6 desktop application for managing Flatpak and Snap packages.

Features:
- Browse installed Flatpak and Snap packages
- Launch, install, uninstall, and reinstall packages
- Duplicate detection across package types
- Export package lists to JSON
- Import and install from JSON backup
- Dark/light theme auto-detection (KDE, GNOME, XFCE, etc.)
- Desktop shortcut management

%prep
%setup -q

%install
# Create directories
mkdir -p %{buildroot}/usr/bin
mkdir -p %{buildroot}/usr/share/%{name}
mkdir -p %{buildroot}/usr/share/applications
mkdir -p %{buildroot}/usr/share/icons/hicolor/256x256/apps

# Install Python scripts
install -m 644 core.py %{buildroot}/usr/share/%{name}/core.py
install -m 644 ui.py %{buildroot}/usr/share/%{name}/ui.py
install -m 644 main.py %{buildroot}/usr/share/%{name}/main.py

# Install wrapper script
cat > %{buildroot}/usr/bin/%{name} << 'EOF'
#!/bin/bash
exec python3 /usr/share/pkg-manager/main.py "$@"
EOF
chmod 755 %{buildroot}/usr/bin/%{name}

# Install desktop entry
install -m 644 %{SOURCE1} %{buildroot}/usr/share/applications/%{name}.desktop

# Install icon
install -m 644 %{SOURCE2} %{buildroot}/usr/share/icons/hicolor/256x256/apps/%{name}.png

%files
/usr/bin/%{name}
/usr/share/%{name}/
/usr/share/applications/%{name}.desktop
/usr/share/icons/hicolor/256x256/apps/%{name}.png

%changelog
* Wed Apr 08 2026 samet <samet@localhost> - 1.0.0-1
- Initial release
