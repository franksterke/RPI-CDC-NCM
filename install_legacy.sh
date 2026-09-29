#!/usr/bin/env bash
set -euo pipefail

# Migrate Raspberry Pi OS rpi-usb-gadget, then install Capture AP/web services.
# Same environment options as install_ap.sh. Run from a full checkout.
# The existing USB link stays up until the required reboot.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [ "$(id -u)" -eq 0 ]; then
    sudo() { "$@"; }
fi

case "${USB_GADGET_ENABLED:-1}" in
    1|yes|true|on|enabled) ;;
    *) echo "For AP-only setup, use USB_GADGET_ENABLED=0 bash install_ap.sh."; exit 1 ;;
esac
if [ -n "${USB_SHARED_ADDRESS:-}" ]; then
    echo "Replace USB_SHARED_ADDRESS with USB_SUBNET (a private /30 network)."
    exit 1
fi

# Check the complete setup's dependencies before changing legacy USB settings.
source "$SCRIPT_DIR/tools/install-packages.sh"
ensure_capture_packages
sudo python3 "$SCRIPT_DIR/tools/migrate-legacy.py" \
    --board "${USB_BOARD:-rpi-zero}" \
    --network "${USB_NETWORK:-server}" \
    --subnet "${USB_SUBNET:-192.168.7.0/30}" \
    --gadget "${USB_GADGET_MODE:-ncm}"

# NCM is already installed; this avoids the clean installer's legacy-package guard.
USB_GADGET_ENABLED=0 bash "$SCRIPT_DIR/install_ap.sh"
echo "Legacy migration complete. Reboot to switch USB from g_ether to CDC-NCM."
if [ "${USB_NETWORK:-server}" = server ]; then
    python3 -c 'import ipaddress, sys; print("After reboot, USB address: " + str(ipaddress.IPv4Network(sys.argv[1]).network_address + 1))' "${USB_SUBNET:-192.168.7.0/30}"
else
    echo "After reboot, the host must supply DHCP/Internet Sharing; there is no fixed USB address."
fi
