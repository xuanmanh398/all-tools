@echo off
title FB Group Auto-Poster

echo ========================================================
echo         FB GROUP AUTO-POSTER - BOOTSTRAPPER
echo ========================================================
echo.

if exist .venv goto ACTIVATED

echo [INFO] Creating Virtual Environment .venv...
python -m venv .venv
if errorlevel 1 (
    echo [ERROR] Cannot create virtual environment. Please check Python installation.
    pause
    exit /b 1
)

:ACTIVATED
echo [INFO] Activating Virtual Environment...
call .venv\Scripts\activate.bat

echo [INFO] Installing required packages...
pip install -r requirements.txt

echo [INFO] Installing Playwright Chromium browser...
playwright install chromium

echo.
echo ========================================================
echo         STARTING FB GROUP AUTO-POSTER...
echo ========================================================
echo.

python main.py

if errorlevel 1 (
    echo.
    echo [ERROR] Application stopped with an error.
    pause
)
