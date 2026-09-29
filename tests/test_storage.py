"""Storage image lifecycle and composite ConfigFS ordering without USB hardware."""
import json
from pathlib import Path, PurePosixPath
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from test_installer import gadget


class StorageTests(unittest.TestCase):
    def test_image_build_and_failure_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            html = root / 'START-HERE.html'
            html.write_text('<html>Quadra</html>')
            runtime = root / 'run'
            with patch.object(gadget, 'HTML', html), patch.object(gadget, 'RUNTIME', runtime), \
                 patch.object(gadget.shutil, 'which', return_value='/usr/bin/tool'), \
                 patch.object(gadget.subprocess, 'run') as command:
                image = gadget.prepare_storage()
                self.assertEqual(image.stat().st_size, 32 * 1024 * 1024)
                self.assertEqual(command.call_args_list[1].args[0],
                                 ['mcopy', '-i', str(image), str(html), '::START-HERE.html'])
                image.unlink()
                command.side_effect = subprocess.CalledProcessError(1, 'mkfs.vfat')
                with self.assertRaises(subprocess.CalledProcessError):
                    gadget.prepare_storage()
                self.assertEqual(list(runtime.iterdir()), [])

    def test_missing_tools_do_not_create_image(self):
        with patch.object(gadget.shutil, 'which', return_value=None), \
             patch.object(gadget.subprocess, 'run') as command:
            with self.assertRaisesRegex(ValueError, 'dosfstools and mtools'):
                gadget.prepare_storage()
            command.assert_not_called()

    def exercise_gadget(self, storage=True, fail_bind=False):
        events, nodes, links = [], {'/gadget'}, set()

        class Node(PurePosixPath):
            def exists(self):
                return str(self) in nodes or str(self) == '/sys/kernel/config/usb_gadget'

            def mkdir(self):
                nodes.add(str(self))

            def is_symlink(self):
                return str(self) in links

            def symlink_to(self, target):
                links.add(str(self))
                events.append(('link', str(self)))

            def unlink(self):
                links.remove(str(self))

            def rmdir(self):
                self_path = str(self)
                if '/functions/' in self_path:
                    assert not links, 'All function links must be removed first'
                nodes.remove(self_path)

            def iterdir(self):
                return iter([Node('/sys/class/udc/controller')])

        def write(path, value):
            events.append((str(path), str(value)))
            if fail_bind and str(path).endswith('/UDC') and value:
                raise OSError('No free endpoint')

        identity = dict(serial='DEV-123', device_mac='02:00:00:00:00:01',
                        host_mac='02:00:00:00:00:02')
        image = Mock()
        image.replace.side_effect = lambda target: events.append(('replace', str(target)))
        with patch.object(gadget, 'G', Node('/gadget')), patch.object(gadget, 'Path', Node), \
             patch.object(gadget, 'C', Mock(read_text=lambda: json.dumps(identity))), \
             patch.object(gadget, 'OPTIONS', Mock(read_text=lambda: json.dumps(
                 {'mode': 'ncm-storage' if storage else 'ncm'}))), \
             patch.object(gadget, 'prepare_storage', return_value=image) as prepare, \
             patch.object(gadget, 'write', side_effect=write), \
             patch.object(gadget.subprocess, 'run'):
            if fail_bind:
                with self.assertRaisesRegex(OSError, 'endpoint'):
                    gadget.start()
            else:
                gadget.start()
                self.assertEqual(len(links), 2 if storage else 1)
                if storage:
                    self.assertLess(events.index(('/gadget/UDC', '')),
                                    next(i for i, event in enumerate(events) if event[0] == 'replace'))
                    self.assertLess(events.index(('/gadget/functions/mass_storage.usb0/lun.0/ro', '1')),
                                    events.index(('/gadget/UDC', 'controller')))
                else:
                    prepare.assert_not_called()
                gadget.stop()
                gadget.stop()  # Already stopped is harmless.
            self.assertFalse(nodes)
            self.assertFalse(links)
            self.assertEqual(events[-1], ('/gadget/UDC', ''))

    def test_composite_start_stop(self):
        self.exercise_gadget()

    def test_network_only_start_stop(self):
        self.exercise_gadget(storage=False)

    def test_failed_bind_removes_both_functions(self):
        self.exercise_gadget(fail_bind=True)
