@echo off
setlocal enabledelayedexpansion
title PassPaper v1.0.0

echo.
echo ========================================
echo   PassPaper v1.0.0 - daemon launcher
echo ========================================
echo.

REM --- Auto-detect Python ---
set PY=

REM 1) Anaconda
for /f "tokens=*" %%i in ('where conda 2^>nul') do (
    for /f "tokens=*" %%j in ('conda info --base 2^>nul') do (
        if exist "%%j\python.exe" (
            set PY=%%j\python.exe
            goto :found_python
        )
    )
)

REM 2) System python3 / python
for %%c in (python3 python) do (
    where %%c >nul 2>&1
    if !errorlevel!==0 (
        for /f "tokens=*" %%p in ('where %%c 2^>nul ^| findstr /V /I "WindowsApps"') do (
            set PY=%%p
            goto :found_python
        )
    )
)

echo [ERROR] Python not found. Please install Python first.
pause
exit /b 1

:found_python
echo [OK] Python: !PY!

REM --- Check/install dependencies ---
"!PY!" -c "import websockets, PIL, qrcode" >nul 2>&1
if !errorlevel! neq 0 (
    echo [INSTALL] Installing dependencies...
    "!PY!" -m pip install -r "%~dp0requirements.txt"
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to install dependencies.
        pause
        exit /b 1
    )
)
echo [OK] Dependencies ready.

REM --- One-time setup (idempotent): bundle + CC/Codex MCP registration ---
"!PY!" "%~dp0src\passpaper\cli.py" setup

REM --- Start the always-on daemon (detached) ---
"!PY!" "%~dp0src\passpaper\cli.py" start

REM --- Show status + tablet URL ---
"!PY!" "%~dp0src\passpaper\cli.py" status

echo.
echo Daemon runs in the background and survives this window closing.
echo To stop it:  "!PY!" "%~dp0src\passpaper\cli.py" stop
echo.
pause
