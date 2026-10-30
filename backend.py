import ctypes
import json
import logging
import math
import queue
import threading
import time
from ctypes import wintypes
from pathlib import Path

from effects import EFFECT_IDS, MUSIC, MOVING_MUSIC, REACTIVE, render, ripple_lifetime, reactive_lifetime
from audio_spectrum import AudioSpectrum
from keyboard_input import KeyboardInput
from layout import NAME_CENTERS, NAME_LEDS

LOG = logging.getLogger("vgn-ripple")

VID = 0x320F
WIRED_PID = 0x5055
WIRELESS_PID = 0x5088
COLORS_PER_PACKET = 56
PACKET_COUNT = 7
REPORT_SIZE = 64
WIRELESS_PACKET_DELAY = 0.012
ROOT = Path(__file__).resolve().parent
with (ROOT / "keyboard_map.json").open("r", encoding="utf-8") as stream:
    MAP = json.load(stream)
MAX_LED = max(MAP["leds"]) + 1
VALID_LEDS = set(MAP["leds"]) | {59}

class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("Flags", wintypes.DWORD),
                ("InterfaceClassGuid", GUID), ("Reserved", ctypes.c_size_t)]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Size", wintypes.ULONG), ("VendorID", wintypes.USHORT),
                ("ProductID", wintypes.USHORT), ("VersionNumber", wintypes.USHORT)]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [("Usage", wintypes.USHORT), ("UsagePage", wintypes.USHORT),
                ("InputReportByteLength", wintypes.USHORT),
                ("OutputReportByteLength", wintypes.USHORT),
                ("FeatureReportByteLength", wintypes.USHORT),
                ("Reserved", wintypes.USHORT * 17),
                ("NumberLinkCollectionNodes", wintypes.USHORT),
                ("NumberInputButtonCaps", wintypes.USHORT),
                ("NumberInputValueCaps", wintypes.USHORT),
                ("NumberInputDataIndices", wintypes.USHORT),
                ("NumberOutputButtonCaps", wintypes.USHORT),
                ("NumberOutputValueCaps", wintypes.USHORT),
                ("NumberOutputDataIndices", wintypes.USHORT),
                ("NumberFeatureButtonCaps", wintypes.USHORT),
                ("NumberFeatureValueCaps", wintypes.USHORT),
                ("NumberFeatureDataIndices", wintypes.USHORT)]


setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
hid = ctypes.WinDLL("hid", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(GUID)]
setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                                 ctypes.POINTER(GUID), wintypes.DWORD,
                                                 ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [ctypes.c_void_p,
                                                       ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
                                                       ctypes.c_void_p, wintypes.DWORD,
                                                       ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
hid.HidD_GetAttributes.argtypes = [wintypes.HANDLE, ctypes.POINTER(HIDD_ATTRIBUTES)]
hid.HidD_GetPreparsedData.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
hid.HidP_GetCaps.restype = ctypes.c_long
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.HANDLE]
kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                               ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]


def bluetooth_keyboard_present():
    """True only while the paired V98 Pro exposes an active Bluetooth HID keyboard."""
    guid = GUID()
    hid.HidD_GetHidGuid(ctypes.byref(guid))
    info = setupapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None, 0x12)
    if info == ctypes.c_void_p(-1).value:
        return False
    try:
        index = 0
        while True:
            item = SP_DEVICE_INTERFACE_DATA()
            item.cbSize = ctypes.sizeof(item)
            if not setupapi.SetupDiEnumDeviceInterfaces(
                    info, None, ctypes.byref(guid), index, ctypes.byref(item)):
                break
            index += 1
            needed = wintypes.DWORD()
            setupapi.SetupDiGetDeviceInterfaceDetailW(
                info, ctypes.byref(item), None, 0, ctypes.byref(needed), None)
            if not needed.value:
                continue
            detail = ctypes.create_string_buffer(needed.value)
            ctypes.cast(detail, ctypes.POINTER(wintypes.DWORD))[0] = (
                8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6)
            if not setupapi.SetupDiGetDeviceInterfaceDetailW(
                    info, ctypes.byref(item), detail, needed,
                    ctypes.byref(needed), None):
                continue
            path = ctypes.wstring_at(ctypes.addressof(detail) + 4).lower()
            if "dev_vid&02245a_pid&8276" in path and "&col01#" in path:
                return True
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(info)
    return False


def find_keyboard_output(preference="auto"):
    guid = GUID()
    hid.HidD_GetHidGuid(ctypes.byref(guid))
    info = setupapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None, 0x12)
    if info == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    candidates = []
    try:
        index = 0
        while True:
            item = SP_DEVICE_INTERFACE_DATA()
            item.cbSize = ctypes.sizeof(item)
            if not setupapi.SetupDiEnumDeviceInterfaces(info, None, ctypes.byref(guid),
                                                        index, ctypes.byref(item)):
                break
            index += 1
            needed = wintypes.DWORD()
            setupapi.SetupDiGetDeviceInterfaceDetailW(info, ctypes.byref(item), None, 0,
                                                       ctypes.byref(needed), None)
            if not needed.value:
                continue
            detail = ctypes.create_string_buffer(needed.value)
            ctypes.cast(detail, ctypes.POINTER(wintypes.DWORD))[0] = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            if not setupapi.SetupDiGetDeviceInterfaceDetailW(info, ctypes.byref(item), detail,
                                                              needed, ctypes.byref(needed), None):
                continue
            path = ctypes.wstring_at(ctypes.addressof(detail) + 4)
            handle = kernel32.CreateFileW(path, 0x80000000 | 0x40000000, 3, None, 3, 0x80, None)
            if handle == wintypes.HANDLE(-1).value:
                continue
            keep_handle = False
            try:
                attrs = HIDD_ATTRIBUTES()
                attrs.Size = ctypes.sizeof(attrs)
                if not hid.HidD_GetAttributes(handle, ctypes.byref(attrs)):
                    continue
                if attrs.VendorID != VID or attrs.ProductID not in (WIRED_PID, WIRELESS_PID):
                    continue
                preparsed = ctypes.c_void_p()
                if not hid.HidD_GetPreparsedData(handle, ctypes.byref(preparsed)):
                    continue
                try:
                    caps = HIDP_CAPS()
                    status = hid.HidP_GetCaps(preparsed, ctypes.byref(caps))
                finally:
                    hid.HidD_FreePreparsedData(preparsed)
                # This is the VGN lighting collection used by the public protocol.
                if (status == 0x110000 and caps.UsagePage == 0xFF1C and
                        caps.Usage == 0x0092 and caps.OutputReportByteLength == REPORT_SIZE):
                    keep_handle = True
                    candidates.append((path, handle, caps.OutputReportByteLength,
                                       "wired" if attrs.ProductID == WIRED_PID else "wireless"))
            finally:
                if not keep_handle:
                    kernel32.CloseHandle(handle)
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(info)
    requested = preference if preference in ("wired", "wireless") else None
    selected = next((item for item in candidates if item[3] == requested), None)
    if selected is None and requested is None:
        selected = next((item for item in candidates if item[3] == "wireless"), None)
        selected = selected or next((item for item in candidates if item[3] == "wired"), None)
    bluetooth_active = bool(selected and selected[3] == "wireless" and
                            bluetooth_keyboard_present())
    if bluetooth_active:
        selected = (next((item for item in candidates if item[3] == "wired"), None)
                    if requested is None else None)
    for item in candidates:
        if item is not selected:
            kernel32.CloseHandle(item[1])
    if selected:
        return selected
    if bluetooth_active:
        raise RuntimeError("键盘当前通过蓝牙连接；逐键灯效需要切到 USB 有线或 2.4G。")
    raise RuntimeError("未发现 V98 Pro 灯控接口（USB 有线 5055 / 2.4G 接收器 5088）。")


def make_key_map():
    names = MAP["names"]
    coords = MAP["positions"]
    leds = MAP["leds"]
    first = {}
    # The published V98Pro name list contains one extra "UnderGlow2" entry.
    # Its LED list and physical position list omit that entry.
    extra_name = names.index("UnderGlow2")
    for i, led in enumerate(leds):
        name = names[i + (i >= extra_name)]
        if name not in first:
            x, y = coords[i]
            first[name] = (led, x, y)
    for name, (x, y) in NAME_CENTERS.items():
        if name in NAME_LEDS:
            first[name] = (NAME_LEDS[name], x, y)
        else:
            first.pop(name, None)
    return first


KEYS = make_key_map()
VK_NAMES = {}


def bind(vk, name):
    VK_NAMES[vk] = name


bind(0x1B, "Esc")
for i in range(12):
    bind(0x70 + i, f"F{i + 1}")
for i, c in enumerate("1234567890"):
    bind(ord(c), c)
for i, c in enumerate("QWERTYUIOP"):
    bind(ord(c), c)
for i, c in enumerate("ASDFGHJKL"):
    bind(ord(c), c)
for i, c in enumerate("ZXCVBNM"):
    bind(ord(c), c)
for vk, name in {
    0xC0: "`", 0xBD: "-_", 0xBB: "=+", 0x08: "Backspace", 0x09: "Tab",
    0xDB: "[", 0xDD: "]", 0xDC: "\\", 0x14: "CapsLock", 0xBA: ";",
    0xDE: "'", 0x0D: "Enter", 0xA0: "Left Shift", 0xA1: "Right Shift",
    0xBC: ",", 0xBE: ".", 0xBF: "/", 0xA2: "Left Ctrl", 0x5B: "Left Win",
    0xA4: "Left Alt", 0xA5: "Right Alt", 0x20: "Space",
    0xA3: "Right Ctrl", 0x5C: "Right Win",
    0x25: "Left Arrow", 0x26: "Up Arrow", 0x27: "Right Arrow", 0x28: "Down Arrow",
    0x2E: "Del", 0x2D: "Insert", 0x21: "Page Up", 0x22: "Page Down",
    0x24: "Home", 0x23: "End", 0x2C: "Print Screen",
    0x91: "Scroll Lock", 0x13: "Pause",
    0x90: "NumLock", 0x6F: "Num /", 0x6A: "Num *", 0x6D: "Num -",
    0x6B: "Num +", 0x6E: "Num .", 0x0C: "Num 5",
}.items():
    bind(vk, name)
for i in range(10):
    bind(0x60 + i, f"Num {i}")


def rgb_packet(frame):
    data = []
    for led, color in enumerate(frame):
        data.extend(color if led in VALID_LEDS else (0, 0, 0))
    data.extend([0] * 24)
    packets = []
    for index in range(PACKET_COUNT):
        chunk = data[index * COLORS_PER_PACKET:(index + 1) * COLORS_PER_PACKET]
        if len(chunk) < COLORS_PER_PACKET:
            chunk.extend([0] * (COLORS_PER_PACKET - len(chunk)))
        base = ((index - 5) * COLORS_PER_PACKET + 0x63) if index >= 5 else (index * COLORS_PER_PACKET + 0x4A)
        check = (sum(chunk) + base) & 0xFFFF
        packet = [0x04, check & 0xFF, (check >> 8) & 0xFF, 0x12,
                  0x30 if index == 6 else 0x38,
                  (index * COLORS_PER_PACKET) & 0xFF,
                  (index * COLORS_PER_PACKET) >> 8, 0x00] + chunk
        packet = (packet + [0] * REPORT_SIZE)[:REPORT_SIZE]
        packets.append(bytes(packet))
    return packets


def wireless_packet(frame):
    """2.4G receiver protocol for VID 320F / PID 5088."""
    data = []
    for led, color in enumerate(frame):
        data.extend(color if led in VALID_LEDS else (0, 0, 0))
    data.extend([0] * 24)
    packets = []
    for index in range(16):
        chunk = data[index * 24:(index + 1) * 24]
        chunk += [0] * (24 - len(chunk))
        base = ((index - 11) * 24 + 0x33) if index >= 11 else (index * 24 + 0x2A)
        check = (sum(chunk) + base) & 0xFFFF
        packet = [0x04, check & 0xFF, check >> 8, 0x12, 0x18,
                  (index * 24) & 0xFF, (index * 24) >> 8, 0x00] + chunk
        packets.append(bytes((packet + [0] * REPORT_SIZE)[:REPORT_SIZE]))
    return packets


class LightingController:
    """UI configuration with an independent renderer and HID streaming thread."""

    def __init__(self):
        self.handle = None
        self.hook = None
        self.events = queue.Queue(maxsize=1024)
        self.keyboard_input = KeyboardInput(VK_NAMES, self._key_pressed)
        self._last_input_retry = 0.0
        self.ripples = []
        self.audio_meter = AudioSpectrum()
        self.audio_level = 0.0
        self.audio_beats = []
        self.audio_trace = []
        self.audio_trace_baseline = None
        self.audio_trace_value = 0.0
        self.audio_last_beat = 0.0
        self.audio_seen_beat = 0
        self.music_frame = None
        self.music_frame_at = 0.0
        self.down_keys = set()
        self.transport = None
        self.preference = "auto"
        self.preview_events = False
        self.effect = "ripple"
        self.worker = None
        self.worker_stop = threading.Event()
        self.worker_lock = threading.Lock()
        self.worker_frame = None
        self.worker_displayed_frame = None
        self.worker_pending_events = []
        self.worker_error = None
        self._stream_session = None
        self._last_stream_write = 0.0
        self._stream_frame_count = 0
        self._audio_refresh = threading.Event()
        self.base = (255, 255, 255)
        self.accent = (0, 0, 0)
        self.brightness = 0.65
        self.base_brightness = 1.0
        self.accent_brightness = 1.0
        self.global_color = (255, 255, 255)
        self.ecg_background = (255, 255, 255)
        self.speed = 1.0
        self.ripple_width = 1.0
        self.custom_heart_keys = set()
        self.custom_canvas_keys = set()
        self.ripples_enabled = True
        self.last_frame = [self.base_color()] * MAX_LED

    @property
    def connected(self):
        return self.handle is not None

    def connect(self):
        if self.connected:
            return
        _, handle, report_length, transport = find_keyboard_output(self.preference)
        if report_length and report_length != REPORT_SIZE:
            kernel32.CloseHandle(handle)
            raise RuntimeError(f"键盘报告长度为 {report_length} 字节，与已知灯光格式不符。")
        self.handle = handle
        self.transport = transport
        try:
            if transport == "wired":
                self._write_report(bytes([0x04, 0x8C, 0x00, 0x0B, 0x30, 0x50, 0x01]
                                         + [0] * 57))
            self.worker_error = None
            self.worker_stop = threading.Event()
            self.worker_displayed_frame = None
            self._last_stream_write = 0.0
            self._stream_frame_count = 0
            self._stream_session = {"reset": None}
            self.worker = threading.Thread(
                target=self._stream_loop,
                args=(self.worker_stop, handle, transport, self._stream_session),
                name=f"Lighting-stream-{transport}", daemon=True)
            self.worker.start()
            if self.ripples_enabled and self.effect in REACTIVE:
                self._install_hook()
        except Exception:
            self.disconnect()
            raise

    def disconnect(self):
        self._remove_hook()
        if self.worker is not None:
            self.worker_stop.set()
            self.worker.join(timeout=0.5)
            # The writer owns its captured HANDLE until it has stopped. Never
            # close/reuse it underneath a delayed WriteFile or a reconnect.
            self.worker = None
        elif self.handle is not None:
            kernel32.CloseHandle(self.handle)
        self.handle = None
        self.transport = None
        self.worker_displayed_frame = None
        self.worker_pending_events.clear()
        self.ripples.clear()
        self.down_keys.clear()

    def close(self):
        had_worker = self.worker is not None
        if self.worker is not None:
            self._stream_session["reset"] = [self.base_color()] * MAX_LED
        elif self.connected:
            try:
                self.write_frame([self.base_color()] * MAX_LED)
            except OSError:
                pass
        self.disconnect()
        # A running stream owns Core Audio's COM objects. Its finally block
        # releases them on that same thread, even after a bounded join.
        if not had_worker and self._stream_session is None:
            self.audio_meter.close()

    def set_active(self, active):
        if active and (self.connected or self.preview_events) and self.effect in REACTIVE:
            self._install_hook()
        else:
            self._remove_hook()
        self.ripples_enabled = active
        self.ripples.clear()
        self.audio_beats.clear()
        self.audio_trace.clear()
        self.audio_trace_baseline = None
        self.audio_trace_value = 0.0
        self.audio_seen_beat = self.audio_meter.beat_serial
        self.music_frame = None
        if not active and self.worker is None:
            self.audio_meter.close()
            self.audio_level = 0.0
        self.down_keys.clear()
        with self.worker_lock:
            self.worker_pending_events.clear()

    def set_effect(self, effect):
        if effect not in EFFECT_IDS:
            raise ValueError(effect)
        self.effect = effect
        self.ripples.clear()
        self.audio_beats.clear()
        self.audio_trace.clear()
        self.audio_trace_baseline = None
        self.audio_trace_value = 0.0
        self.audio_seen_beat = self.audio_meter.beat_serial
        self.music_frame = None
        if effect not in MUSIC and self.worker is None:
            self.audio_meter.close()
            self.audio_level = 0.0
        with self.worker_lock:
            self.worker_pending_events.clear()
        if (self.connected or self.preview_events) and self.ripples_enabled and effect in REACTIVE:
            self._install_hook()
        elif effect not in REACTIVE:
            self._remove_hook()

    def base_color(self):
        level = max(0.0, min(1.0, self.brightness * self.base_brightness))
        return tuple(round(channel * level) for channel in self.base)

    def _write_report(self, packet, handle=None):
        target = self.handle if handle is None else handle
        if target is None:
            return
        sent = wintypes.DWORD()
        buffer = ctypes.create_string_buffer(packet, len(packet))
        if not kernel32.WriteFile(target, buffer, len(packet),
                                  ctypes.byref(sent), None) or sent.value != len(packet):
            raise ctypes.WinError(ctypes.get_last_error())

    def write_frame(self, frame):
        if self.handle is None:
            return
        if self.worker is not None:
            # Connected streams render their own frames. UI refreshes never
            # send reports or replace an in-flight frame.
            return
        for packet in rgb_packet(frame):
            self._write_report(packet)

    def preview_frame(self):
        return self.worker_displayed_frame or self.last_frame

    @property
    def stream_healthy(self):
        return bool(self.worker and self.worker.is_alive() and not self.worker_error and
                    time.perf_counter() - self._last_stream_write < 2.0)

    def refresh_audio(self):
        if self._stream_session is not None:
            self._audio_refresh.set()
        else:
            self.audio_meter.refresh()

    def _stream_config(self):
        # Each field is an immutable value or a copied set. The worker keeps
        # all animation histories private; UI setters never clear its buffers.
        names = ("effect", "ripples_enabled", "base", "accent", "brightness",
                 "base_brightness", "accent_brightness", "ecg_background",
                 "speed", "ripple_width")
        config = {name: getattr(self, name) for name in names}
        config["custom_heart_keys"] = frozenset(self.custom_heart_keys)
        config["custom_canvas_keys"] = frozenset(self.custom_canvas_keys)
        return config

    def _stream_packets(self, frame, handle, transport, stop=None):
        packets = wireless_packet(frame) if transport == "wireless" else rgb_packet(frame)
        for packet in packets:
            if stop is not None and stop.is_set():
                return False
            self._write_report(packet, handle)
            if transport == "wireless":
                time.sleep(WIRELESS_PACKET_DELAY)
        return True

    def _stream_loop(self, stop, handle, transport, session):
        renderer = None
        failed = False
        try:
            # Construct and use audio on this thread; fallback Core Audio
            # pointers must never migrate between COM apartments.
            renderer = LightingController()
            if self.worker_stop is stop:
                self.audio_meter = renderer.audio_meter
            LOG.info("Independent lighting stream started: %s", transport)
            deadline = time.perf_counter()
            while not stop.is_set():
                config = self._stream_config()
                if config["effect"] != renderer.effect:
                    renderer.set_effect(config["effect"])
                if config["ripples_enabled"] != renderer.ripples_enabled:
                    renderer.set_active(config["ripples_enabled"])
                for name, value in config.items():
                    setattr(renderer, name, value)
                if self._audio_refresh.is_set():
                    self._audio_refresh.clear()
                    renderer.audio_meter.refresh()
                now = time.perf_counter()
                try:
                    while True:
                        name, started = self.events.get_nowait()
                        renderer.events.put_nowait((name, now if transport == "wireless" else started))
                except queue.Empty:
                    pass
                renderer.tick(now)
                frame = renderer.last_frame
                if not self._stream_packets(frame, handle, transport, stop):
                    break
                if self.worker_stop is stop:
                    self.last_frame = frame
                    self.worker_displayed_frame = frame
                    self.audio_level = renderer.audio_level
                    self._last_stream_write = time.perf_counter()
                    self._stream_frame_count += 1
                interval = .02 if config["effect"] in MUSIC and transport == "wired" else .033
                deadline += interval
                remaining = deadline - time.perf_counter()
                if remaining > 0:
                    stop.wait(remaining)
                else:
                    # Never burst stale frames after a slow send or a pause.
                    deadline = time.perf_counter()
        except Exception as error:
            failed = True
            if self.worker_stop is stop and not stop.is_set():
                self.worker_error = error if isinstance(error, OSError) else OSError(str(error))
                LOG.exception("Independent lighting stream interrupted")
        finally:
            try:
                if session["reset"] is not None and not failed:
                    self._stream_packets(session["reset"], handle, transport)
            except OSError:
                pass
            try:
                if renderer is not None:
                    renderer.audio_meter.close()
            except Exception:
                LOG.exception("Lighting stream audio cleanup failed")
            finally:
                kernel32.CloseHandle(handle)

    def tick(self, now=None):
        if self.connected and self.worker_error:
            error = self.worker_error
            self.disconnect()
            raise error
        now = now if now is not None else time.perf_counter()
        if (self.ripples_enabled and self.effect in REACTIVE and
                (self.connected or self.preview_events) and
                not self.keyboard_input.running and now - self._last_input_retry > 2):
            self._last_input_retry = now
            try:
                self._install_hook()
            except OSError as error:
                LOG.warning("Background keyboard input retry failed: %s", error)
        if self.worker is not None:
            return  # UI timer reads snapshots; hardware rendering is independent.
        if self.ripples_enabled and self.effect in MUSIC:
            self.audio_level = self.audio_meter.sample()
            if self.audio_meter.mode == "spectrum":
                if self.audio_meter.beat_serial != self.audio_seen_beat:
                    self.audio_beats.append(self.audio_meter.beat_time)
                    self.audio_seen_beat = self.audio_meter.beat_serial
            elif (self.audio_meter.instant > 0.16 and
                  self.audio_meter.impact > 0.16 and
                  self.audio_meter.rise > 0.045 and
                  now - self.audio_last_beat > 0.22):
                self.audio_beats.append(now)
                self.audio_last_beat = now
            trace_lifetime = max(2.2, 2.2 / max(0.45, self.speed))
            beat_lifetime = (trace_lifetime if self.effect in {"audio_ecg", "custom_ecg"}
                             else 1.6)
            self.audio_beats = [started for started in self.audio_beats
                                if now - started < beat_lifetime][-24:]
            if self.effect in {"audio_ecg", "custom_ecg"}:
                bass, middle, treble = self.audio_meter.bands
                raw = (self.audio_level * 0.35 + bass * 0.40 +
                       middle * 0.20 + treble * 0.05)
                if self.audio_trace_baseline is None:
                    self.audio_trace_baseline = raw
                else:
                    rate = 0.055 if raw > self.audio_trace_baseline else 0.15
                    self.audio_trace_baseline += (raw - self.audio_trace_baseline) * rate
                target = max(-0.65, min(0.65,
                                        (raw - self.audio_trace_baseline) * 3.3))
                response = 0.24 if target > self.audio_trace_value else 0.38
                self.audio_trace_value += (target - self.audio_trace_value) * response
                self.audio_trace.append((now, self.audio_trace_value))
                self.audio_trace = [point for point in self.audio_trace
                                    if now - point[0] < trace_lifetime][-800:]
        elif self.audio_meter.available:
            self.audio_meter.close()
            self.audio_level = 0.0
        try:
            while True:
                name, started = self.events.get_nowait()
                if self.ripples_enabled and self.effect in REACTIVE:
                    if self.transport == "wireless":
                        with self.worker_lock:
                            self.worker_pending_events.append(name)
                    else:
                        # Earlier waves finish while new keys are pressed.
                        self.ripples.append((name, started))
                        self.ripples = self.ripples[-64:]
        except queue.Empty:
            pass
        try:
            self.last_frame = self.frame(now)
            self.write_frame(self.last_frame)
        except OSError:
            self.disconnect()
            raise

    def frame(self, now):
        lifetime = (ripple_lifetime(self.speed) if self.effect == "ripple"
                    else reactive_lifetime(self.speed, self.effect))
        self.ripples = [(name, started) for name, started in self.ripples
                        if now - started < lifetime]
        if not self.ripples_enabled:
            return [self.base_color()] * MAX_LED
        target = render(self.effect, now, self.base, self.accent,
                        self.brightness, self.speed, self.ripples,
                        self.ripple_width, self.audio_level, self.audio_beats,
                        self.audio_meter.impact, self.audio_meter.bands,
                        self.audio_trace, self.custom_heart_keys,
                        self.custom_canvas_keys,
                        base_brightness=self.base_brightness,
                        accent_brightness=self.accent_brightness,
                        ecg_background=self.ecg_background)
        # Moving one-key-wide graphics must clear their previous positions in
        # the same frame; the shared music decay otherwise paints a wide trail.
        if self.effect not in MUSIC or self.effect in {"audio_ecg", "custom_ecg"} | MOVING_MUSIC:
            return target
        if self.music_frame is None or len(self.music_frame) != len(target):
            self.music_frame = target
        else:
            elapsed = max(0.0, min(0.25, now - self.music_frame_at))
            on_beat = any(0 <= now - started < 0.18
                          for started in self.audio_beats)
            attack_time = 0.018 if on_beat else 0.09
            rise = 1 - math.exp(-elapsed / attack_time)
            fall = 1 - math.exp(-elapsed / 0.22)
            self.music_frame = [
                tuple(round(old + (new - old) * (rise if new > old else fall))
                      for old, new in zip(previous, desired))
                for previous, desired in zip(self.music_frame, target)
            ]
        self.music_frame_at = now
        return self.music_frame

    def _install_hook(self):
        # Keep the lifecycle entry point for existing UI callers. Raw Input
        # and the key-state fallback share their own non-UI message pump.
        self.keyboard_input.start()
        self.hook = self.keyboard_input.hwnd

    def _key_pressed(self, name, started):
        try:
            self.events.put_nowait((name, started))
        except queue.Full:
            pass  # Never block the input thread behind a stalled render loop.

    def _remove_hook(self):
        self.keyboard_input.stop()
        self.hook = None
        try:
            while True:
                self.events.get_nowait()
        except queue.Empty:
            pass



