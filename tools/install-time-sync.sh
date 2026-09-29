#!/usr/bin/env bash
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo 'Run with sudo.'; exit 1; }
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
systemctl cat capture.service >/dev/null
# Store original service settings for review before changing the time-sync policy.
install -d -m 700 /var/lib/quadra-time-sync
for unit in systemd-timesyncd.service chrony.service chronyd.service ntp.service ntpsec.service openntpd.service; do
    if systemctl cat "$unit" >/dev/null 2>&1; then
        if [ ! -e "/var/lib/quadra-time-sync/$unit.before" ]; then
            { systemctl is-enabled "$unit" || true; systemctl is-active "$unit" || true; } > "/var/lib/quadra-time-sync/$unit.before"
        fi
        systemctl disable --now "$unit"
        if systemctl is-active --quiet "$unit"; then
            echo "Cannot disable background time sync: $unit"; exit 1
        fi
    fi
done
install -m 755 "$SCRIPT_DIR/quadra-time-sync.py" /usr/local/sbin/quadra-time-sync
install -d /etc/systemd/system/capture.service.d
DROPIN=/etc/systemd/system/capture.service.d/20-quadra-time-sync.conf
if [ -f "$DROPIN" ] && ! grep -q '# Managed by quadra-time-sync' "$DROPIN"; then
    echo "Refusing to overwrite $DROPIN"; exit 1
fi
cat > "$DROPIN" <<'EOF'
# Managed by quadra-time-sync
[Service]
ExecStartPre=+/usr/local/sbin/quadra-time-sync gate
EOF
systemctl daemon-reload
echo 'Installed. Capture has NOT been restarted and the clock has NOT been changed.'
echo 'On the next Capture start, PC sync gets up to 5 seconds before application initialization.'
echo 'After that window, all helper requests are refused until the next Pi reboot.'
