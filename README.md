# USB CDC-NCM installer

Install a single-function USB network gadget on a systemd Linux board. The board
advertises its hostname as its USB product name and retains its serial and MAC
addresses across reboot and reinstall. No Python packages are required.

This repository configures USB networking. Website hosting, browser-based clock
synchronization, firewall policy, and laptop internet sharing are application or
host responsibilities.

## Current support

| Device/host | Status |
| --- | --- |
| Raspberry Pi Zero family | Explicit `rpi-zero` boot profile; Zero 2 W development deployment tested |
| Other Pi / Radxa / embedded Linux | `generic` requires an already enabled, sole USB device controller; board-specific boot setup not automated |
| Windows 11 build 26200 | NCM driver, DHCP, ping, SSH, boot and gadget restart tested with the development deployment |
| Linux and macOS hosts | Qualification pending |

See [hardware validation](docs/quadra-003-validation.md). The reusable installer
is newer than that deployment; its full install/uninstall lifecycle has not yet
been hardware-qualified. The original development installer is retained only as
a record of that deployment; use `tools/install.py` for new installations.

## Requirements

- USB peripheral-capable controller and a data cable connected to its device port.
- Python 3.9+, systemd, systemd-networkd, iproute2, kmod, ConfigFS and kernel NCM support.
- A dedicated target without another USB gadget or competing USB network profile.
- For `rpi-zero`, a Zero family board using `/boot/firmware/config.txt` or `/boot/config.txt`.
- For `generic`, board vendor configuration must expose exactly one entry under `/sys/class/udc`.

The installer rejects files it does not own, existing gadgets, invalid identities,
and overlapping active IPv4 routes. It does not automatically migrate the earlier
development installation. Review existing NetworkManager/networkd/netplan profiles
before installing: arbitrary distribution network rules cannot all be inferred.

## Install on the target board

Copy this repository to the board. Preview first:

```sh
sudo python3 tools/install.py install --board rpi-zero --development --dry-run
sudo python3 tools/install.py install --board rpi-zero --development
sudo reboot
```

Use `--board generic` on a board with a configured UDC. No vendor-specific Radxa
overlay is guessed. Installation enables boot services but does not restart the
network or reboot automatically. `--development` is required because the current
runtime uses example USB IDs `1d6b:0104`; production VID/PID configuration is pending.

### Networking

The default `--network server` gives the board `192.168.7.1/30` and leases
`192.168.7.2` to the laptop. It advertises no default router or DNS. Set
`--subnet 192.168.8.0/30` for another device; allocate distinct, non-overlapping
subnets for devices connected to the same laptop. Addresses are not automatically
coordinated across boards.

`--network client` requests an IPv4 lease, gateway and DNS from the laptop.
The laptop must separately supply DHCP/internet sharing. DNS received by networkd
also requires the target distribution's resolver integration (for example
systemd-resolved); this installer does not replace `/etc/resolv.conf`.
The USB route metric is 700, so an existing Wi-Fi route with metric 600 stays
preferred. DHCP does not synchronize the board's clock.

### Capture AP and web proxy setup

For the application setup (SSH, mDNS, nginx on port 80 forwarding to port 8080,
and the optional Wi-Fi fallback AP), run from a full checkout on the board:

```sh
bash install_ap.sh
# Host supplies DHCP/internet sharing instead of the device:
USB_NETWORK=client bash install_ap.sh
```

The wrapper calls `tools/install.py` with development USB IDs. It defaults to
`USB_BOARD=rpi-zero`, `USB_NETWORK=server`, and `USB_SUBNET=192.168.7.0/30`
(device address `192.168.7.1`). Set `USB_BOARD=generic` for an already configured
UDC. NetworkManager manages Wi-Fi; systemd-networkd owns USB. There is no
automatic switch between server and client modes. Reboot after installation.

For an existing `rpi-usb-gadget` setup, use the separate migration installer:

```sh
bash install_legacy.sh
sudo reboot
```

It accepts the same board/network/AP options, saves root-only backups under
`/var/lib/usb-cdc-ncm/legacy-backup-*`, masks the old ICS watcher, disables
autoconnect on its two USB profiles, and removes its `g_ether` autoload and
generated DHCP snippet. It leaves the active USB link up until reboot and does
not alter Wi-Fi profiles during migration. For `rpi-zero`, it replaces the known
peripheral overlay with the NCM installer's owned boot configuration; `generic`
retains the existing board configuration. Custom legacy configurations are
rejected instead of guessed. If NCM installation fails, the migration restores
the backed-up legacy settings. Failures in the later AP/web setup leave NCM
installed; rerun the legacy entry point to finish that setup.

The old package remains installed but inactive; do not run `rpi-usb-gadget on`
after migration. The clean `install_ap.sh` still rejects that package. The former
`USB_SHARED_ADDRESS` override is replaced by `USB_SUBNET`, a private /30 network.
`USB_GADGET_ENABLED=0` skips USB setup without uninstalling an existing gadget.
`AP_ENABLED=0` skips AP setup. The default hostname and SSID are `quadra-004` and
`Q004`; override them with `DEVICE_HOSTNAME` and `AP_SSID` as needed.

### Update and uninstall

Rerun the installer with the desired profile to update an owned installation,
then reboot. Identity stays in `/etc/usb-cdc-ncm.json`.

```sh
sudo python3 tools/install.py uninstall --dry-run
sudo python3 tools/install.py uninstall
sudo reboot
```

Uninstall restores prior contents of owned files and preserves identity. It
refuses to overwrite files edited since installation, including boot config;
reconcile those edits first. Networkd is not stopped during uninstall, to avoid
disconnecting unrelated interfaces. Its original enablement is restored at boot.
Backups and installation ownership are recorded in `/var/lib/usb-cdc-ncm/install.json`.

## Diagnostics and tests

```sh
systemctl status usb-cdc-ncm systemd-networkd
journalctl -b -u usb-cdc-ncm -u systemd-networkd
ls /sys/class/udc
ip -brief address
networkctl list
python3 -m unittest discover -s tests -v
```

Windows may call the connection `Ethernet N` despite receiving the hostname in
the USB product descriptor. This installer performs no host-side rename or driver
installation.

Implementation references: [Linux ConfigFS](https://docs.kernel.org/usb/gadget_configfs.html),
[systemd network configuration](https://github.com/systemd/systemd/blob/main/man/systemd.network.xml),
and the installed Raspberry Pi `dtoverlay -h dwc2` documentation.
