"""Check elevation handoff without showing UAC or changing system settings."""
from pathlib import Path
import os
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app_privileges as privileges
import ui_app

passed = 0


def check(condition, label):
    global passed
    assert condition, label
    passed += 1
    print('PASS:', label, flush=True)


executable, args, directory = privileges.restart_command()
check(Path(executable).is_absolute() and Path(executable).is_file(), 'restart uses actual executable path')
check('--restart-after' in args and str(os.getpid()) in args and '--autostart' not in args, 'handoff identifies parent without changing startup preference')
check('main.py' in args and Path(directory).is_dir(), 'source launch points to existing entry')


class Function:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        return self.result


class Shell:
    ShellExecuteW = Function(5)


real_dll = privileges.ctypes.WinDLL
try:
    shell = Shell()
    privileges.ctypes.WinDLL = lambda *args, **kwargs: shell
    try:
        privileges.request_elevated_restart()
    except OSError:
        check(True, 'cancelled UAC reports failure without claiming restart')
    else:
        raise AssertionError('cancel not handled')
    shell.ShellExecuteW.result = 64
    privileges.request_elevated_restart()
    check(shell.ShellExecuteW.calls[-1][1] == 'runas', 'uses explicit Windows consent verb')
finally:
    privileges.ctypes.WinDLL = real_dll

for argv in (['--restart-after'], ['--restart-after', 'bad'], ['--restart-after', str(os.getpid())]):
    try:
        privileges.wait_for_previous_instance(argv)
    except SystemExit:
        check(True, 'invalid parent cannot launch a competing instance')
    else:
        raise AssertionError('invalid parent accepted')

parent = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(.25)'],
                          creationflags=subprocess.CREATE_NO_WINDOW)
at = time.perf_counter()
privileges.wait_for_previous_instance(['--restart-after', str(parent.pid)])
check(parent.poll() is not None and time.perf_counter() - at >= .15, 'new instance waits for real parent exit before opening resources')


class Label:
    def setText(self, value):
        self.text = value


class Host:
    preview_mode = False
    game_compatibility_status = Label()

    def __init__(self):
        self.calls = []

    def _save_settings(self):
        self.calls.append('save')

    def exit_app(self):
        self.calls.append('exit')


old_elevated, old_request = ui_app.is_elevated, ui_app.request_elevated_restart
try:
    ui_app.is_elevated = lambda: False
    host = Host()

    def cancelled():
        raise OSError('cancelled')

    ui_app.request_elevated_restart = cancelled
    ui_app.MainWindow._restart_for_game(host)
    check(host.calls == ['save'], 'cancel retains current app and saved settings')
    ui_app.request_elevated_restart = lambda: host.calls.append('consent')
    host.calls.clear()
    ui_app.MainWindow._restart_for_game(host)
    check(host.calls == ['save', 'consent', 'exit'], 'save and consent precede orderly shutdown')
    host.preview_mode = True
    host.calls.clear()
    ui_app.MainWindow._restart_for_game(host)
    check(not host.calls, 'preview cannot request elevation')
finally:
    ui_app.is_elevated, ui_app.request_elevated_restart = old_elevated, old_request
print(f'PASS: {passed} restart checks; no real UAC requested')
