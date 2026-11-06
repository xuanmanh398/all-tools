@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
title Tools Marketing

echo ========================================================
echo             TOOLS MARKETING - BOOTSTRAPPER
echo ========================================================
echo.

:: Clean old stuck node processes
taskkill /F /IM node.exe /T >nul 2>&1

:: Auto detect Python 3.11 if not in PATH
python --version >nul 2>&1
if errorlevel 1 (
    if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
        set "PATH=%LOCALAPPDATA%\Programs\Python\Python311;%LOCALAPPDATA%\Programs\Python\Python311\Scripts;%PATH%"
    ) else if exist "C:\Python311\python.exe" (
        set "PATH=C:\Python311;C:\Python311\Scripts;%PATH%"
    )
)

if exist "%~dp0.venv\Scripts\python.exe" goto RUN_APP

echo [INFO] Creating Virtual Environment .venv...
python -m venv .venv
if errorlevel 1 (
    echo [ERROR] Cannot create virtual environment!
    pause
    exit /b 1
)

echo [INFO] Installing required libraries...
call "%~dp0.venv\Scripts\activate.bat"
call pip install -r requirements.txt

:RUN_APP
echo [INFO] Starting Tools Marketing...
"%~dp0.venv\Scripts\python.exe" main.py

if errorlevel 1 (
    echo.
    echo [ERROR] Application exited with error.
    pause
)
