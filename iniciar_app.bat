@echo off
setlocal
cd /d "%~dp0"
if /i not "%~1"=="--bootstrap" (
    wscript.exe "%~dp0lanzar_silencioso.vbs"
    exit /b
)
if not exist ".venv\Scripts\pythonw.exe" (
    py -3 -m venv .venv || exit /b 1
)
if not exist ".venv\rutas-instalado" (
    ".venv\Scripts\python.exe" -m pip show proyecto-final-poo >nul 2>&1
    if errorlevel 1 (
        ".venv\Scripts\python.exe" -m pip install --upgrade pip || exit /b 1
        ".venv\Scripts\python.exe" -m pip install -e ".[dev]" || exit /b 1
    )
    type nul > ".venv\rutas-instalado"
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0scripts\lanzar_app.py"
