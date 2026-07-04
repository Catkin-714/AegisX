@echo off
setlocal enabledelayedexpansion
title AegisX Dashboard
cd /d "%~dp0"

echo ============================================
echo   AegisX Dashboard Launcher
echo ============================================
echo.

REM Check Python
.venv\Scripts\python.exe --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python venv not found at .venv\Scripts\python.exe
    echo Run: python -m venv .venv
    echo Then: .venv\Scripts\pip install fastapi uvicorn pycryptodome
    pause
    exit /b 1
)

REM Check Rust binary
if exist "mcu_rust\target\release\mcu_hp.exe" (
    set "RUST_HP=mcu_rust\target\release\mcu_hp.exe"
) else if exist "mcu_rust\target\debug\mcu_hp.exe" (
    set "RUST_HP=mcu_rust\target\debug\mcu_hp.exe"
) else (
    echo [WARN] Rust binary not found, building...
    cd mcu_rust
    cargo build --release 2>nul
    cd ..
    if exist "mcu_rust\target\release\mcu_hp.exe" (
        set "RUST_HP=mcu_rust\target\release\mcu_hp.exe"
    ) else (
        echo [ERROR] Rust build failed. Check Rust toolchain.
        pause
        exit /b 1
    )
)

REM Kill old processes
taskkill /F /IM mcu_hp.exe >nul 2>&1
ping -n 2 127.0.0.1 >nul

REM 1. Rust HP
echo [1/3] Starting Rust MCU HP on port 9000...
start "RustHP" cmd /c "!RUST_HP!" --mode hp ^& pause
ping -n 3 127.0.0.1 >nul
echo   [OK] Rust HP launched

REM 2. Dashboard Backend
echo [2/3] Starting Dashboard API on port 8000...
start "DashAPI" cmd /c "cd /d %~dp0dashboard\backend && ..\..\.venv\Scripts\python.exe main.py & pause"
ping -n 4 127.0.0.1 >nul
echo   [OK] Dashboard launched

REM 3. Open browser
echo [3/3] Opening frontend...
start "" "dashboard\frontend\index.html"
echo   [OK] Browser opened

echo.
echo ============================================
echo   All services started:
echo     Rust HP    : http://127.0.0.1:9000
echo     Dashboard  : http://127.0.0.1:8000
echo     API Docs   : http://127.0.0.1:8000/docs
echo ============================================
echo.
echo Close the three windows to stop all services.
echo Press any key to close this launcher...
pause >nul

taskkill /FI "WINDOWTITLE eq RustHP" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq DashAPI" /F >nul 2>&1
echo Done.
