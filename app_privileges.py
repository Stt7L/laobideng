"""Explicit, one-session Windows elevation; never change login or UAC policy."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys


def is_elevated():
    return bool(ctypes.WinDLL('shell32', use_last_error=True).IsUserAnAdmin())


def restart_command():
    executable = Path(sys.executable).resolve()
    args = [] if getattr(sys, 'frozen', False) else [str(Path(__file__).resolve().with_name('main.py'))]
    args += ['--restart-after', str(os.getpid())]
    return str(executable), subprocess.list2cmdline(args), str(executable.parent)


def request_elevated_restart():
    executable, arguments, directory = restart_command()
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
