"""Exercise isolated rendering/writer ownership with fake HID and audio."""

from collections import Counter
from pathlib import Path
import queue
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backend

passed = 0


def check(condition, label):
    global passed
    assert condition, label
    passed += 1
    print("PASS:", label, flush=True)


def wait_until(predicate, timeout=1.5):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if predicate():
            return True
        time.sleep(.005)
    return bool(predicate())


class Audio:
    def __init__(self):
        self.available = False
        self.mode = "spectrum"
        self.level = self.instant = self.impact = self.rise = .4
        self.bands = (.4, .2, .1)
        self.beat_serial = 0
        self.beat_time = 0
        self.sample_threads = set()
        self.close_threads = set()
        self.refreshes = 0

    def sample(self):
        self.available = True
        self.sample_threads.add(threading.get_ident())
        return .4

    def close(self):
        if self.available:
            self.close_threads.add(threading.get_ident())
        self.available = False

    def refresh(self):
        self.close()
        self.refreshes += 1


backend.AudioSpectrum = Audio
closed = []
backend.kernel32.CloseHandle = lambda handle: closed.append(handle) or True
handle_counter = 100
transport = "wired"


def discover(_preference):
    global handle_counter
    handle_counter += 1
    return None, handle_counter, 64, transport


backend.find_keyboard_output = discover


def controller(effect="rainbow"):
    engine = backend.LightingController()
    engine.effect = effect
    engine.keyboard_input.start = lambda: None
    writes = []
    engine._write_report = lambda packet, handle=None: writes.append((handle, threading.get_ident(), time.perf_counter(), packet))
    return engine, writes


engine, writes = controller()
engine.connect()
handle = engine.handle
check(wait_until(lambda: engine._stream_frame_count >= 4), "wired renderer starts without UI ticks")
initial = engine._stream_frame_count
time.sleep(.35)
check(engine._stream_frame_count - initial >= 7, "animation continues while UI does no work")
check(engine.stream_healthy, "heartbeat reflects completed sends")
check(all(tid != threading.get_ident() for _h, tid, _t, packet in writes if packet[3] == 0x12), "all frame packets sent outside UI thread")
engine.set_active(False)
check(wait_until(lambda: len(set(engine.preview_frame())) == 1), "pause produces uniform base frame")
engine.base = (17, 71, 203)
check(wait_until(lambda: engine.preview_frame()[0] == engine.base_color()), "paused base color changes still reach stream")
engine.set_active(True)
check(wait_until(lambda: len(set(engine.preview_frame())) > 1), "resume restarts moving effect")
engine.set_effect("audio_spectrum")
check(wait_until(lambda: bool(engine.audio_meter.sample_threads)), "music sampled by independent renderer")
audio = engine.audio_meter
engine.refresh_audio()
check(wait_until(lambda: audio.refreshes > 0), "audio refresh dispatched to owner thread")
engine.set_effect("rainbow")
check(wait_until(lambda: bool(audio.close_threads)), "leaving music releases audio")
check(audio.close_threads <= audio.sample_threads and threading.get_ident() not in audio.close_threads,
      "Core Audio cleanup stays on sampling thread")
worker = engine.worker
engine.close()
check(not worker.is_alive(), "shutdown joins writer")
check(Counter(closed)[handle] == 1, "HANDLE closed exactly once by worker")

engine, writes = controller("ripple")
engine.base, engine.accent = (255, 255, 255), (255, 0, 0)
engine.connect()
check(wait_until(lambda: engine._stream_frame_count > 1), "reactive renderer starts")
engine._key_pressed("A", time.perf_counter())
check(wait_until(lambda: any(rgb != engine.base_color() for rgb in engine.preview_frame())), "input event renders without UI callbacks")
engine.close()

transport = "wireless"
engine, writes = controller()
engine.connect()
check(wait_until(lambda: engine._stream_frame_count >= 2), "wireless renderer continues independently")
frame_writes = [entry for entry in writes if entry[3][3] == 0x12]
check(len(frame_writes) >= 32 and all(entry[3][4] == 0x18 for entry in frame_writes), "wireless commits preserve 16-report format")
check(min(b[2] - a[2] for a, b in zip(frame_writes, frame_writes[1:])) >= .009, "wireless pacing preserved")
engine.close()

transport = "wired"
engine, writes = controller()


def broken_write(packet, handle=None):
    if packet[3] == 0x12:
        raise OSError("simulated unplug")


engine._write_report = broken_write
engine.connect()
old_handle = engine.handle
check(wait_until(lambda: engine.worker_error is not None), "send error reaches UI snapshot")
try:
    engine.tick()
except OSError:
    pass
else:
    raise AssertionError("stream error not raised")
check(not engine.connected and Counter(closed)[old_handle] == 1, "failed stream closes old HANDLE once")
engine._write_report = lambda packet, handle=None: writes.append((engine.handle if handle is None else handle, packet))
engine.connect()
new_handle = engine.handle
check(wait_until(lambda: engine._stream_frame_count >= 2), "reconnection creates healthy new writer")
check(new_handle != old_handle and all(h == new_handle for h, _packet in writes), "new writer never reuses stale HANDLE")
engine.close()
print(f"PASS: {passed} independent stream checks; fake HID/audio only")
