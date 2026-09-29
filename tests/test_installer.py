import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


installer = module('installer', 'install.py')
gadget = module('gadget', 'setup-ncm.py')


class InstallerTests(unittest.TestCase):
    def test_server_has_no_default_route_or_dns(self):
        text = installer.network_config('02:00:00:00:00:01', 'server', '192.168.8.0/30')
        self.assertIn('Address=192.168.8.1/30', text)
        self.assertIn('PoolOffset=2', text)
        self.assertIn('EmitRouter=no', text)
        self.assertIn('EmitDNS=no', text)
        self.assertNotIn('DHCP=ipv4', text)

    def test_client_does_not_run_server(self):
        text = installer.network_config('02:00:00:00:00:01', 'client', '192.168.7.0/30')
        self.assertIn('DHCP=ipv4', text)
        self.assertNotIn('DHCPServer', text)
        self.assertNotIn('\nAddress=', text)

    def test_reject_invalid_subnets(self):
        for subnet in ('192.168.7.1/30', '192.168.7.0/24', '8.8.8.0/30', '127.0.0.0/30', '169.254.0.0/30'):
            with self.subTest(subnet=subnet), self.assertRaises(ValueError):
                installer.network_config('02:00:00:00:00:01', 'server', subnet)

    def test_board_guard(self):
        self.assertEqual(installer.board_config('rpi-zero', 'Raspberry Pi Zero 2 W Rev 1.0', Path('/boot/config.txt'), []), Path('/boot/config.txt'))
        for profile, model, boot, udcs in [('rpi-zero', 'Radxa', Path('/boot/config.txt'), []),
                                           ('rpi-zero', 'Raspberry Pi Zero W', None, []),
                                           ('generic', 'Radxa', None, []),
                                           ('generic', 'Radxa', None, ['a', 'b'])]:
            with self.assertRaises(ValueError):
                installer.board_config(profile, model, boot, udcs)
        self.assertIsNone(installer.board_config('generic', 'Radxa', None, ['a']))

    def test_identity_guard(self):
        valid = dict(serial='DEV-123', device_mac='02:00:00:00:00:01', host_mac='02:00:00:00:00:02')
        gadget.validate(valid)
        for change in ({'serial': '../bad'}, {'device_mac': '01:00:00:00:00:01'},
                       {'host_mac': valid['device_mac']}, {'host_mac': 'not-a-mac'}):
            with self.assertRaises(ValueError):
                gadget.validate(valid | change)

    def test_uninstall_restores_and_detects_external_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            existing, created = Path(tmp) / 'existing', Path(tmp) / 'created'
            existing.write_text('installed')
            created.write_text('new')
            state = {'files': {str(existing): dict(before='original', installed='installed', mode=0o640),
                               str(created): dict(before=None, installed='new', mode=0o644)}}
            installer.check_unchanged(state)
            existing.write_text('user edit')
            with self.assertRaises(ValueError):
                installer.check_unchanged(state)
            existing.write_text('installed')
            installer.restore(state)
            self.assertEqual(existing.read_text(), 'original')
            self.assertFalse(created.exists())

    def lifecycle(self, fail=False, storage=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def target(value):
                value = str(value)
                if value.startswith(('/etc/', '/sys/', '/var/', '/proc/', '/boot/', '/usr/')):
                    return root / value.lstrip('/')
                return Path(value)
            target('/sys/class/udc/controller').mkdir(parents=True)
            target('/etc/dummy').parent.mkdir()
            state = target('/var/lib/usb-cdc-ncm/install.json')
            args = SimpleNamespace(board='generic', network='server', subnet='192.168.7.0/30',
                                   development=True, dry_run=False, gadget='ncm-storage' if storage else 'ncm')
            def command(*argv):
                if fail and argv[:2] == ('systemctl', 'enable'):
                    raise subprocess.CalledProcessError(1, argv)
                return '[]' if argv[0] == 'ip' else ''
            with patch.object(installer, 'Path', side_effect=target), patch.object(installer, 'STATE', state), \
                 patch.object(installer, 'run', side_effect=command), patch.object(installer, 'enabled', return_value=False), \
                 patch.object(installer.subprocess, 'run'), patch.object(installer.shutil, 'which', return_value='/usr/bin/tool'):
                if fail:
                    with self.assertRaises(subprocess.CalledProcessError):
                        installer.install(args)
                    self.assertFalse(state.exists())
                    self.assertFalse(target('/usr/local/sbin/usb-cdc-ncm').exists())
                    self.assertFalse(target('/usr/local/share/usb-cdc-ncm/START-HERE.html').exists())
                    return
                args.dry_run = True
                installer.install(args)
                self.assertFalse(state.exists())
                self.assertFalse(target(installer.IDENTITY).exists())
                args.dry_run = False
                installer.install(args)
                identity = target(installer.IDENTITY).read_text()
                if storage:
                    self.assertEqual(target('/usr/local/share/usb-cdc-ncm/START-HERE.html').read_text(),
                                     (ROOT / 'START-HERE.html').read_text(encoding='utf-8'))
                    self.assertIn('ncm-storage', target('/etc/usb-cdc-ncm-gadget.json').read_text())
                    # An update changes the mode without changing persistent identity.
                    args.gadget = 'ncm'
                args.network = 'client'
                installer.install(args)
                self.assertEqual(target(installer.IDENTITY).read_text(), identity)
                self.assertIn('DHCP=ipv4', target('/etc/systemd/network/10-usb-cdc-ncm.network').read_text())
                self.assertNotIn('ncm-storage', target('/etc/usb-cdc-ncm-gadget.json').read_text())
                installer.uninstall(args)
                self.assertFalse(state.exists())
                self.assertFalse(target('/usr/local/sbin/usb-cdc-ncm').exists())
                self.assertFalse(target('/usr/local/share/usb-cdc-ncm/START-HERE.html').exists())
                self.assertEqual(target(installer.IDENTITY).read_text(), identity)

    def test_install_update_uninstall(self):
        self.lifecycle()

    def test_failed_install_rolls_back(self):
        self.lifecycle(fail=True)

    def test_composite_install_switch_uninstall(self):
        self.lifecycle(storage=True)

    def test_failed_composite_install_rolls_back(self):
        self.lifecycle(fail=True, storage=True)


if __name__ == '__main__':
    unittest.main()
