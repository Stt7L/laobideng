"""Regression checks for missing background packets; no input injection or HID."""
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import VK_NAMES
from keyboard_input import KeyboardInput

passed = 0


def check(condition, label):
    global passed
    assert condition, label
    passed += 1
    print('PASS:', label, flush=True)


events = []
listener = KeyboardInput(VK_NAMES, lambda name, at: events.append(name))
states = {}
listener.user32.GetAsyncKeyState = lambda vk: states.get(vk, 0)

states[ord('W')] = 0x8000
listener._sample_keys()
check(events == ['W'], 'missing raw packets still produce a press')
for _ in range(20):
    listener._sample_keys()
check(events == ['W'], 'held fallback key never repeats')
listener.feed(1, ord('W'), 0x11, 0)
check(events == ['W'], 'sampler before raw produces one wave')
states.clear()
listener.feed(1, ord('W'), 0x11, 1)
listener._sample_keys()
listener.feed(1, ord('W'), 0x11, 0)
states[ord('W')] = 0x8000
listener._sample_keys()
check(events == ['W', 'W'], 'raw before sampler produces one wave')
listener.feed(2, ord('W'), 0x11, 0)
check(events == ['W', 'W', 'W'], 'raw device identities remain independent')
listener.feed(1, ord('W'), 0x11, 1)
listener.feed(2, ord('W'), 0x11, 1)
states.clear()
listener._sample_keys()

before = len(events)
for _ in range(10):
    listener.feed(1, ord('A'), 0x1e, 0)
    listener.feed(1, ord('A'), 0x1e, 1)
check(len(events) - before == 10, 'fast repeated physical taps are not debounced away')
states[ord('D')] = 1
listener._sample_keys()
check(events[-1] != 'D', 'unreliable low bit does not synthesize a press')
states.clear()
states[0xA0] = states[ord('W')] = states[0x20] = 0x8000
before = len(events)
listener._sample_keys()
check(set(events[before:]) == {'Left Shift', 'W', 'Space'}, 'game chord supports modifiers and space')
states.clear()
listener._sample_keys()
listener.feed(1, ord('S'), 0x1f, 0)
listener._raw_at[(1, 'S')] -= .2
listener._sample_keys()
check((1, 'S') not in listener.held, 'lost break packet does not latch the key forever')
before = len(events)
listener.feed(1, ord('S'), 0x1f, 0)
check(len(events) == before + 1, 'key works again after lost break recovery')
listener.feed(1, ord('S'), 0x1f, 1)
listener.feed(1, 0x0D, 0x1c, 2)
states[0x0D] = 0x8000
before = len(events)
listener._sample_keys()
check(len(events) == before, 'raw numpad Enter is not duplicated as main Enter')
check('raw=' in listener.diagnostics() and 'fallback=' in listener.diagnostics(), 'diagnostics contain counts without key names')
listener.stop()
before = len(events)
listener._sample_keys()
check(len(events) == before, 'stop disables compatibility sampling')

# Native WM_TIMER execution must continue with no Qt/UI event loop. Only this
# process has its synthetic API state replaced; no system keys are generated.
calls = []
states.clear()


def state(vk):
    calls.append(threading.get_ident())
    return states.get(vk, 0)


listener.user32.GetAsyncKeyState = state
listener.start()
states[ord('W')] = 0x8000
deadline = time.perf_counter() + 1
before = len(events)
while time.perf_counter() < deadline and len(events) == before:
    time.sleep(.01)
check(len(events) > before and events[-1] == 'W', 'native receiver timer emits without UI callbacks')
check(set(calls) == {listener.thread.ident}, 'all key-state calls run on receiver thread')
listener.stop()
check(not listener.running and not listener.thread.is_alive(), 'native timer and receiver stop together')
check(not listener.held and not listener._sampled_down, 'shutdown clears both input states')

# Exercise the full receiver -> renderer -> complete frame path, with fake HID
# only. The main thread does not call engine.tick or run a GUI event loop.
import backend
backend.find_keyboard_output = lambda preference: (None, 9999, 64, 'wired')
backend.kernel32.CloseHandle = lambda handle: True
engine = backend.LightingController()
engine.base, engine.accent = (255, 255, 255), (255, 0, 0)
writes = []
engine._write_report = lambda packet, handle=None: writes.append(packet)
game_keys = {}
engine.keyboard_input.user32.GetAsyncKeyState = lambda vk: game_keys.get(vk, 0)
try:
    engine.connect()
    game_keys[ord('A')] = 0x8000
    deadline = time.perf_counter() + 1
    while time.perf_counter() < deadline and not any(rgb != engine.base_color() for rgb in engine.preview_frame()):
        time.sleep(.01)
    check(engine.keyboard_input.fallback_presses > 0, 'connected controller receives fallback without raw packets')
    check(any(rgb != engine.base_color() for rgb in engine.preview_frame()) and bool(writes), 'fallback reaches completed reactive lighting frame without UI ticks')
finally:
    engine.close()
print(f'PASS: {passed} game-input checks; synthetic state only, no game claim')
