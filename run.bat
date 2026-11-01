@echo off
chcp 65001 >nul
set NODE_OPTIONS=
title FB Group Auto-Poster & Threads Mass Post

echo ========================================================
echo         FB GROUP AUTO-POSTER - BOOTSTRAPPER
echo ========================================================
echo.

:: Dọn dẹp tiến trình node.exe cũ nếu bị kẹt
taskkill /F /IM "node.exe" /T >nul 2>&1

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
