#!/usr/bin/env bash
# Installs a desktop launcher (GNOME/KDE/XFCE app menu) and the icon for Hostkeep.
# Runs from the source checkout; safe to re-run any time (e.g. after moving the repo).
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
chmod +x "$DIR/bin/hostkeep" "$DIR/hostkeep/askpass.py"

ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
APPS_DIR="$HOME/.local/share/applications"
BIN_DIR="$HOME/.local/bin"
mkdir -p "$ICON_DIR" "$APPS_DIR" "$BIN_DIR"

cp "$DIR/hostkeep/icon.svg" "$ICON_DIR/hostkeep.svg"
ln -sf "$DIR/bin/hostkeep" "$BIN_DIR/hostkeep"

cat > "$APPS_DIR/hostkeep.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Hostkeep
GenericName=SSH Manager
Comment=Manage ~/.ssh/config hosts, SSH sessions and tunnels
Exec=$DIR/bin/hostkeep
Icon=hostkeep
Terminal=false
Categories=Network;RemoteAccess;
Keywords=ssh;terminal;server;tunnel;port forwarding;config;
StartupNotify=true
StartupWMClass=hostkeep
DESKTOP

# launcher of the pre-release name, if it was installed
rm -f "$APPS_DIR/ssh-manager.desktop" "$ICON_DIR/ssh-manager.svg"

update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true

echo "Hostkeep installed: app menu entry + '$BIN_DIR/hostkeep'."
