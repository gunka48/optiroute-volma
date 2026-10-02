@echo off
cd /d "%~dp0"
title OptiRoute VOLMA - Installation
color 0B

echo ====================================================
echo   STEP 1: INSTALLING SYSTEM DEPENDENCIES
echo ====================================================
echo.

echo [1/3] Checking Python installation...
python --version
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Python is not installed or not in PATH!
    echo Please install Python and check "Add Python to PATH".
    echo.
    pause
    exit /b
)

echo.
echo [2/3] Creating virtual environment (venv)...
if exist "venv\Scripts\activate.bat" (
    echo Virtual environment already exists.
) else (
    python -m venv venv
)

echo.
echo [3/3] Installing libraries (FastAPI, OR-Tools, Uvicorn)...
echo Please wait about 30-45 seconds...
echo.

call venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to install requirements.
    pause
    exit /b
)

color 0A
echo.
echo ====================================================
echo   SUCCESS! All dependencies installed successfully!
echo   Now you can run: run.bat
echo ====================================================
echo.
pause