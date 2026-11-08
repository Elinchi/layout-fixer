#!/usr/bin/env bash
# Install layout-fixer for this user: command, systemd user service, launcher entry.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

python -c "import evdev" 2>/dev/null || sudo pacman -S --needed --noconfirm python-evdev
id -nG | grep -qw input || { echo "add yourself to the 'input' group first"; exit 1; }
[ -f "$HERE/data/model.json.gz" ] || python "$HERE/src/train.py"

mkdir -p ~/.local/bin ~/.config/systemd/user ~/.local/share/applications
cat > ~/.local/bin/layout-fixer <<SH
#!/usr/bin/env bash
exec python "$HERE/src/cli.py" "\$@"
SH
chmod +x ~/.local/bin/layout-fixer

cat > ~/.config/systemd/user/layout-fixer.service <<UNIT
[Unit]
Description=Layout fixer: retype words typed in the wrong keyboard layout
PartOf=graphical-session.target
After=graphical-session.target

[Service]
ExecStart=%h/.local/bin/layout-fixer daemon
Restart=on-failure
RestartSec=2

[Install]
WantedBy=graphical-session.target
UNIT

cat > ~/.local/share/applications/layout-fixer.desktop <<DESK
[Desktop Entry]
Type=Application
Name=Розкладка: автовиправлення
GenericName=Layout fixer
Comment=Виправляє слова, набрані не в тій розкладці (ghbdsn → привіт)
Exec=$HOME/.local/bin/layout-fixer settings
Icon=input-keyboard
Terminal=false
Categories=Utility;
Keywords=keyboard;layout;punto;розкладка;клавіатура;
DESK

systemctl --user daemon-reload
systemctl --user enable --now layout-fixer.service
echo "installed. settings: layout-fixer settings (or the launcher entry)"
