# quadra-003 development deployment

Verified on 2026-09-25 with a Raspberry Pi Zero 2 W, Debian 13.7,
kernel 6.18.50+rpt-rpi-v8, and Windows 11 Pro build 26200.

The original boot configuration used the USB host controller and exposed no UDC.
Enabled `dtoverlay=dwc2,dr_mode=peripheral`, installed the single-function NCM
gadget, and rebooted successfully. The prior boot configuration is saved on the Pi
at `/boot/firmware/config.txt.before-usb-cdc-ncm`.

## Connect

```powershell
ssh frank@192.168.7.1
```

The Pi has `192.168.7.1/30`. Windows receives `192.168.7.2` from
systemd-networkd's DHCP server. No router or DNS options are advertised.
Wi-Fi remains available at its independently assigned address (192.168.0.50
during testing).

## Observed results

- Gadget bound to `3f980000.usb`; controller state `configured`.
- Windows enumerated `UsbNcm Host Device`, PnP status OK, service `UsbNcm`.
- Windows adapter `Ethernet 9` received the expected DHCP address.
- Three pings succeeded with zero loss and latency at or below 1 ms.
- SSH over the USB address returned hostname `quadra-003`.
- Restarting `usb-cdc-ncm` recreated the Linux interface; DHCP, ping, and SSH
  recovered and Windows retained adapter name `Ethernet 9`.
- Boot activation was verified after the deployment reboot.

Physical cable reconnect, Windows reboot, throughput, other Windows builds,
and production descriptor qualification have not been tested.

## Installed files and maintenance

`tools/setup-ncm.py` is installed as `/usr/local/sbin/usb-cdc-ncm`.
`tools/install-development.py` provisions a persistent random development serial
and locally administered MAC pair in `/etc/usb-cdc-ncm.json`. Preserve that file
across reinstalls to preserve device identity.

Other installed files:

- `/etc/systemd/system/usb-cdc-ncm.service`
- `/etc/systemd/network/10-usb-cdc-ncm.network`
- `/etc/NetworkManager/conf.d/90-usb-cdc-ncm.conf`
- `/etc/modules-load.d/usb-cdc-ncm.conf`

The network profile matches the device MAC rather than an interface name.
The USB product string is `<hostname>` (currently `quadra-003`),
read at gadget startup. Windows may still use its driver's generic friendly
name `UsbNcm Host Device` in adapter listings.
The gadget uses the kernel's NCM function and development VID/PID
`1d6b:0104`. These IDs and scripts are a development deployment, not the full
production implementation described in the architecture and milestone plan.
The installer is intended for a dedicated Pi with no pre-existing gadget and
no overlapping network configuration; it writes the listed project-owned files.

On the Pi:

```sh
sudo systemctl status usb-cdc-ncm systemd-networkd
sudo systemctl restart usb-cdc-ncm
networkctl status usb0
journalctl -b -u usb-cdc-ncm -u systemd-networkd
```

To disable the gadget, use `sudo systemctl disable --now usb-cdc-ncm`.
To restore USB host mode, remove the appended development overlay block from
`/boot/firmware/config.txt` and reboot. The backup can be used as a reference;
preserve any subsequent unrelated boot edits.
