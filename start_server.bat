@echo off
setlocal

REM ========================================
REM   Birder Station Web Server Launcher
REM ========================================
REM   Start from a normal cmd/PowerShell
REM   window, NOT from IDE terminal.
REM   IDE sandbox blocks recycle bin APIs.
REM ========================================

cd /d "%~dp0"

set "PYTHON_EXE=C:\Users\qinmi\AppData\Local\Programs\Python\Python311\python.exe"

if not exist "%PYTHON_EXE%" (
    set "PYTHON_EXE=python"
)

echo ========================================
echo   Birder Station Web Server
echo ========================================
echo.
echo Working dir: %CD%
echo Python: %PYTHON_EXE%
echo.
echo Starting server...
echo URL: http://localhost:8000
echo Press Ctrl+C to stop
echo ========================================
echo.

REM Run directly (no "start") to keep console open
"%PYTHON_EXE%" src\web\app.py

echo.
echo ========================================
echo Server stopped. Exit code: %ERRORLEVEL%
echo ========================================
pause
