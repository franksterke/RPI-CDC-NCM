#!/usr/bin/env python3
"""Manage the development NCM gadget with optional read-only USB storage."""
import json
import socket
import re
from pathlib import Path
import subprocess
import sys
import time
import shutil
import tempfile

G = Path('/sys/kernel/config/usb_gadget/quadra-ncm')
C = Path('/etc/usb-cdc-ncm.json')
OPTIONS = Path('/etc/usb-cdc-ncm-gadget.json')
HTML = Path('/usr/local/share/usb-cdc-ncm/START-HERE.html')
RUNTIME = Path('/run/usb-cdc-ncm')


def prepare_storage():
    """Build a fresh image without touching storage exported by a running gadget."""
    for command in ('mkfs.vfat', 'mcopy'):
        if not shutil.which(command):
            raise ValueError('USB storage requires dosfstools and mtools: missing ' + command)
    if not HTML.is_file():
        raise ValueError('Missing USB landing page: ' + str(HTML))
    RUNTIME.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=RUNTIME, suffix='.img', delete=False) as image:
        image.truncate(32 * 1024 * 1024)
        path = Path(image.name)
    try:
        subprocess.run(['mkfs.vfat', '-F', '16', '-n', 'QUADRA', str(path)], check=True)
        subprocess.run(['mcopy', '-i', str(path), str(HTML), '::START-HERE.html'], check=True)
        return path
    except Exception:
        path.unlink(missing_ok=True)
        raise


def validate(c):
    if not isinstance(c.get('serial'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', c['serial']):
        raise ValueError('Invalid stable serial number')
    for key in ('device_mac', 'host_mac'):
        value = c.get(key, '')
        if not isinstance(value, str) or not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', value):
            raise ValueError('Invalid ' + key)
        if int(value[:2], 16) & 3 != 2:
            raise ValueError(key + ' must be locally administered unicast')
    if c['device_mac'].lower() == c['host_mac'].lower():
        raise ValueError('Device and host MAC must differ')


def write(path, value):
    path.write_text(str(value) + '\n')


def stop():
    if not G.exists():
        return
    write(G / 'UDC', '')
    for function in ('mass_storage.usb0', 'ncm.usb0'):
        link = G / 'configs/c.1' / function
        if link.is_symlink():
            link.unlink()
    for name in ('functions/mass_storage.usb0', 'functions/ncm.usb0', 'configs/c.1/strings/0x409',
                 'configs/c.1', 'strings/0x409'):
        p = G / name
        if p.exists():
            p.rmdir()
    G.rmdir()


def start():
    c = json.loads(C.read_text())
    validate(c)
    mode = json.loads(OPTIONS.read_text()).get('mode', 'ncm') if OPTIONS.exists() else 'ncm'
    if mode not in ('ncm', 'ncm-storage'):
        raise ValueError('Invalid USB gadget mode')
    storage = mode == 'ncm-storage'
    subprocess.run(['modprobe', 'libcomposite'], check=True)
    subprocess.run(['modprobe', 'usb_f_ncm'], check=True)
    if storage:
        subprocess.run(['modprobe', 'usb_f_mass_storage'], check=True)
    if not Path('/sys/kernel/config/usb_gadget').exists():
        subprocess.run(['mount', '-t', 'configfs', 'none', '/sys/kernel/config'], check=True)
    for _ in range(30):
        udcs = list(Path('/sys/class/udc').iterdir())
        if udcs:
            break
        time.sleep(1)
    if len(udcs) != 1:
        raise RuntimeError('Expected exactly one USB device controller')
    image = prepare_storage() if storage else None
    try:
        stop()
    except Exception:
        if image:
            image.unlink(missing_ok=True)
        raise
    try:
        if image:
            image.replace(RUNTIME / 'start-here.img')
        G.mkdir()
        for name, value in {'idVendor': '0x1d6b', 'idProduct': '0x0104',
                            'bcdDevice': '0x0100', 'bcdUSB': '0x0200',
                            'bDeviceClass': '0xEF', 'bDeviceSubClass': '0x02',
                            'bDeviceProtocol': '0x01'}.items():
            write(G / name, value)
        strings = G / 'strings/0x409'
        strings.mkdir()
        for name, value in {'serialnumber': c['serial'], 'manufacturer': 'Development',
                            'product': socket.gethostname()}.items():
            write(strings / name, value)
        config = G / 'configs/c.1'
        config.mkdir()
        (config / 'strings/0x409').mkdir()
        write(config / 'strings/0x409/configuration', 'CDC-NCM + read-only storage' if storage else 'CDC-NCM')
        write(config / 'MaxPower', 250)
        f = G / 'functions/ncm.usb0'
        f.mkdir()
        write(f / 'dev_addr', c['device_mac'])
        write(f / 'host_addr', c['host_mac'])
        (config / 'ncm.usb0').symlink_to(f)
        if storage:
            f = G / 'functions/mass_storage.usb0'
            f.mkdir()
            write(f / 'lun.0/ro', 1)
            write(f / 'lun.0/removable', 1)
            write(f / 'lun.0/cdrom', 0)
            write(f / 'lun.0/file', RUNTIME / 'start-here.img')
            (config / 'mass_storage.usb0').symlink_to(f)
        write(G / 'UDC', udcs[0].name)
        print(mode, 'bound to', udcs[0].name, flush=True)
    except Exception:
        stop()
        raise
    finally:
        if image:
            image.unlink(missing_ok=True)


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in ('start', 'stop'):
        sys.exit('Usage: setup-ncm.py start|stop')
    {'start': start, 'stop': stop}[sys.argv[1]]()
