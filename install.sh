#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# Package Manager — install.sh
# Auto-detects latest version from GitHub Releases
# Supports: Debian/Ubuntu, Fedora/RHEL, Arch/Manjaro
# ─────────────────────────────────────────────────────────
set -euo pipefail

REPO="sametkarakus68/PackageManager"
API_URL="https://api.github.com/repos/${REPO}/releases/latest"
TMP_DIR=$(mktemp -d)

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()    { echo -e "${BLUE}[✓]${NC} $*"; }
warn()    { echo -e "${YELLOW}[!]${NC} $*"; }
error()   { echo -e "${RED}[✗]${NC} $*"; }
step()    { echo -e "${BLUE}[$1/$3]${NC} $2"; }

cleanup() { rm -rf "${TMP_DIR}"; }
trap cleanup EXIT

# ── Fetch latest release metadata ───────────────────────
fetch_latest_release() {
    local json
    json=$(curl -fSL --silent "${API_URL}" 2>/dev/null || echo "")
    if [[ -z "${json}" ]]; then
        error "Failed to fetch latest release from GitHub."
        error "Check: ${API_URL}"
        exit 1
    fi

    # Extract tag name
    LATEST_TAG=$(echo "${json}" | grep -o '"tag_name": *"[^"]*"' | head -1 | cut -d'"' -f4)
    info "Latest release: ${LATEST_TAG}"

    # Extract asset names and URLs
    # JSON format: "assets": [{"name": "...", "browser_download_url": "..."}, ...]
    ASSET_NAMES=()
    ASSET_URLS=()
    while IFS=$'\t' read -r name url; do
        name=$(echo "${name}" | sed 's/.*"name": *"\([^"]*\)".*/\1/')
        url=$(echo "${url}" | sed 's/.*"browser_download_url": *"\([^"]*\)".*/\1/')
        [[ -n "${name}" && -n "${url}" ]] && {
            ASSET_NAMES+=("${name}")
            ASSET_URLS+=("${url}")
        }
    done < <(echo "${json}" | grep -oP '"name": *"[^"]*\.(deb|rpm|pkg\.tar\.zst)"|"browser_download_url": *"[^"]*"' | paste - -)

    if [[ ${#ASSET_NAMES[@]} -eq 0 ]]; then
        error "No package assets found in release ${LATEST_TAG}."
        exit 1
    fi
}

find_asset() {
    local pattern="$1"
    for i in "${!ASSET_NAMES[@]}"; do
        if [[ "${ASSET_NAMES[$i]}" == *${pattern}* ]]; then
            echo "${ASSET_URLS[$i]}"
            return 0
        fi
    done
    return 1
}

# ── Download helper ─────────────────────────────────────
download() {
    local url="$1" dest="$2"
    if command -v wget &>/dev/null; then
        wget -q --show-progress -O "${dest}" "${url}" 2>&1
    elif command -v curl &>/dev/null; then
        curl -fSL --progress-bar -o "${dest}" "${url}"
    else
        error "Neither wget nor curl found."
        exit 1
    fi
    [[ -f "${dest}" ]] && [[ -s "${dest}" ]]
}

# ── Debian/Ubuntu family ────────────────────────────────
install_debian() {
    step 1 2 "Finding pkg-manager (.deb)..."
    local url
    url=$(find_asset ".deb") || {
        warn "No .deb found in release. Installing dependencies only."
        install_deps_debian
        return
    }
    local deb_name="${url##*/}"
    step 2 2 "Downloading & installing ${deb_name}..."
    if download "${url}" "${TMP_DIR}/${deb_name}"; then
        apt-get install -y -qq "${TMP_DIR}/${deb_name}" 2>&1 | tail -3
        info "pkg-manager installed!"
    else
        warn "Download failed. Installing dependencies only."
        install_deps_debian
    fi
}

install_deps_debian() {
    apt-get update -qq
    apt-get install -y -qq python3 python3-pyqt6 flatpak snapd 2>&1 | tail -3
    info "Dependencies installed."
}

# ── Fedora/RHEL/openSUSE ────────────────────────────────
install_fedora() {
    step 1 2 "Finding pkg-manager (.rpm)..."
    local url
    url=$(find_asset ".noarch.rpm") || {
        warn "No .rpm found in release. Installing dependencies only."
        install_deps_fedora
        return
    }
    local rpm_name="${url##*/}"
    step 2 2 "Downloading & installing ${rpm_name}..."
    if download "${url}" "${TMP_DIR}/${rpm_name}"; then
        dnf install -y "${TMP_DIR}/${rpm_name}" 2>&1 | tail -3
        info "pkg-manager installed!"
    else
        warn "Download failed. Installing dependencies only."
        install_deps_fedora
    fi
}

install_deps_fedora() {
    dnf install -y python3 python3-qt6 flatpak snapd 2>&1 | tail -3
    systemctl enable --now snapd.socket 2>/dev/null || true
    info "Dependencies installed."
}

install_suse() {
    step 1 2 "Finding pkg-manager (.rpm)..."
    local url
    url=$(find_asset ".noarch.rpm") || {
        warn "No .rpm found in release. Installing dependencies only."
        zypper install -y python3 python3-qt6 flatpak snapd 2>&1 | tail -3
        info "Dependencies installed."
        return
    }
    local rpm_name="${url##*/}"
    step 2 2 "Downloading & installing ${rpm_name}..."
    if download "${url}" "${TMP_DIR}/${rpm_name}"; then
        zypper install -y "${TMP_DIR}/${rpm_name}" 2>&1 | tail -3
        info "pkg-manager installed!"
    else
        warn "Download failed. Installing dependencies only."
        zypper install -y python3 python3-qt6 flatpak snapd 2>&1 | tail -3
        info "Dependencies installed."
    fi
}

# ── Arch/Manjaro ────────────────────────────────────────
install_arch() {
    step 1 2 "Finding pkg-manager (.pkg.tar.zst)..."
    local url
    url=$(find_asset ".pkg.tar.zst") || {
        warn "No .pkg.tar.zst found in release. Installing dependencies only."
        pacman -Syu --noconfirm python python-pyqt6 flatpak snapd 2>&1 | tail -3
        systemctl enable --now snapd.socket 2>/dev/null || true
        info "Dependencies installed."
        return
    }
    local pkg_name="${url##*/}"
    step 2 2 "Downloading & installing ${pkg_name}..."
    if download "${url}" "${TMP_DIR}/${pkg_name}"; then
        pacman -U --noconfirm "${TMP_DIR}/${pkg_name}" 2>&1 | tail -3
        info "pkg-manager installed!"
    else
        warn "Download failed. Installing dependencies only."
        pacman -Syu --noconfirm python python-pyqt6 flatpak snapd 2>&1 | tail -3
        systemctl enable --now snapd.socket 2>/dev/null || true
        info "Dependencies installed."
    fi
}

# ── Local file install (any distro) ─────────────────────
install_local() {
    local file="$1"
    if [[ ! -f "${file}" ]]; then
        error "File not found: ${file}"
        exit 1
    fi
    case "${file}" in
        *.deb)
            apt-get install -y -qq "${file}" 2>&1 | tail -3
            ;;
        *.rpm)
            if command -v dnf &>/dev/null; then
                dnf install -y "${file}" 2>&1 | tail -3
            elif command -v zypper &>/dev/null; then
                zypper install -y "${file}" 2>&1 | tail -3
            else
                rpm -i "${file}" 2>&1 || yum install -y "${file}" 2>&1 | tail -3
            fi
            ;;
        *.pkg.tar.zst|*.pkg.tar.xz)
            pacman -U --noconfirm "${file}" 2>&1 | tail -3
            ;;
        *)
            error "Unsupported package format: ${file}"
            exit 1
            ;;
    esac
    info "Package installed!"
}

# ── Detect distro & dispatch ────────────────────────────
detect_and_install() {
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        local distro="${ID}"
        info "Detected: ${PRETTY_NAME:-${distro}}"
        fetch_latest_release
        case "${distro}" in
            ubuntu|debian|linuxmint|kubuntu|pop|zorin|elementary|neon)
                install_debian
                ;;
            fedora|nobara)
                install_fedora
                ;;
            opensuse-*|sles)
                install_suse
                ;;
            arch|manjaro|endeavouros|garuda|cachyos)
                install_arch
                ;;
            *)
                warn "Unsupported distro: ${distro}."
                install_deps_debian
                ;;
        esac
    else
        error "Cannot detect Linux distribution."
        exit 1
    fi
}

show_done() {
    echo ""
    echo -e "${GREEN}═══════════════════════════════════════════${NC}"
    echo -e "  Installation complete!"
    echo -e "  Launch with: ${BLUE}pkg-manager${NC}"
    echo -e "  Or find it in your application menu."
    echo -e "${GREEN}═══════════════════════════════════════════${NC}"
    echo ""
}

# ── Main ────────────────────────────────────────────────
main() {
    if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
        echo "Usage:"
        echo "  sudo bash install.sh              # Auto-detect & install latest from GitHub"
        echo "  sudo bash install.sh ./file.deb   # Install local package file"
        echo "  sudo bash install.sh ./file.rpm"
        echo "  sudo bash install.sh ./file.pkg.tar.zst"
        echo ""
        echo "Options:"
        echo "  --help, -h    Show this help message"
        exit 0
    fi

    if [[ -n "${1:-}" ]]; then
        if [[ $EUID -ne 0 ]]; then
            error "This script requires root privileges."
            error "Run with: sudo bash install.sh ${1}"
            exit 1
        fi
        install_local "$1"
        show_done
        return
    fi

    if [[ $EUID -ne 0 ]]; then
        error "This script requires root privileges."
        error "Run with: sudo bash install.sh"
        exit 1
    fi
    detect_and_install
    show_done
}

main "$@"
