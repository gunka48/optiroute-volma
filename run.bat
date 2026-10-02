@echo off
cd /d "%~dp0"
title OptiRoute VOLMA - Server Running
color 0A

echo ====================================================
echo   STEP 2: STARTING OPTIROUTE VOLMA SERVER
echo ====================================================
echo.

if not exist "venv\Scripts\activate.bat" (
    color 0C
    echo [ERROR] Virtual environment not found!
    echo Please run "install.bat" first!
    echo.
    pause
    exit /b
)

call venv\Scripts\activate.bat

echo Server URL: http://127.0.0.1:8000
echo The browser will open automatically in 2 seconds.
echo Press Ctrl+C in this window to stop the server.
echo.

python main.py

echo.
echo Server stopped.
pause