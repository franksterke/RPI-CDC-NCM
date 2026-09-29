#!/usr/bin/env python3
"""A bounded, once-per-boot clock gate before Capture is launched."""
import fcntl
import json
import math
import os
from pathlib import Path
import select
import sys
import time
from contextlib import contextmanager

ROOT = Path('/run/quadra-time-sync')

@contextmanager
def locked():
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (ROOT / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield

def read_state():
    path = ROOT / 'state.json'
    return json.loads(path.read_text()) if path.exists() else {}

def save(state):
    (ROOT / 'state.json').write_text(json.dumps(state))

def gate(seconds=5):
    with locked():
        if read_state():
            print('Time window already used this boot; starting Capture without clock changes.', flush=True)
            return
        save({'pid': os.getpid(), 'deadline': time.monotonic() + seconds, 'open': True})
    print(f'Waiting up to {seconds} seconds for PC time before Capture starts.', flush=True)
    try:
        while True:
            with locked():
                state = read_state()
                if not state.get('open') or time.monotonic() >= state['deadline']:
                    state['open'] = False
                    save(state)
                    break
            time.sleep(0.05)
    finally:
        with locked():
            state = read_state()
            state['open'] = False
            save(state)
    print('Time window closed. No further automatic clock updates this boot.', flush=True)

def offer():
    # Request the timestamp only after SSH authentication, reducing clock error.
    print('READY', flush=True)
    if not select.select([sys.stdin], [], [], 2)[0]:
        return 2
    epoch = float(sys.stdin.readline().strip())
    if not math.isfinite(epoch) or not 1577836800 <= epoch <= 4102444800:
        raise ValueError('PC timestamp outside supported range (2020-2100)')
    with locked():
        state = read_state()
        if not state.get('open') or time.monotonic() >= state.get('deadline', 0):
            print('CLOSED: Capture time window is not open; clock unchanged.', flush=True)
            return 3
        try:
            os.kill(state['pid'], 0)
        except ProcessLookupError:
            state['open'] = False
            save(state)
            return 3
        # Consume the window BEFORE changing the clock, even if setting it fails.
        state['open'] = False
        save(state)
        time.clock_settime(time.CLOCK_REALTIME, epoch)
        print('SYNCED: PC time accepted before Capture startup.', flush=True)
    return 0

if __name__ == '__main__':
    if os.geteuid() != 0:
        sys.exit('Must run as root')
    try:
        if sys.argv[1:] == ['gate']:
            gate()
        elif sys.argv[1:] == ['offer']:
            sys.exit(offer())
        else:
            sys.exit('Usage: quadra-time-sync gate|offer')
    except (OSError, ValueError) as exc:
        sys.exit(str(exc))
