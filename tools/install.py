#!/usr/bin/env python3
"""Install CDC-NCM on systemd Linux; standard library only."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import secrets
import subprocess
import shutil

STATE = Path('/var/lib/usb-cdc-ncm/install.json')
IDENTITY = '/etc/usb-cdc-ncm.json'
UNIT = 'usb-cdc-ncm.service'


def run(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True).stdout


def network_config(mac, mode, subnet):
    net = ipaddress.IPv4Network(subnet)
    if net.prefixlen != 30 or not net.is_private or net.is_loopback or net.is_link_local:
        raise ValueError('Choose a private /30 subnet, e.g. 192.168.7.0/30')
    common = f'''[Match]
MACAddress={mac}

[Link]
RequiredForOnline=no

[Network]
LinkLocalAddressing=no
IPv6AcceptRA=no
'''
    if mode == 'client':
        return common + '''DHCP=ipv4

[DHCPv4]
RouteMetric=700
UseDNS=yes
'''
    return common + f'''Address={net.network_address + 1}/30
DHCPServer=yes
ConfigureWithoutCarrier=yes

[DHCPServer]
PoolOffset=2
PoolSize=1
EmitDNS=no
EmitRouter=no
DefaultLeaseTimeSec=1h
'''


def board_config(profile, model, boot, udcs):
    if profile == 'rpi-zero':
        if not model.startswith('Raspberry Pi Zero'):
            raise ValueError('rpi-zero requires a Raspberry Pi Zero family board')
        if boot is None:
            raise ValueError('No Raspberry Pi config.txt found')
        return boot
    if len(udcs) != 1:
        raise ValueError('generic requires exactly one configured UDC; enable peripheral mode using board vendor instructions')
    return None


def enabled(unit):
    return subprocess.run(['systemctl', 'is-enabled', '--quiet', unit]).returncode == 0


def check_unchanged(state):
    for name, entry in state['files'].items():
        p = Path(name)
        if not p.exists() or p.read_text() != entry['installed']:
            raise ValueError(f'Installed file changed externally; reconcile before proceeding: {name}')


def restore(state):
    for name, entry in reversed(list(state['files'].items())):
        p = Path(name)
        if entry['before'] is None:
            p.unlink(missing_ok=True)
        else:
            p.write_text(entry['before'])
            p.chmod(entry['mode'])


def install(args):
    if not args.development:
        raise ValueError('This version uses example VID/PID: explicitly pass --development')
    model_path = Path('/proc/device-tree/model')
    model = model_path.read_text().rstrip('\0') if model_path.exists() else ''
    boot = next((p for p in (Path('/boot/firmware/config.txt'), Path('/boot/config.txt')) if p.exists()), None)
    udcs = list(Path('/sys/class/udc').glob('*'))
    boot = board_config(args.board, model, boot, udcs)
    run('systemctl', 'cat', 'systemd-networkd.service')
    run('modprobe', '--dry-run', 'libcomposite')
    run('modprobe', '--dry-run', 'usb_f_ncm')
    mode = getattr(args, 'gadget', 'ncm')
    if mode not in ('ncm', 'ncm-storage'):
        raise ValueError('Invalid USB gadget mode')
    if mode == 'ncm-storage':
        run('modprobe', '--dry-run', 'usb_f_mass_storage')
        for command in ('mkfs.vfat', 'mcopy'):
            if not shutil.which(command):
                raise ValueError('Install dosfstools and mtools for USB storage; missing ' + command)
    state = json.loads(STATE.read_text()) if STATE.exists() else None
    if state:
        check_unchanged(state)
    gadgets = list(Path('/sys/kernel/config/usb_gadget').glob('*'))
    if any(p.name != 'quadra-ncm' or not state for p in gadgets):
        raise ValueError('Existing USB gadget detected; remove or migrate it before installation')
    if state and state['board'] != args.board:
        raise ValueError('Uninstall before changing board profile')
    identity_path = Path(IDENTITY)
    if identity_path.exists():
        identity = json.loads(identity_path.read_text())
    else:
        suffix = secrets.token_bytes(4)
        prefix = '02:' + ':'.join(f'{b:02x}' for b in suffix)
        identity = dict(serial='DEV-' + secrets.token_hex(8),
                        device_mac=prefix + ':01', host_mac=prefix + ':02')
    # Validate identity with the same code used at gadget startup.
    import importlib.util
    spec = importlib.util.spec_from_file_location('gadget', Path(__file__).with_name('setup-ncm.py'))
    gadget = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gadget)
    gadget.validate(identity)
    files = {
        '/etc/usb-cdc-ncm-gadget.json': json.dumps({'mode': mode}) + '\n',
        '/usr/local/sbin/usb-cdc-ncm': Path(__file__).with_name('setup-ncm.py').read_text(),
        '/etc/systemd/network/10-usb-cdc-ncm.network': network_config(identity['device_mac'], args.network, args.subnet),
        '/etc/NetworkManager/conf.d/90-usb-cdc-ncm.conf':
            '[device-usb-cdc-ncm]\nmatch-device=mac:' + identity['device_mac'] + '\nmanaged=0\n',
        '/etc/modules-load.d/usb-cdc-ncm.conf': ('dwc2\n' if boot else '') + 'libcomposite\n',
        '/etc/systemd/system/' + UNIT: '''[Unit]
Description=USB CDC-NCM gadget
After=systemd-modules-load.service
Before=systemd-networkd.service

[Service]
Type=oneshot
RemainAfterExit=yes
RuntimeDirectory=usb-cdc-ncm
RuntimeDirectoryMode=0700
ExecStart=/usr/local/sbin/usb-cdc-ncm start
ExecStop=/usr/local/sbin/usb-cdc-ncm stop
TimeoutStartSec=45

[Install]
WantedBy=multi-user.target
''',
    }
    if mode == 'ncm-storage':
        files['/usr/local/share/usb-cdc-ncm/START-HERE.html'] = (
            Path(__file__).resolve().parents[1] / 'START-HERE.html').read_text(encoding='utf-8')
    if boot:
        original = boot.read_text()
        overlay = 'dtoverlay=dwc2,dr_mode=peripheral'
        if any(line.strip().startswith('dtoverlay=dwc2') for line in original.splitlines()) and not state:
            raise ValueError('Existing dwc2 overlay: use generic after enabling the UDC, or reconcile boot configuration first')
        files[str(boot)] = original if state else original + '\n# usb-cdc-ncm installer\n[all]\n' + overlay + '\n'
    for name in files:
        if Path(name).exists() and (not state or name not in state['files']) and name != str(boot):
            raise ValueError(f'Refusing to overwrite unmanaged file: {name}')
    if args.network == 'server':
        wanted = ipaddress.IPv4Network(args.subnet)
        for route in json.loads(run('ip', '-j', '-4', 'route', 'show', 'table', 'all')):
            dst = route.get('dst', 'default')
            if dst == 'default':
                continue
            if wanted.overlaps(ipaddress.IPv4Network(dst, strict=False)) and not (state and route.get('dev') in gadget_interfaces(identity)):
                raise ValueError(f'Subnet overlaps an existing route: {dst}')
    print(f'Board: {args.board}; gadget: {mode}; networking: {args.network}; model: {model}')
    print('\n'.join(files))
    if args.dry_run:
        print('Preflight passed; no changes made.')
        return
    if state is None:
        state = {'board': args.board, 'files': {},
                 'networkd_enabled': enabled('systemd-networkd'),
                 'wait_enabled': enabled('systemd-networkd-wait-online')}
    if not identity_path.exists():
        identity_path.write_text(json.dumps(identity, indent=2) + '\n')
        identity_path.chmod(0o600)
    # Keep original uninstall backups and a separate snapshot of this update.
    previous_state = STATE.read_text() if STATE.exists() else None
    snapshot = {'files': {name: dict(before=Path(name).read_text() if Path(name).exists() else None,
                                    mode=Path(name).stat().st_mode & 0o777 if Path(name).exists() else 0o644)
                          for name in files}}
    service_enabled = enabled(UNIT)
    networkd_enabled = enabled('systemd-networkd')
    wait_enabled = enabled('systemd-networkd-wait-online')
    for name, content in files.items():
        p = Path(name)
        if name not in state['files']:
            state['files'][name] = dict(before=p.read_text() if p.exists() else None,
                                       mode=p.stat().st_mode & 0o777 if p.exists() else 0o644)
        state['files'][name]['installed'] = content
    STATE.parent.mkdir(parents=True, exist_ok=True)
    try:
        STATE.write_text(json.dumps(state, indent=2))
        for name, content in files.items():
            p = Path(name)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
            p.chmod(0o755 if name == '/usr/local/sbin/usb-cdc-ncm' else state['files'][name]['mode'])
        run('systemctl', 'daemon-reload')
        run('systemctl', 'enable', UNIT, 'systemd-networkd')
        if not state['wait_enabled']:
            run('systemctl', 'disable', 'systemd-networkd-wait-online')
    except Exception:
        # Undo newly enabled units while their unit files still exist.
        for unit, was_enabled in ((UNIT, service_enabled), ('systemd-networkd', networkd_enabled),
                                  ('systemd-networkd-wait-online', wait_enabled)):
            subprocess.run(['systemctl', 'enable' if was_enabled else 'disable', unit], check=False)
        restore(snapshot)
        if previous_state is None:
            STATE.unlink(missing_ok=True)
        else:
            STATE.write_text(previous_state)
        run('systemctl', 'daemon-reload')
        raise
    print('Installed. Reboot to apply. Identity is preserved in ' + IDENTITY)


def gadget_interfaces(identity):
    return {p.parent.name for p in Path('/sys/class/net').glob('*/address')
            if p.read_text().strip().lower() == identity['device_mac'].lower()}


def uninstall(args):
    if not STATE.exists():
        raise ValueError('No managed installation found')
    state = json.loads(STATE.read_text())
    check_unchanged(state)
    if args.dry_run:
        print('Would restore/remove:\n' + '\n'.join(state['files']))
        return
    run('systemctl', 'disable', '--now', UNIT)
    restore(state)
    run('systemctl', 'daemon-reload')
    if not state['networkd_enabled']:
        run('systemctl', 'disable', 'systemd-networkd')
    if state['wait_enabled']:
        run('systemctl', 'enable', 'systemd-networkd-wait-online')
    STATE.unlink()
    print('Uninstalled. Identity retained for reinstall. Reboot to apply restored boot/network settings.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install', 'uninstall'])
    parser.add_argument('--board', choices=['rpi-zero', 'generic'], default='generic')
    parser.add_argument('--network', choices=['server', 'client'], default='server')
    parser.add_argument('--gadget', choices=['ncm', 'ncm-storage'], default='ncm',
                        help='Optionally expose a read-only USB drive containing START-HERE.html')
    parser.add_argument('--subnet', default='192.168.7.0/30')
    parser.add_argument('--development', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    try:
        if os.name != 'posix' or os.geteuid() != 0:
            raise ValueError('Run as root on the target Linux board')
        (install if args.action == 'install' else uninstall)(args)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
