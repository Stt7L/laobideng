@echo off
setlocal
cd /d "%~dp0"
where py.exe >nul 2>nul
if not errorlevel 1 (
    py -3 -m venv ".venv"
    if errorlevel 1 goto failed
    goto install
)
where python.exe >nul 2>nul
if not errorlevel 1 (
    python -m venv ".venv"
    if errorlevel 1 goto failed
    goto install
)
echo 未找到 Python 3.10 或更新版本。请先安装 Python。
pause
exit /b 1
:install
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r "requirements.txt"
if errorlevel 1 goto failed
echo 安装完成。
exit /b 0
:failed
echo 安装失败，请检查网络连接后重试。
pause
exit /b 1
