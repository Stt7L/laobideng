"""Read physical keyboard transitions on an independent Windows message loop.

RIDEV_INPUTSINK observes background input without consuming game input or
installing a low-level hook. Only transient lighting events leave this thread.
"""

import ctypes
from ctypes import wintypes
import logging
import threading
import time

LOG = logging.getLogger("vgn-ripple")
WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                            wintypes.WPARAM, wintypes.LPARAM)


class _WindowClass(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("proc", WNDPROC),
                ("class_extra", ctypes.c_int), ("window_extra", ctypes.c_int),
                ("instance", wintypes.HINSTANCE), ("icon", wintypes.HICON),
                ("cursor", wintypes.HANDLE), ("background", wintypes.HBRUSH),
                ("menu", wintypes.LPCWSTR), ("name", wintypes.LPCWSTR)]


class _RawDevice(ctypes.Structure):
    _fields_ = [("page", wintypes.USHORT), ("usage", wintypes.USHORT),
                ("flags", wintypes.DWORD), ("target", wintypes.HWND)]


class _RawHeader(ctypes.Structure):
    _fields_ = [("kind", wintypes.DWORD), ("size", wintypes.DWORD),
                ("device", wintypes.HANDLE), ("wparam", wintypes.WPARAM)]


class _RawKeyboard(ctypes.Structure):
    _fields_ = [("scan", wintypes.USHORT), ("flags", wintypes.USHORT),
                ("reserved", wintypes.USHORT), ("vk", wintypes.USHORT),
                ("message", wintypes.UINT), ("extra", wintypes.ULONG)]


class _RawPacket(ctypes.Structure):
    _fields_ = [("header", _RawHeader), ("keyboard", _RawKeyboard)]


def key_name(vk, scan, flags, names):
    """Normalize physical modifiers and numpad independently of Num Lock."""
    if vk == 255 or scan == 0xFF:
        return None
    extended = bool(flags & 2)
    if vk == 0x10:
        vk = 0xA1 if scan == 0x36 else 0xA0
    elif vk == 0x11:
        vk = 0xA3 if extended else 0xA2
    elif vk == 0x12:
        vk = 0xA5 if extended else 0xA4
    if vk == 0x0D and extended:
        return "Num Enter"
    if not extended and not flags & 4:
        numpad = {0x47: "Num 7", 0x48: "Num 8", 0x49: "Num 9",
                  0x4B: "Num 4", 0x4C: "Num 5", 0x4D: "Num 6",
                  0x4F: "Num 1", 0x50: "Num 2", 0x51: "Num 3",
                  0x52: "Num 0", 0x53: "Num ."}
        if scan in numpad:
            return numpad[scan]
    return names.get(vk)


class KeyboardInput:
    def __init__(self, names, on_press):
        self.names = names
        self.on_press = on_press
        self.thread = None
        self.hwnd = None
        self.error = None
        self.ready = threading.Event()
        self.stopping = threading.Event()
        self.held = set()
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        u = self.user32
        u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u.DefWindowProcW.restype = ctypes.c_ssize_t
        u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                     wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                     wintypes.HINSTANCE, ctypes.c_void_p]
        u.CreateWindowExW.restype = wintypes.HWND
        u.RegisterClassW.argtypes = [ctypes.POINTER(_WindowClass)]
        u.RegisterClassW.restype = wintypes.ATOM
        u.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
        u.RegisterRawInputDevices.argtypes = [ctypes.POINTER(_RawDevice), wintypes.UINT, wintypes.UINT]
        u.GetRawInputData.argtypes = [wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p,
                                     ctypes.POINTER(wintypes.UINT), wintypes.UINT]
        u.GetRawInputData.restype = wintypes.UINT
        u.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        u.GetMessageW.restype = wintypes.BOOL
        u.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        u.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        u.DispatchMessageW.restype = ctypes.c_ssize_t
        u.DestroyWindow.argtypes = [wintypes.HWND]
        u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self.kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self.kernel32.GetModuleHandleW.restype = wintypes.HMODULE

    @property
    def running(self):
        return bool(self.thread and self.thread.is_alive() and self.hwnd and not self.stopping.is_set())

    def start(self):
        if self.running:
            return
        if self.thread and self.thread.is_alive():
            raise OSError("Keyboard input is still stopping")
        self.ready.clear()
        self.stopping.clear()
        self.error = None
        self.thread = threading.Thread(target=self._run, name="Lighting-keyboard-input", daemon=True)
        self.thread.start()
        if not self.ready.wait(1.5):
            self.stop()
            raise OSError("Keyboard input initialization timed out")
        if self.error:
            raise OSError("Keyboard input unavailable") from self.error

    def stop(self):
        self.stopping.set()
        if self.hwnd:
            self.user32.PostMessageW(self.hwnd, 0x0010, 0, 0)
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=.25)

    def feed(self, device, vk, scan, flags):
        if self.stopping.is_set():
            return
        name = key_name(vk, scan, flags, self.names)
        if name is None:
            return
        key = (device, name)
        if flags & 1:
            self.held.discard(key)
        elif key not in self.held:
            self.held.add(key)
            self.on_press(name, time.perf_counter())
            # Pause often has no break packet. Do not latch it forever.
            if name == "Pause":
                self.held.discard(key)

    def _window_proc(self, hwnd, message, wparam, lparam):
        try:
            if message == 0x00FF:  # WM_INPUT: read before DefWindowProc cleanup.
                size = wintypes.UINT()
                u = self.user32
                if u.GetRawInputData(lparam, 0x10000003, None, ctypes.byref(size), ctypes.sizeof(_RawHeader)) == 0:
                    if ctypes.sizeof(_RawPacket) <= size.value <= 4096:
                        data = ctypes.create_string_buffer(size.value)
                        received = u.GetRawInputData(lparam, 0x10000003, data, ctypes.byref(size), ctypes.sizeof(_RawHeader))
                        if received == size.value:
                            packet = _RawPacket.from_buffer(data)
                            if packet.header.kind == 1:
                                k = packet.keyboard
                                self.feed(packet.header.device, k.vk, k.scan, k.flags)
            elif message == 0x00FE and wparam == 2:  # Device removal clears held keys.
                self.held = {key for key in self.held if key[0] != lparam}
            elif message == 0x0010:
                self.user32.DestroyWindow(hwnd)
                return 0
            elif message == 0x0002:
                self.user32.PostQuitMessage(0)
                return 0
        except Exception:
            LOG.exception("Keyboard input packet could not be processed")
        return self.user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _run(self):
        instance = self.kernel32.GetModuleHandleW(None)
        class_name = f"LaoBiDengInput-{id(self)}"
        proc = WNDPROC(self._window_proc)
        window_class = _WindowClass(0, proc, 0, 0, instance, None, None, None, None, class_name)
        registered = False
        try:
            if not self.user32.RegisterClassW(ctypes.byref(window_class)):
                raise ctypes.WinError(ctypes.get_last_error())
            registered = True
            self.hwnd = self.user32.CreateWindowExW(0, class_name, "", 0, 0, 0, 0, 0,
                                                    wintypes.HWND(-3), None, instance, None)
            if not self.hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            device = _RawDevice(1, 6, 0x00000100 | 0x00002000, self.hwnd)
            if not self.user32.RegisterRawInputDevices(ctypes.byref(device), 1, ctypes.sizeof(device)):
                raise ctypes.WinError(ctypes.get_last_error())
            self.ready.set()
            LOG.info("Background keyboard input registered on dedicated thread")
            message = wintypes.MSG()
            while not self.stopping.is_set():
                result = self.user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result == -1:
                    raise ctypes.WinError(ctypes.get_last_error())
                if result == 0:
                    break
                self.user32.TranslateMessage(ctypes.byref(message))
                self.user32.DispatchMessageW(ctypes.byref(message))
        except Exception as error:
            self.error = error
            LOG.exception("Background keyboard input stopped unexpectedly")
        finally:
            if self.hwnd:
                device = _RawDevice(1, 6, 1, None)
                self.user32.RegisterRawInputDevices(ctypes.byref(device), 1, ctypes.sizeof(device))
                self.user32.DestroyWindow(self.hwnd)
            self.hwnd = None
            self.held.clear()
            if registered:
                self.user32.UnregisterClassW(class_name, instance)
            self.ready.set()
