@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv 2>nul
    if not exist ".venv\Scripts\python.exe" python -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
    echo Python 3.10 or newer is required.
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo Installation failed; see messages above.
    pause
    exit /b 1
)
echo Open http://127.0.0.1:8765 in your browser.
python run.py
pause
