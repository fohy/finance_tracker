@echo off
setlocal
cd /d "%~dp0"

if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
)

call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt

echo.
echo FinFlow is running at http://127.0.0.1:5050
echo Press Ctrl+C to stop.
echo.
python app.py
