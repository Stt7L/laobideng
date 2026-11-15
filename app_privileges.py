"""Explicit, one-session Windows elevation; never change login or UAC policy."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys


def is_elevated():
    return bool(ctypes.WinDLL('shell32', use_last_error=True).IsUserAnAdmin())


def elevated_foreground_pid():
    """Read the foreground process's elevation without opening its UI."""
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    hwnd = user.GetForegroundWindow()
    if not hwnd:
        return None
    pid = wintypes.DWORD()
    user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value or pid.value == os.getpid():
        return None

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    process = kernel.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not process:
        return None
    token = wintypes.HANDLE()
    try:
        security = ctypes.WinDLL('advapi32', use_last_error=True)
        security.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                               ctypes.POINTER(wintypes.HANDLE)]
        security.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                  wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        if not security.OpenProcessToken(process, 8, ctypes.byref(token)):  # TOKEN_QUERY
            return None
        elevated = wintypes.DWORD()
        size = wintypes.DWORD()
        if (security.GetTokenInformation(token, 20, ctypes.byref(elevated),
                                         ctypes.sizeof(elevated), ctypes.byref(size))
                and elevated.value):
            return pid.value
        return None
    finally:
        if token:
            kernel.CloseHandle(token)
        kernel.CloseHandle(process)


def restart_command(background=False):
    executable = Path(sys.executable).resolve()
    args = [] if getattr(sys, 'frozen', False) else [str(Path(__file__).resolve().with_name('main.py'))]
    args += ['--restart-after', str(os.getpid())]
    if background:
        args.append('--tray')
    return str(executable), subprocess.list2cmdline(args), str(executable.parent)


def request_elevated_restart(background=False):
    executable, arguments, directory = restart_command(background)
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    shell.ShellExecuteW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                   wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int]
    shell.ShellExecuteW.restype = ctypes.c_ssize_t
    result = shell.ShellExecuteW(None, 'runas', executable, arguments, directory, 1)
    if result <= 32:
        raise OSError('未获得管理员启动确认，已保留当前运行。')


def wait_for_previous_instance(arguments):
    """Wait before logs, mutex and HID are opened, avoiding two active writers."""
    if '--restart-after' not in arguments:
        return
    try:
        pid = int(arguments[arguments.index('--restart-after') + 1])
        if pid <= 0 or pid == os.getpid():
            raise ValueError()
    except (ValueError, IndexError):
        raise SystemExit('无效的重启请求。')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE only
    if not handle:
        if ctypes.get_last_error() == 87:  # Parent has already exited.
            return
        raise SystemExit('无法等待原程序退出，已取消重复启动。')
    try:
        if kernel.WaitForSingleObject(handle, 15000) != 0:
            raise SystemExit('原程序尚未退出，已取消重复启动。')
    finally:
        kernel.CloseHandle(handle)
