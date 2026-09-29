#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# Capture AP + USB Gadget Installer
# ============================================================
#
# Features:
# - USB CDC-NCM gadget managed by systemd-networkd
# - SSH over USB and mDNS hostname access
# - Optional host Internet Connection Sharing over USB gadget mode
# - Wi-Fi access point with SSID Q004
# - Automatic AP fallback when no client Wi-Fi is connected
# - nginx reverse proxy to the Capture app on localhost:8080
#
# Usage:
#
#   ./install_ap.sh
#
# Optional environment overrides:
#
#   AP_ENABLED=0 ./install_ap.sh
#   START_AP_NOW=1 ./install_ap.sh
#   AP_PASSWORD=another-pass ./install_ap.sh
#   USB_GADGET_ENABLED=0 ./install_ap.sh
#   USB_BOARD=generic ./install_ap.sh
#   USB_NETWORK=client ./install_ap.sh
#   USB_GADGET_MODE=ncm-storage ./install_ap.sh
#   USB_SUBNET=192.168.8.0/30 ./install_ap.sh
#
# Requires a full checkout, including tools/install.py and tools/setup-ncm.py.
# USB uses development VID/PID values; production identity is not supported yet.
# Server/client modes are explicit; there is no automatic ICS fallback.
#
# ============================================================

# ------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------

USER_NAME="${SUDO_USER:-$(id -un)}"
DEVICE_HOSTNAME="${DEVICE_HOSTNAME:-quadra-004}"
AP_ENABLED="${AP_ENABLED:-1}"
AP_SSID="${AP_SSID:-Q004}"
AP_PASSWORD="${AP_PASSWORD:-Capture!}"
AP_KEY_MGMT="${AP_KEY_MGMT:-wpa-psk}"
AP_CON_NAME="${AP_CON_NAME:-CaptureAP}"
START_AP_NOW="${START_AP_NOW:-0}"
USB_GADGET_ENABLED="${USB_GADGET_ENABLED:-1}"
USB_BOARD="${USB_BOARD:-rpi-zero}"
USB_NETWORK="${USB_NETWORK:-server}"
USB_GADGET_MODE="${USB_GADGET_MODE:-ncm}"
USB_SUBNET="${USB_SUBNET:-192.168.7.0/30}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
USB_SHARED_HOST=""

export LANG=C.UTF-8
export LC_ALL=C.UTF-8

# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------

is_enabled() {
    case "${1,,}" in
        1|yes|true|on|enabled) return 0 ;;
        *) return 1 ;;
    esac
}

require_root_helper() {
    if ! command -v sudo >/dev/null 2>&1 && [ "$(id -u)" -ne 0 ]; then
        echo "ERROR: sudo is required when not running as root."
        exit 1
    fi
}

validate_ap_settings() {
    if [ "${#AP_SSID}" -lt 1 ] || [ "${#AP_SSID}" -gt 32 ]; then
        echo "ERROR: AP SSID must be 1-32 characters. Current SSID: $AP_SSID"
        exit 1
    fi

    if [ "$AP_KEY_MGMT" = "wpa-psk" ] || [ "$AP_KEY_MGMT" = "sae" ]; then
        if [ "${#AP_PASSWORD}" -lt 8 ] || [ "${#AP_PASSWORD}" -gt 63 ]; then
            echo "ERROR: WPA2/WPA3 passwords must be 8-63 characters."
            echo "Set a longer AP_PASSWORD."
            exit 1
        fi
    fi
}

# Also support root on images without sudo.
if [ "$(id -u)" -eq 0 ]; then
    sudo() { "$@"; }
fi

validate_usb_settings() {
    is_enabled "$USB_GADGET_ENABLED" || return 0
    case "$USB_GADGET_MODE" in
        ncm|ncm-storage) ;;
        *) echo "ERROR: USB_GADGET_MODE must be ncm or ncm-storage."; exit 1 ;;
    esac
    case "$USB_BOARD" in
        rpi-zero|generic) ;;
        *) echo "ERROR: USB_BOARD must be rpi-zero or generic."; exit 1 ;;
    esac
    case "$USB_NETWORK" in
        server|client) ;;
        *) echo "ERROR: USB_NETWORK must be server or client."; exit 1 ;;
    esac
    if [ ! -f "$SCRIPT_DIR/tools/install.py" ] || [ ! -f "$SCRIPT_DIR/tools/setup-ncm.py" ]; then
        echo "ERROR: Run this script from a full RPI-CDC-NCM checkout."
        exit 1
    fi
    if [ -n "${USB_SHARED_ADDRESS:-}" ]; then
        echo "ERROR: Replace USB_SHARED_ADDRESS with USB_SUBNET (a private /30 network)."
        exit 1
    fi
    if command -v rpi-usb-gadget >/dev/null 2>&1; then
        echo "ERROR: Migrate/remove the legacy rpi-usb-gadget installation before continuing."
        echo "Use its uninstall procedure and reboot, then rerun this installer."
        exit 1
    fi
}

# ------------------------------------------------------------
# PRE-FLIGHT
# ------------------------------------------------------------

require_root_helper
if is_enabled "$AP_ENABLED"; then
    validate_ap_settings
fi
validate_usb_settings

echo ""
echo "=================================================="
echo "Installing Capture AP + USB gadget networking"
echo "=================================================="

# ------------------------------------------------------------
# INSTALL REQUIRED PACKAGES
# ------------------------------------------------------------

echo ""
echo "Installing required packages..."

source "$SCRIPT_DIR/tools/install-packages.sh"
ensure_capture_packages

# ------------------------------------------------------------
# INSTALL USB CDC-NCM
# ------------------------------------------------------------

USB_GADGET_AVAILABLE=0

# The runtime reads the hostname for its USB product string at boot.
if command -v hostnamectl >/dev/null 2>&1; then
    echo "Setting device hostname to ${DEVICE_HOSTNAME}..."
    sudo hostnamectl set-hostname "$DEVICE_HOSTNAME"
fi

if is_enabled "$USB_GADGET_ENABLED"; then
    USB_SHARED_HOST="$(python3 -c 'import ipaddress, sys; n = ipaddress.IPv4Network(sys.argv[1]); print(n.network_address + 1)' "$USB_SUBNET")"
    echo "Installing USB CDC-NCM ($USB_NETWORK mode, development USB identity)..."
    sudo python3 "$SCRIPT_DIR/tools/install.py" install \
        --board "$USB_BOARD" --network "$USB_NETWORK" --subnet "$USB_SUBNET" --gadget "$USB_GADGET_MODE" \
        --development
    USB_GADGET_AVAILABLE=1
else
    echo "USB_GADGET_ENABLED=0; skipping USB setup (existing installations are unchanged)."
fi

# ------------------------------------------------------------
# ENABLE NETWORKMANAGER
# ------------------------------------------------------------

echo ""
echo "Enabling NetworkManager..."

sudo systemctl enable --now NetworkManager

# ------------------------------------------------------------
# ALLOW CAPTURE SERVICE USER TO MANAGE WI-FI
# ------------------------------------------------------------

echo ""
echo "Allowing Capture service user to manage Wi-Fi..."

NMCLI_PATH="$(command -v nmcli)"
sudo tee /etc/sudoers.d/capture-nmcli >/dev/null <<EOF
$USER_NAME ALL=(root) NOPASSWD: $NMCLI_PATH
EOF
sudo chmod 440 /etc/sudoers.d/capture-nmcli

# ------------------------------------------------------------
# ENABLE SSH
# ------------------------------------------------------------

echo ""
echo "Enabling SSH..."

sudo systemctl enable ssh
sudo systemctl restart ssh

# ------------------------------------------------------------
# CONFIGURE AVAHI / mDNS
# ------------------------------------------------------------

echo ""
echo "Configuring Avahi for USB, Wi-Fi, and Ethernet..."

AVAHI_CONF="/etc/avahi/avahi-daemon.conf"
sudo cp "$AVAHI_CONF" "$AVAHI_CONF.bak.$(date +%Y%m%d%H%M%S)"

# NCM interface names are assigned at runtime. Let Avahi see the gadget
# when it appears after reboot, along with Wi-Fi and Ethernet.
sudo sed -i -E '/^[[:space:]]*(allow|deny)-interfaces=/d' "$AVAHI_CONF"

sudo systemctl enable avahi-daemon
sudo systemctl restart avahi-daemon

# ------------------------------------------------------------
# CONFIGURE NGINX
# ------------------------------------------------------------

echo ""
echo "Creating nginx reverse proxy config..."

sudo tee /etc/nginx/sites-available/capture >/dev/null <<EOF
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8080;

        proxy_http_version 1.1;

        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

echo ""
echo "Enabling nginx site..."

sudo ln -sf \
    /etc/nginx/sites-available/capture \
    /etc/nginx/sites-enabled/capture

echo ""
echo "Removing default nginx site..."

sudo rm -f /etc/nginx/sites-enabled/default

echo ""
echo "Testing nginx configuration..."

sudo nginx -t

echo ""
echo "Enabling nginx..."

sudo systemctl enable nginx
sudo systemctl restart nginx

# ------------------------------------------------------------
# CONFIGURE WI-FI ACCESS POINT
# ------------------------------------------------------------

if is_enabled "$AP_ENABLED"; then
    echo ""
    echo "Configuring Wi-Fi access point..."

    sudo rfkill unblock wifi >/dev/null 2>&1 || true
    sudo nmcli radio wifi on >/dev/null 2>&1 || true
    sudo nmcli connection delete "$AP_CON_NAME" >/dev/null 2>&1 || true

    sudo nmcli connection add \
        type wifi \
        ifname wlan0 \
        con-name "$AP_CON_NAME" \
        autoconnect no \
        ssid "$AP_SSID"

    sudo nmcli connection modify "$AP_CON_NAME" \
        802-11-wireless.mode ap \
        802-11-wireless.band bg \
        connection.autoconnect no \
        connection.autoconnect-priority 100 \
        ipv4.method shared \
        ipv6.method disabled \
        802-11-wireless-security.key-mgmt "$AP_KEY_MGMT" \
        802-11-wireless-security.psk "$AP_PASSWORD"

    if [ "$AP_KEY_MGMT" = "sae" ]; then
        sudo nmcli connection modify \
            "$AP_CON_NAME" \
            802-11-wireless-security.pmf 3
    fi

    if is_enabled "$START_AP_NOW"; then
        sudo nmcli connection up "$AP_CON_NAME"
    else
        echo "AP profile created. It will start if no client Wi-Fi is connected."
    fi
else
    echo ""
    echo "AP_ENABLED=0; leaving Wi-Fi access point disabled."
    sudo nmcli connection modify "$AP_CON_NAME" connection.autoconnect no >/dev/null 2>&1 || true
fi

# ------------------------------------------------------------
# CONFIGURE WI-FI FALLBACK SERVICE
# ------------------------------------------------------------

if is_enabled "$AP_ENABLED"; then
    echo ""
    echo "Creating Wi-Fi AP fallback service..."

    sudo tee /usr/local/sbin/capture-wifi-fallback.sh >/dev/null <<EOF
#!/usr/bin/env bash
set -euo pipefail

AP_CON_NAME="$AP_CON_NAME"
WAIT_SECONDS="\${WAIT_SECONDS:-35}"

nmcli radio wifi on >/dev/null 2>&1 || true

for _ in \$(seq 1 "\$WAIT_SECONDS"); do
    ACTIVE_WIFI="\$(nmcli -t -f NAME,TYPE,DEVICE connection show --active | awk -F: '\$2 == "802-11-wireless" && \$3 == "wlan0" {print \$1; exit}')"

    if [ -n "\$ACTIVE_WIFI" ] && [ "\$ACTIVE_WIFI" != "\$AP_CON_NAME" ]; then
        exit 0
    fi

    sleep 1
done

ACTIVE_WIFI="\$(nmcli -t -f NAME,TYPE,DEVICE connection show --active | awk -F: '\$2 == "802-11-wireless" && \$3 == "wlan0" {print \$1; exit}')"

if [ -z "\$ACTIVE_WIFI" ]; then
    nmcli connection up "\$AP_CON_NAME" >/dev/null 2>&1 || true
fi
EOF

    sudo chmod 755 /usr/local/sbin/capture-wifi-fallback.sh

    sudo tee /etc/systemd/system/capture-wifi-fallback.service >/dev/null <<EOF
[Unit]
Description=Capture Wi-Fi AP fallback
After=NetworkManager.service
Wants=NetworkManager.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/capture-wifi-fallback.sh

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable capture-wifi-fallback.service
else
    sudo systemctl disable capture-wifi-fallback.service >/dev/null 2>&1 || true
fi

# ------------------------------------------------------------
# INSTALL COMPLETE
# ------------------------------------------------------------

echo ""
echo "=================================================="
echo "Capture AP + USB gadget installation complete"
echo "=================================================="
echo ""
echo "Reboot required:"
echo ""
echo "    sudo reboot"
echo ""
echo "After reboot, connect the USB data cable and use:"
echo ""
    echo "    ssh ${USER_NAME}@${DEVICE_HOSTNAME}.local"
echo ""
echo "USB SSH:"
echo ""
if [ "$USB_GADGET_AVAILABLE" -eq 1 ] && [ "$USB_NETWORK" = server ]; then
    echo "    ssh ${USER_NAME}@${USB_SHARED_HOST}"
elif [ "$USB_GADGET_AVAILABLE" -eq 1 ]; then
    echo "    Use ${DEVICE_HOSTNAME}.local or the address leased by your host."
else
    echo "    USB gadget networking was skipped on this device."
fi
echo ""
echo "Web UI:"
echo ""
    echo "    http://${DEVICE_HOSTNAME}.local"
if [ "$USB_GADGET_AVAILABLE" -eq 1 ] && [ "$USB_NETWORK" = server ]; then
    echo "    http://${USB_SHARED_HOST}"
fi
echo ""

if is_enabled "$AP_ENABLED"; then
    echo "Wi-Fi access point:"
    echo ""
    echo "    SSID:     ${AP_SSID}"
    echo "    Password: ${AP_PASSWORD}"
    echo "    Security: ${AP_KEY_MGMT}"
    echo ""
fi

if [ "$USB_GADGET_AVAILABLE" -eq 1 ]; then
    if [ "$USB_NETWORK" = client ]; then
        echo "Enable DHCP/Internet Sharing on the host for the USB adapter."
        echo "There is no fixed USB address or automatic server fallback in client mode."
        echo "Host-provided DNS requires resolver integration on the Pi (see README.md)."
    else
        echo "USB server mode leases an address to the host."
        echo "For host internet sharing, rerun with USB_NETWORK=client, configure sharing on the host, and reboot."
    fi
else
    echo "USB gadget networking can be retried later with USB_GADGET_ENABLED=1 ./install_ap.sh."
fi
echo ""
