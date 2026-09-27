"""Read the peak level of the Windows default playback device via Core Audio."""

import ctypes
import math
import time
import uuid


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, value):
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


CLSID_ENUMERATOR = GUID.parse("BCDE0395-E52F-467C-8E3D-C4579291692E")
IID_ENUMERATOR = GUID.parse("A95664D2-9614-4F35-A746-DE8DB63617E6")
IID_METER = GUID.parse("C02216F6-8C67-4B5B-9D00-D008E73E0064")
ole32 = ctypes.WinDLL("ole32", use_last_error=True)
ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
ole32.CoInitializeEx.restype = ctypes.c_long
ole32.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), ctypes.c_void_p,
                                   ctypes.c_uint32, ctypes.POINTER(GUID),
                                   ctypes.POINTER(ctypes.c_void_p)]
ole32.CoCreateInstance.restype = ctypes.c_long


def _call(pointer, index, restype, argtypes, *args):
    address = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0][index]
    function = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(address)
    result = function(pointer, *args)
    if restype is ctypes.c_long and result < 0:
        raise OSError(f"Core Audio error 0x{result & 0xFFFFFFFF:08X}")
    return result


def _release(pointer):
    if pointer:
        _call(pointer, 2, ctypes.c_ulong, (), )


class AudioMeter:
    def __init__(self):
        self.meter = ctypes.c_void_p()
        self.com_initialized = False
        self.level = 0.0
        self.instant = 0.0
        self.average = 0.0
        self.impact = 0.0
        self.rise = 0.0
        self.error = ""
        self.retry_after = 0.0

    @property
    def available(self):
        return bool(self.meter.value)

    def _open(self):
        hr = ole32.CoInitializeEx(None, 2)
        if hr in (0, 1):
            self.com_initialized = True
        elif hr != -2147417850:  # COM already initialized in another apartment.
            raise OSError(f"COM initialization error 0x{hr & 0xFFFFFFFF:08X}")
        enumerator = ctypes.c_void_p()
        device = ctypes.c_void_p()
        try:
            hr = ole32.CoCreateInstance(ctypes.byref(CLSID_ENUMERATOR), None, 23,
                                        ctypes.byref(IID_ENUMERATOR), ctypes.byref(enumerator))
            if hr < 0:
                raise OSError(f"No Windows audio enumerator: 0x{hr & 0xFFFFFFFF:08X}")
            _call(enumerator, 4, ctypes.c_long,
                  (ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)),
                  0, 1, ctypes.byref(device))
            _call(device, 3, ctypes.c_long,
                  (ctypes.POINTER(GUID), ctypes.c_uint32, ctypes.c_void_p,
                   ctypes.POINTER(ctypes.c_void_p)),
                  ctypes.byref(IID_METER), 23, None, ctypes.byref(self.meter))
            self.error = ""
        finally:
            _release(device)
            _release(enumerator)

    def sample(self):
        now = time.perf_counter()
        if not self.available and now >= self.retry_after:
            try:
                self._open()
            except (OSError, ValueError) as error:
                self.error = str(error)
                self.retry_after = now + 3.0
                self.close()
        if self.available:
            peak = ctypes.c_float()
            try:
                _call(self.meter, 3, ctypes.c_long,
                      (ctypes.POINTER(ctypes.c_float),), ctypes.byref(peak))
                # The endpoint peak is linear. A square-root curve keeps quiet
                # playback visible without making loud playback a solid block.
                target = min(1.0, math.sqrt(max(0.0, peak.value) * 3.6))
                self.rise = max(0.0, target - self.instant)
                self.instant = target
                self.impact = max(0.0, min(1.0, (target - self.average) * 2.4))
                self.average += (target - self.average) * (
                    0.045 if target > self.average else 0.018)
                self.level += (target - self.level) * (
                    0.53 if target > self.level else 0.20)
            except OSError as error:
                self.error = str(error)
                self.retry_after = now + 3.0
                self.close()
        else:
            self.level *= 0.85
            self.instant = 0.0
            self.impact = 0.0
            self.rise = 0.0
        return self.level

    def close(self):
        _release(self.meter)
        self.meter = ctypes.c_void_p()
        if self.com_initialized:
            ole32.CoUninitialize()
            self.com_initialized = False
        self.level = 0.0
        self.instant = 0.0
        self.average = 0.0
        self.impact = 0.0
        self.rise = 0.0
