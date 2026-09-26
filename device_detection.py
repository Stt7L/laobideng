"""Read connected HID keyboard identities without opening their lighting interface."""

import ctypes
import re
from ctypes import wintypes

from backend import (GUID, SP_DEVICE_INTERFACE_DATA, HIDD_ATTRIBUTES, HIDP_CAPS,
                     bluetooth_keyboard_present, hid, kernel32, setupapi)


KNOWN_MODELS = {
    (0x320F, 0x5055): ("VGN V98 Pro", "USB 有线"),
    (0x320F, 0x5088): ("VGN V98 Pro", "2.4G 接收器"),
}
GENERIC_NAMES = {
    "hid keyboard device", "usb keyboard", "usb input device", "keyboard",
    "2.4g wireless keyboard", "wireless gaming keyboard", "usb gaming keyboard",
    "bluetooth keyboard", "wireless keyboard", "standard keyboard", "gaming keyboard",
    "标准键盘", "hid 键盘设备", "键盘",
}
NON_KEYBOARD_MARKERS = ("mouse", "multitouch", "virtual", "alienware 610m")

for function in (hid.HidD_GetProductString, hid.HidD_GetManufacturerString):
    function.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
    function.restype = wintypes.BOOL


def _hid_string(function, handle):
    buffer = ctypes.create_unicode_buffer(128)
    if function(handle, buffer, ctypes.sizeof(buffer)):
        return re.sub(r"\s+", " ", buffer.value).strip()
    return ""


def _model_name(vid, pid, product, manufacturer):
    known = KNOWN_MODELS.get((vid, pid))
    if known:
        return known[0]
    if product and product.casefold() not in GENERIC_NAMES:
        if manufacturer and manufacturer.casefold() not in GENERIC_NAMES \
                and manufacturer.casefold() not in product.casefold():
            return f"{manufacturer} {product}"
        return product
    return ""


def detect_keyboards():
    """Return unique connected keyboard identities, strongest model evidence first."""
    guid = GUID()
    hid.HidD_GetHidGuid(ctypes.byref(guid))
    info = setupapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None, 0x12)
    if info == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    found = {}
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
                    info, ctypes.byref(item), detail, needed.value,
                    ctypes.byref(needed), None):
                continue
            path = ctypes.wstring_at(ctypes.addressof(detail) + 4)
            handle = kernel32.CreateFileW(path, 0, 3, None, 3, 0, None)
            if handle == wintypes.HANDLE(-1).value:
                continue
            try:
                attrs = HIDD_ATTRIBUTES()
                attrs.Size = ctypes.sizeof(attrs)
                if not hid.HidD_GetAttributes(handle, ctypes.byref(attrs)):
                    continue
                identity = (attrs.VendorID, attrs.ProductID)
                preparsed = ctypes.c_void_p()
                keyboard_collection = False
                if hid.HidD_GetPreparsedData(handle, ctypes.byref(preparsed)):
                    try:
                        caps = HIDP_CAPS()
                        keyboard_collection = (
                            hid.HidP_GetCaps(preparsed, ctypes.byref(caps)) == 0x110000
                            and caps.UsagePage == 1 and caps.Usage == 6)
                    finally:
                        hid.HidD_FreePreparsedData(preparsed)
                if not keyboard_collection and identity not in KNOWN_MODELS:
                    continue
                product = _hid_string(hid.HidD_GetProductString, handle)
                manufacturer = _hid_string(hid.HidD_GetManufacturerString, handle)
                if identity not in KNOWN_MODELS and any(
                        marker in product.casefold() for marker in NON_KEYBOARD_MARKERS):
                    continue
                model = _model_name(*identity, product, manufacturer)
                previous = found.get(identity)
                if previous and (bool(previous["model"]), len(previous["product"])) >= (
                        bool(model), len(product)):
                    continue
                transport = KNOWN_MODELS.get(identity, (None, "蓝牙" if "bth" in path.lower()
                                              else "USB / 2.4G"))[1]
                found[identity] = {
                    "model": model,
                    "vid": f"{identity[0]:04X}",
                    "pid": f"{identity[1]:04X}",
                    "transport": transport,
                    "product": product,
                    "manufacturer": manufacturer,
                    "known": identity in KNOWN_MODELS,
                }
            finally:
                kernel32.CloseHandle(handle)
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(info)
    return sorted(found.values(), key=lambda device: (
        not device["known"], device["model"].casefold(), device["transport"] != "USB 有线",
        device["vid"], device["pid"]))


def preferred_known_keyboard(devices, preference="auto"):
    """Select a known lighting adapter; leave ambiguous unknown models to the user."""
    known = [device for device in devices if device["known"]]
    if not known:
        return None
    if preference == "wired" or (preference == "auto" and bluetooth_keyboard_present()):
        preferred = "USB 有线"
    else:
        preferred = "2.4G 接收器"
    return next((device for device in known if device["transport"] == preferred), known[0])
