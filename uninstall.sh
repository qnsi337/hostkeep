#!/usr/bin/env bash
# Removes the launcher and icon created by install.sh.
# Your data (~/.config/hostkeep) and ~/.ssh/config are left untouched.
set -euo pipefail
rm -f "$HOME/.local/share/applications/hostkeep.desktop" \
      "$HOME/.local/share/icons/hicolor/scalable/apps/hostkeep.svg" \
      "$HOME/.local/bin/hostkeep"
update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
echo "Hostkeep launcher removed. Data in ~/.config/hostkeep was kept."
