"""Linux-only gate tests: fake clock setter, temporary state, no host clock changes."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import io
import threading
import time
import os

@unittest.skipUnless(os.name == 'posix', 'Gate uses Linux flock')
class TimeGateTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('gate', Path(__file__).resolve().parents[1] / 'tools/quadra-time-sync.py')
        self.gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.gate)
        self.temp = tempfile.TemporaryDirectory()
        self.gate.ROOT = Path(self.temp.name)
    def tearDown(self):
        self.temp.cleanup()
    def offer(self, epoch='1790000000'):
        with patch.object(self.gate.sys, 'stdin', io.StringIO(epoch)), patch.object(self.gate.select, 'select', return_value=([1], [], [])):
            return self.gate.offer()
    def test_closed_never_sets_time(self):
        with patch.object(self.gate.time, 'clock_settime') as setter:
            self.assertEqual(self.offer(), 3)
            setter.assert_not_called()
    def test_accept_once_and_gate_closes_before_return(self):
        worker = threading.Thread(target=self.gate.gate, args=(1,))
        worker.start()
        for _ in range(100):
            with self.gate.locked():
                if self.gate.read_state().get('open'): break
            time.sleep(.01)
        with patch.object(self.gate.time, 'clock_settime') as setter:
            self.assertEqual(self.offer(), 0)
            self.assertEqual(self.offer(), 3)
            setter.assert_called_once()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertFalse(self.gate.read_state()['open'])
    def test_timeout_and_restart_do_not_reopen(self):
        self.gate.gate(.01)
        self.gate.gate(.1)
        with patch.object(self.gate.time, 'clock_settime') as setter:
            self.assertEqual(self.offer(), 3)
            setter.assert_not_called()
    def test_stale_dead_gate_rejected(self):
        self.gate.save({'open': True, 'deadline': time.monotonic()+5, 'pid': 99999999})
        with patch.object(self.gate.time, 'clock_settime') as setter:
            self.assertEqual(self.offer(), 3)
            setter.assert_not_called()
