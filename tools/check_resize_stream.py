"""Measure resize work and verify lighting survives a blocked UI message loop.

HID discovery/writes are replaced locally; this never opens the user's device.
"""

import argparse
import ctypes
from pathlib import Path
import statistics
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backend
import ui_app
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

parser = argparse.ArgumentParser()
parser.add_argument("--baseline", action="store_true")
parser.add_argument("--interactive", action="store_true")
args = parser.parse_args()
app = QApplication([sys.argv[0], "-platform", "windows:fontengine=freetype"])
app.setStyle("Fusion")
ui_app.load_ui_font()
app.setFont(ui_app.ui_display_font(10))
app.setStyleSheet(ui_app.ui_stylesheet())
ui_app.read_settings = lambda: {"effect": "rainbow", "base": "#FFFFFF", "accent": "#FF6157"}
class ResizeProbe(ui_app.MainWindow):
    def nativeEvent(self, kind, pointer):
        message = ctypes.wintypes.MSG.from_address(int(pointer)).message
        if message == 0x0231 and "engine" in globals():
            self._probe_start = (engine._stream_frame_count, time.perf_counter())
        result = super().nativeEvent(kind, pointer)
        if message == 0x0232 and hasattr(self, "_probe_start"):
            count, started = self._probe_start
            print(f"native size/move: {time.perf_counter() - started:.3f}s; "
                  f"completed lighting frames: {engine._stream_frame_count - count}", flush=True)
        return result


window = ResizeProbe(preview=True)
window.resize(1180, 760)
window.show()
app.processEvents()

# A fake HANDLE is never handed to Win32. The controller's writer and closer
# are replaced for this entire isolated process.
backend.find_keyboard_output = lambda _preference: (None, 123, 64, "wired")
original_close = backend.kernel32.CloseHandle
backend.kernel32.CloseHandle = lambda _handle: True
packets = []
writer_threads = set()
engine = backend.LightingController()
engine.effect = "rainbow"


def write(packet, handle=None):
    if len(packet) > 3 and packet[3] == 0x12:
        packets.append(time.perf_counter())
        writer_threads.add(threading.get_ident())
    time.sleep(.0003)


engine._write_report = write
engine.connect()
timer = QTimer()
timer.timeout.connect(engine.tick)
timer.start(33)
for _ in range(20):
    app.processEvents()
    time.sleep(.01)
before = len(packets)
time.sleep(.7)  # Same absence of UI callbacks as a blocked native sizing loop.
frames_during_ui_stall = (len(packets) - before) // 7
print(f"frames during 700 ms without UI callbacks: {frames_during_ui_stall}", flush=True)
if not args.baseline:
    assert frames_during_ui_stall >= 8, "lighting depends on UI callbacks"
    assert threading.get_ident() not in writer_threads, "UI thread still sends HID packets"
    old_engine = window.engine
    old_worker = engine.worker
    window.engine = engine
    window.preview_mode = False
    window._last_tick_wall = time.time() - 10
    window._frame_tick()
    assert engine.worker is old_worker and engine.connected, "UI stall incorrectly triggered reconnect"
    window.engine = old_engine
    window.preview_mode = True
    print("PASS: 10-second UI gap does not reconnect a healthy stream", flush=True)

    user32 = ctypes.WinDLL("user32")
    user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
    user32.SendMessageW(int(window.winId()), 0x0231, 0, 0)
    assert window._native_resizing and not window._window_frame.shadow.isVisible()
    print("PASS: native sizing loop suspends layered shadow", flush=True)

costs = []
for i in range(72):
    width = 900 + (i * 17) % 540
    height = 630 + (i * 9) % 280
    start = time.perf_counter()
    window.resize(width, height)
    app.processEvents()
    costs.append((time.perf_counter() - start) * 1000)
print(f"resize rounds: {len(costs)}; median={statistics.median(costs):.2f} ms; "
      f"p95={sorted(costs)[int(len(costs) * .95)]:.2f} ms", flush=True)
if not args.baseline:
    user32.SendMessageW(int(window.winId()), 0x0232, 0, 0)
    assert not window._native_resizing and window._window_frame.shadow.isVisible()
    print("PASS: leaving native sizing restores shadow and preview", flush=True)
if args.interactive:
    window.setWindowTitle("老必灯 · 缩放检查")
    window.resize(1180, 760)
    window._window_frame.ensure_visible()
    print("READY: native sizing probe; fake HID only", flush=True)
    app.exec()
timer.stop()
engine.close()
backend.kernel32.CloseHandle = original_close
window.close()
app.processEvents()
print("Done: fake HID only; no settings changed", flush=True)
