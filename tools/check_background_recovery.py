"""Fault injection against native input recovery, without Qt or real HID."""
from pathlib import Path
import ctypes
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backend
from keyboard_input import KeyboardInput, _RawDevice

passed = 0


def check(condition, label):
    global passed
    assert condition, label
    passed += 1
    print('PASS:', label, flush=True)


def wait_until(predicate, timeout=2):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if predicate():
            return True
        time.sleep(.01)
    return bool(predicate())


backend.find_keyboard_output = lambda preference: (None, 9988, 64, 'wired')
backend.kernel32.CloseHandle = lambda handle: True
engine = backend.LightingController()
engine.base, engine.accent = (255, 255, 255), (255, 0, 0)
engine._write_report = lambda packet, handle=None: None
keys = {}
listener = engine.keyboard_input
listener.user32.GetAsyncKeyState = lambda vk: keys.get(vk, 0)
try:
    engine.connect()
    check(wait_until(lambda: engine._stream_frame_count > 3), 'background frames start with no GUI callbacks')
    first_thread = listener.thread
    check(listener._registration_matches(), 'native keyboard registration targets receiver')

    # Simulate another component removing the process registration.
    remove = _RawDevice(1, 6, 1, None)
    check(bool(listener.user32.RegisterRawInputDevices(ctypes.byref(remove), 1, ctypes.sizeof(remove))), 'fault: remove process background input registration')
    listener._last_registration_check = 0
    check(wait_until(lambda: listener.repairs > 0 and listener._registration_matches()), 'missing raw registration repairs without opening window')
    check(listener.thread is first_thread, 'registration repair preserves healthy receiver')

    # Simulate a missing WM_TIMER. Disable one timer on our own hidden native
    # window, then let real elapsed time trigger the worker's heartbeat probe.
    check(bool(listener.user32.KillTimer(listener.hwnd, 1)), 'fault: stop native input timer')
    time.sleep(.06)
    listener._last_maintenance = 0
    wake_before = listener.wakes
    keys[ord('W')] = 0x8000
    consumed = engine._stream_event_count
    check(wait_until(lambda: engine._stream_event_count > consumed), 'lighting worker supplies key-state fallback when native timer is missing')
    check(wait_until(lambda: listener.wakes > wake_before, 4), 'worker wakes native receiver and reinstalls timer')
    sampled = listener.last_sample_at
    check(wait_until(lambda: listener.last_sample_at > sampled + .04), 'native timer resumes after wake')
    check(listener.thread is first_thread, 'wake avoids unnecessary thread or HID replacement')
    keys.clear()
    time.sleep(.06)

    # Real receiver-loop exit, preserving enabled intent. Watchdog must create
    # a replacement without relying on LightingController.tick or a Qt timer.
    old_thread = listener.thread
    listener.user32.PostMessageW(listener.hwnd, 0x0010, 0, 0)
    check(wait_until(lambda: not old_thread.is_alive()), 'fault: native receiver exits')
    listener._last_maintenance = 0
    check(wait_until(lambda: listener.thread is not old_thread and listener.running), 'dead receiver restarts from lighting worker')
    check(listener.restarts > 0 and listener._registration_matches(), 'replacement re-registers background input')
    keys[ord('A')] = 0x8000
    consumed = engine._stream_event_count
    check(wait_until(lambda: engine._stream_event_count > consumed), 'replacement events reach completed output frames')
    check(engine.stream_healthy and engine.worker_error is None, 'input faults do not disconnect healthy HID stream')
    keys.clear()
    time.sleep(.05)

    # Absence of typing is not evidence of failure. Old event age may be days
    # while the message-pump heartbeat stays healthy.
    thread = listener.thread
    restarts, wakes = listener.restarts, listener.wakes
    listener.last_press_at = time.perf_counter() - 86400
    time.sleep(.1)
    listener._last_maintenance = 0
    listener.maintain()
    check(listener.thread is thread and (listener.restarts, listener.wakes) == (restarts, wakes), 'idle keyboard does not trigger spurious recovery')

    engine.set_active(False)
    time.sleep(.08)
    check(not listener.enabled and not listener.running, 'pause disables receiver intent')
    listener.maintain(time.perf_counter() + 20)
    check(not listener.running, 'watchdog never revives explicitly paused input')
    engine.set_active(True)
    check(wait_until(lambda: listener.running), 'resume enables a receiver again')
    check('pump=' in listener.diagnostics() and 'repairs=' in listener.diagnostics(), 'diagnostics distinguish input heartbeat and repair counts')
finally:
    engine.close()

# Simulate a responsive Python thread whose native pump ignores messages. The
# worker must retain a sampler, avoid duplicate receivers and recover after
# the original thread can finally stop.
class StalledReceiver(KeyboardInput):
    def __init__(self):
        super().__init__(backend.VK_NAMES, lambda name, at: seen.append(name))
        self.release = threading.Event()

    def _run(self):
        self.hwnd = None
        self.last_pump_at = time.perf_counter() - 10
        self.ready.set()
        self.release.wait(5)


seen = []
stalled = StalledReceiver()
stalled.user32.GetAsyncKeyState = lambda vk: 0x8000 if vk == ord('D') else 0
try:
    stalled.start()
    old_thread = stalled.thread
    stalled.maintain()
    stalled._last_maintenance = 0
    stalled._wake_sent_at -= 3
    stalled.maintain()
    check(stalled.thread is old_thread and old_thread.is_alive(), 'unresponsive receiver is not duplicated or force-killed')
    stalled._sampled_down.clear()
    stalled.last_sample_at = 0
    stalled.maintain()
    check(seen.count('D') >= 2, 'backup sampler survives bounded stop timeout')
finally:
    stalled.release.set()
    stalled.stop()

print(f'PASS: {passed} background recovery checks; no physical HID, no keyboard injection, no UI loop')
