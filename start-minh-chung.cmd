@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=C:\Users\Minh\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"
start "" cmd /c "timeout /t 2 /nobreak > nul & start http://127.0.0.1:8765"
"%PYTHON%" run.py

