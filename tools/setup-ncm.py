#!/usr/bin/env python3
"""Manage this project's single-function development NCM gadget (run as root)."""
import json
import socket
import re
from pathlib import Path
import subprocess
import sys
import time

G = Path('/sys/kernel/config/usb_gadget/quadra-ncm')
C = Path('/etc/usb-cdc-ncm.json')


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
    link = G / 'configs/c.1/ncm.usb0'
    if link.is_symlink():
        link.unlink()
    for name in ('functions/ncm.usb0', 'configs/c.1/strings/0x409',
                 'configs/c.1', 'strings/0x409'):
        p = G / name
        if p.exists():
            p.rmdir()
    G.rmdir()


def start():
    c = json.loads(C.read_text())
    validate(c)
    subprocess.run(['modprobe', 'libcomposite'], check=True)
    subprocess.run(['modprobe', 'usb_f_ncm'], check=True)
    if not Path('/sys/kernel/config/usb_gadget').exists():
        subprocess.run(['mount', '-t', 'configfs', 'none', '/sys/kernel/config'], check=True)
    for _ in range(30):
        udcs = list(Path('/sys/class/udc').iterdir())
        if udcs:
            break
        time.sleep(1)
    if len(udcs) != 1:
        raise RuntimeError('Expected exactly one USB device controller')
    stop()
    try:
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
        write(config / 'strings/0x409/configuration', 'CDC-NCM')
        write(config / 'MaxPower', 250)
        f = G / 'functions/ncm.usb0'
        f.mkdir()
        write(f / 'dev_addr', c['device_mac'])
        write(f / 'host_addr', c['host_mac'])
        (config / 'ncm.usb0').symlink_to(f)
        write(G / 'UDC', udcs[0].name)
        print('NCM bound to', udcs[0].name, flush=True)
    except Exception:
        stop()
        raise


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in ('start', 'stop'):
        sys.exit('Usage: setup-ncm.py start|stop')
    {'start': start, 'stop': stop}[sys.argv[1]]()
