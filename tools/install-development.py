#!/usr/bin/env python3
"""Install on a dedicated Raspberry Pi development target as root.

Uses example USB IDs; not production packaging. Reboot after installation.
Run from the directory containing setup-ncm.py.
"""
import json
from pathlib import Path
import secrets
import shutil
import subprocess


def put(path, contents):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(contents)


config = Path('/etc/usb-cdc-ncm.json')
if not config.exists():
    suffix = secrets.token_hex(4)
    mac = '02:' + ':'.join(suffix[i:i+2] for i in range(0, 8, 2))
    put(config, json.dumps({'serial': 'DEV-' + secrets.token_hex(8),
                           'device_mac': mac + ':01', 'host_mac': mac + ':02'}, indent=2))
c = json.loads(config.read_text())
shutil.copyfile(Path(__file__).with_name('setup-ncm.py'), '/usr/local/sbin/usb-cdc-ncm')
Path('/usr/local/sbin/usb-cdc-ncm').chmod(0o755)
put('/etc/NetworkManager/conf.d/90-usb-cdc-ncm.conf',
    '[keyfile]\nunmanaged-devices=mac:' + c['device_mac'] + '\n')
put('/etc/systemd/network/10-usb-cdc-ncm.network', '''[Match]
MACAddress={mac}

[Link]
RequiredForOnline=no

[Network]
Address=192.168.7.1/30
DHCPServer=yes
LinkLocalAddressing=no
IPv6AcceptRA=no
ConfigureWithoutCarrier=yes

[DHCPServer]
PoolOffset=2
PoolSize=1
EmitDNS=no
EmitRouter=no
DefaultLeaseTimeSec=1h
'''.format(mac=c['device_mac']))
put('/etc/systemd/system/usb-cdc-ncm.service', '''[Unit]
Description=Development USB CDC-NCM gadget
After=systemd-modules-load.service
Before=systemd-networkd.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/usb-cdc-ncm start
ExecStop=/usr/local/sbin/usb-cdc-ncm stop
TimeoutStartSec=45

[Install]
WantedBy=multi-user.target
''')
boot = Path('/boot/firmware/config.txt')
overlay = 'dtoverlay=dwc2,dr_mode=peripheral'
if overlay not in boot.read_text().splitlines():
    backup = boot.with_name('config.txt.before-usb-cdc-ncm')
    if not backup.exists():
        shutil.copyfile(boot, backup)
    with boot.open('a') as f:
        f.write('\n# USB CDC-NCM development gadget\n[all]\n' + overlay + '\n')
put('/etc/modules-load.d/usb-cdc-ncm.conf', 'dwc2\nlibcomposite\n')
subprocess.run(['systemctl', 'daemon-reload'], check=True)
wait_enabled = subprocess.run(['systemctl', 'is-enabled', '--quiet',
                               'systemd-networkd-wait-online']).returncode == 0
subprocess.run(['systemctl', 'enable', 'usb-cdc-ncm', 'systemd-networkd'], check=True)
if not wait_enabled:
    subprocess.run(['systemctl', 'disable', 'systemd-networkd-wait-online'], check=True)
print('Installed. Reboot to enable the USB peripheral controller.')
