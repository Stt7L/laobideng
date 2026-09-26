@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" goto setup
".venv\Scripts\python.exe" -c "import PySide6" >nul 2>nul
if errorlevel 1 goto setup
goto launch
:setup
call "安装依赖.bat"
if errorlevel 1 exit /b 1
:launch
start "" ".venv\Scripts\pythonw.exe" "main.py"
