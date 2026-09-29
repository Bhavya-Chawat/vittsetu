@echo off
setlocal enabledelayedexpansion
title VittSetu — SC Channel Finance Navigator

echo ===================================================
echo    VittSetu — SC Channel Finance Navigator
echo ===================================================
echo.

cd /d "%~dp0"

:: ── 1. Python virtual environment ───────────────────────────────────────
set "PYTHON_CMD="

if exist ".venv\Scripts\python.exe" (
    set "PYTHON_CMD=.venv\Scripts\python.exe"
    echo [INFO] Using virtual environment at .venv\
) else if exist "venv\Scripts\python.exe" (
    set "PYTHON_CMD=venv\Scripts\python.exe"
    echo [INFO] Using virtual environment at venv\
)

if "%PYTHON_CMD%"=="" (
    where uv >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] No virtual environment found, and 'uv' is not installed.
        echo         Install uv first: https://docs.astral.sh/uv/getting-started/installation/
        echo         Then re-run this script.
        pause
        exit /b 1
    )
    echo [INFO] No virtual environment found - creating one with uv...
    uv venv --python 3.12 .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create the virtual environment.
        pause
        exit /b 1
    )
    set "PYTHON_CMD=.venv\Scripts\python.exe"
    echo [INFO] Installing backend dependencies ^(this can take a few minutes on first run^)...
    uv pip install --python .venv -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies.
        pause
        exit /b 1
    )
)

:: ── 2. .env ──────────────────────────────────────────────────────────────
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo [WARNING] .env created from .env.example.
        echo           Add your GROQ_API_KEY to enable Ask VittSetu and AI form-filling.
        echo           Get a free key at https://console.groq.com/keys
        echo           Opening it in Notepad now - save and close when done.
        notepad ".env"
    ) else (
        echo [WARNING] No .env or .env.example found. Set GROQ_API_KEY some other way to enable AI features.
    )
)

:: ── 3. Scheme database ───────────────────────────────────────────────────
:: Runs every start: idempotent — adds missing schemes and fills fields an
:: older database lacks (e.g. newly added guideline rules), never overwrites.
echo [INFO] Checking scheme database against verified NSFDC data...
"%PYTHON_CMD%" scripts\seed_schemes.py

:: ── 4. Channel Partner data (first run only) ────────────────────────────
"%PYTHON_CMD%" -c "import sys; from db import SessionLocal; from models import Partner; db = SessionLocal(); n = db.query(Partner).count(); db.close(); sys.exit(0 if n > 0 else 1)"
if errorlevel 1 (
    echo [INFO] Downloading and geocoding NSFDC's official Channel Partner directories...
    echo        One-time step, takes several minutes ^(network + geocoding rate limits^).
    echo        VittSetu will still start normally afterwards even if this is interrupted.
    "%PYTHON_CMD%" scripts\ingest_partners.py
)

:: ── 5. Frontend ──────────────────────────────────────────────────────────
where npm >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Node.js/npm not found. Install Node.js first: https://nodejs.org/
    pause
    exit /b 1
)

if not exist "frontend\node_modules" (
    echo [INFO] Installing frontend dependencies...
    call npm --prefix frontend install
)
if not exist "frontend\dist\index.html" (
    echo [INFO] Building frontend...
    call npm --prefix frontend run build
)

:: ── 6. Voice service (optional, best-effort) ────────────────────────────
if exist "voice_service\main.py" (
    echo [INFO] Starting VittSetu Voice Service on http://localhost:8001...
    start "VittSetu Voice Service" "%PYTHON_CMD%" -m uvicorn voice_service.main:app --host 127.0.0.1 --port 8001
)

:: ── 7. Backend + frontend (single server, one URL) ──────────────────────
echo.
echo [INFO] Starting VittSetu on http://localhost:8000 ...
echo [INFO] Press Ctrl+C to stop.
echo.

start "" cmd /c "timeout /t 5 >nul && start http://127.0.0.1:8000"

"%PYTHON_CMD%" -m uvicorn api:app --host 127.0.0.1 --port 8000

pause
