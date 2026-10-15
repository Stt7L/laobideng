"""Isolated checks: background input lifecycle and tray popup dismissal."""

import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import LightingController, VK_NAMES
from keyboard_input import KeyboardInput, _RawDevice, key_name
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from ui_app import control_icon, load_ui_font, ui_display_font, ui_stylesheet
from ui_tray import TrayMenu

passed = 0


def check(condition, label):
    global passed
    assert condition, label
    passed += 1
    print("PASS:", label, flush=True)


for args, expected in [((0x10, 0x2A, 0), "Left Shift"), ((0x10, 0x36, 0), "Right Shift"),
                       ((0x11, 0x1D, 0), "Left Ctrl"), ((0x11, 0x1D, 2), "Right Ctrl"),
                       ((0x12, 0x38, 0), "Left Alt"), ((0x12, 0x38, 2), "Right Alt"),
                       ((0x0D, 0x1C, 0), "Enter"), ((0x0D, 0x1C, 2), "Num Enter"),
                       ((0x24, 0x47, 0), "Num 7"), ((0x24, 0x47, 2), "Home"),
                       ((255, 0xFF, 0), None)]:
    check(key_name(*args, VK_NAMES) == expected, "physical key normalization")

events = []
listener = KeyboardInput(VK_NAMES, lambda name, now: events.append((name, now)))
listener.feed(1, ord("A"), 0x1E, 0)
listener.feed(1, ord("A"), 0x1E, 0)
check(len(events) == 1, "held key does not repeat")
listener.feed(1, ord("A"), 0x1E, 1)
listener.feed(1, ord("A"), 0x1E, 0)
check(len(events) == 2, "release allows a new press")
listener.feed(2, ord("A"), 0x1E, 0)
check(len(events) == 3, "key state isolated per device")
listener._window_proc(0, 0x00FE, 2, 1)
check((1, "A") not in listener.held and (2, "A") in listener.held, "unplug clears only removed keyboard")
listener.feed(1, 0x13, 0x45, 4)
listener.feed(1, 0x13, 0x45, 4)
check(len(events) == 5, "Pause without break never latches")
listener.stop()
listener.feed(3, ord("A"), 0x1E, 0)
check(len(events) == 5, "stopped listener ignores events")

for _ in range(4):
    listener.start()
    check(listener.running and listener.thread.ident != __import__("threading").get_ident(), "native receiver owns independent message thread")
    listener.start()
    count = wintypes.UINT()
    u = listener.user32
    u.GetRegisteredRawInputDevices.argtypes = [ctypes.POINTER(_RawDevice), ctypes.POINTER(wintypes.UINT), wintypes.UINT]
    u.GetRegisteredRawInputDevices.restype = wintypes.UINT
    u.GetRegisteredRawInputDevices(None, ctypes.byref(count), ctypes.sizeof(_RawDevice))
    devices = (_RawDevice * count.value)()
    u.GetRegisteredRawInputDevices(devices, ctypes.byref(count), ctypes.sizeof(_RawDevice))
    check(any(d.page == 1 and d.usage == 6 and d.flags & 0x100 and not d.flags & 0x30 and d.target == listener.hwnd for d in devices), "background sink registered without suppressing game input")
    listener.stop()
    check(not listener.thread.is_alive() and listener.hwnd is None, "stop releases native window and message pump")

engine = LightingController()
try:
    for i in range(1100):
        engine._key_pressed("A", float(i))
    check(engine.events.qsize() == 1024, "input backlog is bounded and nonblocking")
    engine._remove_hook()
    check(engine.events.empty(), "effect stop clears pending input")
finally:
    engine.close()

app = QApplication([sys.argv[0], "-platform", "windows:fontengine=freetype"])
app.setStyle("Fusion")
load_ui_font()
app.setFont(ui_display_font(10))
app.setStyleSheet(ui_stylesheet())


class Host(QWidget):
    def __init__(self):
        super().__init__()
        self.calls = []

    def show_window(self):
        self.calls.append("show")

    def _toggle_effect(self):
        self.calls.append("toggle")

    def exit_app(self):
        self.calls.append("quit")


host = Host()
host.setWindowTitle("老必灯 · 托盘检查")
host.resize(500, 300)
host.show()
menu = TrayMenu(host, control_icon)
# Stable ownership for deterministic keyboard/layout checks. Restore before
# testing the native foreground/deactivation path.
native_foreground = menu.user32.GetForegroundWindow
menu.user32.GetForegroundWindow = lambda: int(menu.winId())


def open_menu():
    if menu.isVisible():
        menu.hide()
    menu.popup(QPoint(500, 400))
    app.processEvents()


try:
    open_menu()
    check(menu.isVisible() and menu.watchdog.isActive(), "popup visible with lifecycle watchdog")
    menu.set_active(False)
    check(menu.toggle_button.text() == "继续灯效" and not menu.toggle_button.icon().isNull(), "paused action has matching text and icon")
    menu.set_active(True)
    QTest.keyClick(menu, Qt.Key.Key_Down)
    check(menu.toggle_button.hasFocus(), "arrow keys select actions")
    QTest.keyClick(menu, Qt.Key.Key_Return)
    app.processEvents()
    check(host.calls == ["toggle"] and not menu.isVisible(), "Enter closes popup before invoking exactly once")
    check(not menu.watchdog.isActive(), "hidden popup stops polling")
    open_menu()
    QTest.keyClick(menu, Qt.Key.Key_Escape)
    check(not menu.isVisible(), "Escape dismisses menu")
    open_menu()
    QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=QPoint(1, 1))
    check(not menu.isVisible(), "outside panel dismisses menu")
    open_menu()
    QApplication.sendEvent(menu, QEvent(QEvent.Type.WindowDeactivate))
    check(not menu.isVisible(), "window deactivation dismisses menu")
    open_menu()
    menu._opened_at = time.monotonic() - 1
    menu.user32.GetForegroundWindow = lambda: int(host.winId())
    menu._check_owner()
    check(not menu.isVisible(), "native foreground change dismisses stale popup")
    menu.user32.GetForegroundWindow = lambda: int(menu.winId())
    open_menu()
    menu._opened_at = time.monotonic() - 1
    menu._anchor_host = (int(host.winId()), (0, 0, 0, 0))
    menu._check_owner()
    check(not menu.isVisible(), "tray host moving or collapsing dismisses popup")
    menu._anchor_host = None
    open_menu()
    screen = menu.screen().availableGeometry()
    menu.hide()
    menu.popup(screen.bottomRight())
    app.processEvents()
    check(screen.contains(menu.geometry()), "popup stays inside screen work area")
    for button in menu.buttons:
        check(button.width() > button.fontMetrics().horizontalAdvance(button.text()) + 45, "action text and icon fit")
    menu.grab().save(str(Path(__file__).resolve().parents[1] / "build" / "tray-v158.png"))
finally:
    menu.user32.GetForegroundWindow = native_foreground
    menu.hide()
    host.close()
print(f"PASS: {passed} input/tray checks; no HID writes or settings changes")
