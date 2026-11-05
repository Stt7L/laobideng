"""Read physical keyboard transitions on an independent Windows message loop.

Raw Input supplies physical keys; a thread-local key-state sampler covers
foreground applications that stop delivering background packets. Neither path
consumes or injects input. Only transient lighting events leave this thread.
"""

import ctypes
from ctypes import wintypes
import logging
import threading
import time

LOG = logging.getLogger("vgn-ripple")
WM_INPUT_WAKE = 0x8001
# These physical keys share asynchronous virtual-key states. Prefer the raw
# name when it is available; the fallback alone cannot distinguish them.
POLL_ALIASES = {"Num Enter": "Enter", "Num 7": "Home", "Num 8": "Up Arrow",
                "Num 9": "Page Up", "Num 4": "Left Arrow", "Num 6": "Right Arrow",
                "Num 1": "End", "Num 2": "Down Arrow", "Num 3": "Page Down",
                "Num 0": "Insert", "Num .": "Del"}
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
        self.enabled = False
        self._state_lock = threading.RLock()
        self._lifecycle_lock = threading.RLock()
        self.last_pump_at = 0.0
        self.last_sample_at = 0.0
        self._last_maintenance = 0.0
        self._last_registration_check = 0.0
        self._wake_sent_at = 0.0
        self.repairs = 0
        self.restarts = 0
        self.wakes = 0
        self.input_errors = 0
        self._last_packet_error = 0.0
        self._raw_at = {}
        self._sampled_down = set()
        self._fallback_at = {}
        self.raw_presses = 0
        self.fallback_presses = 0
        self.last_press_at = 0.0
        self._poll_keys = tuple((vk, name) for vk, name in names.items()
                                if vk not in (0x10, 0x11, 0x12))
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
        u.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
        u.SetTimer.restype = ctypes.c_size_t
        u.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
        u.GetAsyncKeyState.argtypes = [ctypes.c_int]
        u.GetAsyncKeyState.restype = ctypes.c_short
        u.GetRegisteredRawInputDevices.argtypes = [ctypes.POINTER(_RawDevice),
                                                  ctypes.POINTER(wintypes.UINT), wintypes.UINT]
        u.GetRegisteredRawInputDevices.restype = wintypes.UINT
        self.kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self.kernel32.GetModuleHandleW.restype = wintypes.HMODULE

    @property
    def running(self):
        return bool(self.thread and self.thread.is_alive() and self.hwnd and not self.stopping.is_set())

    def start(self):
        with self._lifecycle_lock:
            self.enabled = True
            self._start_receiver()

    def _start_receiver(self):
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
            self._stop_receiver()
            raise OSError("Keyboard input initialization timed out")
        if self.error:
            raise OSError("Keyboard input unavailable") from self.error

    def stop(self):
        with self._lifecycle_lock:
            self.enabled = False
            self._stop_receiver()

    def _stop_receiver(self):
        self.stopping.set()
        if self.hwnd:
            self.user32.PostMessageW(self.hwnd, 0x0010, 0, 0)
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=.25)

    def maintain(self, now=None):
        """Called by the lighting worker, even when the UI is hidden/stalled."""
        now = time.perf_counter() if now is None else now
        if not self.enabled:
            return
        # A stuck native message queue must not stop both input paths. The
        # shared state lock merges this backup sample with the native timer.
        if now - self.last_sample_at > .05:
            self._sample_keys()
        if now - self._last_maintenance < 1:
            return
        with self._lifecycle_lock:
            if not self.enabled:
                return
            self._last_maintenance = now
            if self.running and now - self.last_pump_at < 2:
                self._wake_sent_at = 0.0
                return
            if self.thread and self.thread.is_alive():
                if not self._wake_sent_at:
                    self._wake_sent_at = now
                    self.user32.PostMessageW(self.hwnd, WM_INPUT_WAKE, 0, 0)
                    LOG.warning("Keyboard message heartbeat stale; requesting receiver wake")
                    return
                if now - self._wake_sent_at < 2:
                    return
                self._stop_receiver()
                if self.thread.is_alive():
                    self._wake_sent_at = now
                    LOG.warning("Keyboard receiver did not stop; retaining backup sampling without duplicate receiver")
                    return
            self.restarts += 1
            self._wake_sent_at = 0.0
            LOG.warning("Restarting keyboard receiver from lighting worker")
            self._start_receiver()

    def _registration_matches(self):
        count = wintypes.UINT()
        u = self.user32
        size = ctypes.sizeof(_RawDevice)
        u.GetRegisteredRawInputDevices(None, ctypes.byref(count), size)
        if not count.value:
            return False
        devices = (_RawDevice * count.value)()
        result = u.GetRegisteredRawInputDevices(devices, ctypes.byref(count), size)
        if result == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        return any(d.page == 1 and d.usage == 6 and d.target == self.hwnd and
                   d.flags & 0x100 and not d.flags & 0x30 for d in devices[:result])

    def _maintain_registration(self, force=False):
        now = time.perf_counter()
        if not force and now - self._last_registration_check < 5:
            return
        self._last_registration_check = now
        if self._registration_matches():
            return
        device = _RawDevice(1, 6, 0x100 | 0x2000, self.hwnd)
        if not self.user32.RegisterRawInputDevices(ctypes.byref(device), 1, ctypes.sizeof(device)):
            raise ctypes.WinError(ctypes.get_last_error())
        self.repairs += 1
        LOG.warning("Restored missing background keyboard registration")

    def _pulse(self):
        now = time.perf_counter()
        if self.last_pump_at and now - self.last_pump_at > 2:
            with self._state_lock:
                self.held.clear()
                self._raw_at.clear()
                self._sampled_down.clear()
                self._fallback_at.clear()
        self.last_pump_at = now

    def feed(self, device, vk, scan, flags):
        with self._state_lock:
            self._feed_locked(device, vk, scan, flags)

    def _feed_locked(self, device, vk, scan, flags):
        if self.stopping.is_set():
            return
        name = key_name(vk, scan, flags, self.names)
        if name is None:
            return
        key = (device, name)
        alias = POLL_ALIASES.get(name, name)
        if flags & 1:
            self.held.discard(key)
            self._raw_at.pop(key, None)
            self._sampled_down.discard(name)
            self._fallback_at.pop(name, None)
            if alias != name:
                self._sampled_down.discard(alias)
                self._fallback_at.pop(alias, None)
        elif key not in self.held:
            now = time.perf_counter()
            self.held.add(key)
            self._raw_at[key] = now
            self.raw_presses += 1
            # Raw packets and the sampler can describe the same transition in
            # either order. Preserve raw per-device presses, but never draw a
            # second wave for one already supplied by the sampler.
            fallback_at = self._fallback_at.pop(name, None)
            if fallback_at is None and alias != name:
                fallback_at = self._fallback_at.pop(alias, None)
            if fallback_at is None or (name not in self._sampled_down and alias not in self._sampled_down and now - fallback_at > .06):
                self._emit(name, now)
            # Pause often has no break packet. Do not latch it forever.
            if name == "Pause":
                self.held.discard(key)
                self._raw_at.pop(key, None)

    def _emit(self, name, now):
        self.last_press_at = now
        self.on_press(name, now)

    def _sample_keys(self):
        with self._state_lock:
            self._sample_keys_locked()

    def _sample_keys_locked(self):
        if self.stopping.is_set() and not self.enabled:
            return
        now = time.perf_counter()
        self.last_sample_at = now
        # Use only the current-down high bit. The low "pressed since" bit is
        # shared with other applications and is not a reliable event source.
        down = {name for vk, name in self._poll_keys
                if self.user32.GetAsyncKeyState(vk) & 0x8000}
        raw_down = {name for _device, name in self.held}
        for name, alias in POLL_ALIASES.items():
            if name in raw_down and alias in down:
                down.remove(alias)
                down.add(name)
        for name in down - self._sampled_down - raw_down:
            self.fallback_presses += 1
            self._fallback_at[name] = now
            self._emit(name, now)
        self._sampled_down = down
        # A foreground switch can lose a break packet. Recover stale latches
        # after a grace period; never repeatedly light a genuinely held key.
        for key in tuple(self.held):
            if key[1] not in down and now - self._raw_at.get(key, now) > .10:
                self.held.discard(key)
                self._raw_at.pop(key, None)

    def diagnostics(self):
        now = time.perf_counter()
        age = now - self.last_press_at if self.last_press_at else -1
        pump = now - self.last_pump_at if self.last_pump_at else -1
        sample = now - self.last_sample_at if self.last_sample_at else -1
        return (f"raw={self.raw_presses},fallback={self.fallback_presses},last={age:.1f}s,"
                f"pump={pump:.2f}s,sample={sample:.2f}s,repairs={self.repairs},"
                f"restarts={self.restarts},wakes={self.wakes},errors={self.input_errors}")

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
                with self._state_lock:
                    self.held = {key for key in self.held if key[0] != lparam}
                    self._raw_at = {key: at for key, at in self._raw_at.items() if key[0] != lparam}
            elif message == 0x0113 and wparam == 1:  # WM_TIMER on the receiver thread.
                self._pulse()
                self._sample_keys()
                self._maintain_registration()
                return 0
            elif message == WM_INPUT_WAKE:
                self.wakes += 1
                self._pulse()
                if not self.user32.SetTimer(hwnd, 1, 15, None):
                    raise ctypes.WinError(ctypes.get_last_error())
                self._maintain_registration(force=True)
                return 0
            elif message == 0x0010:
                self.user32.DestroyWindow(hwnd)
                return 0
            elif message == 0x0002:
                self.user32.PostQuitMessage(0)
                return 0
        except Exception:
            self.input_errors += 1
            now = time.perf_counter()
            if now - self._last_packet_error > 5:
                self._last_packet_error = now
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
            if not self.user32.SetTimer(self.hwnd, 1, 15, None):
                raise ctypes.WinError(ctypes.get_last_error())
            self._pulse()
            self._last_registration_check = time.perf_counter()
            self.ready.set()
            LOG.info("Background keyboard input registered: raw + key-state fallback on dedicated thread")
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
                self.user32.KillTimer(self.hwnd, 1)
                device = _RawDevice(1, 6, 1, None)
                try:
                    if self._registration_matches():
                        self.user32.RegisterRawInputDevices(ctypes.byref(device), 1, ctypes.sizeof(device))
                except OSError:
                    LOG.exception("Keyboard registration cleanup could not be checked")
                self.user32.DestroyWindow(self.hwnd)
            self.hwnd = None
            with self._state_lock:
                self.held.clear()
                self._raw_at.clear()
                self._sampled_down.clear()
                self._fallback_at.clear()
            if registered:
                self.user32.UnregisterClassW(class_name, instance)
            self.ready.set()
