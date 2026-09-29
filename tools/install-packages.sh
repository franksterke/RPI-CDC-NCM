#!/usr/bin/env bash
# Sourced by the installers; sudo is supplied by the caller (including root).
ensure_capture_packages() {
    local package status
    local -a missing=()
    local -a packages=(avahi-daemon network-manager nginx openssh-server python3 iproute2 kmod)
    if [ "${USB_GADGET_MODE:-ncm}" = ncm-storage ]; then
        packages+=(dosfstools mtools)
    fi
    for package in "${packages[@]}"; do
        status="$(dpkg-query -W -f='${Status}' "$package" 2>/dev/null || true)"
        if [ "$status" != 'install ok installed' ]; then
            missing+=("$package")
        fi
    done
    if [ "${#missing[@]}" -eq 0 ]; then
        echo "All required packages are installed; skipping apt."
        return 0
    fi
    echo "Installing missing packages: ${missing[*]}"
    # Fail on repository errors instead of silently proceeding with stale indexes.
    sudo apt-get -o APT::Update::Error-Mode=any update
    sudo apt-get install -y "${missing[@]}"
}
