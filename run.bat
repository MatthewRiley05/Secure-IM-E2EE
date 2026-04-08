@echo off
REM run.bat - Start the Secure-IM-E2EE server with TLS (Windows)
REM Runs on https://localhost:8000

setlocal enabledelayedexpansion

echo.
echo 🚀 Starting Secure-IM-E2EE Server
echo ==================================
echo.

REM Check if certificates exist
if not exist "certs\cert.pem" (
    echo ❌ Certificates not found!
    echo Run "setup.bat" first to generate certificates.
    pause
    exit /b 1
)

if not exist "certs\key.pem" (
    echo ❌ Key file not found!
    echo Run "setup.bat" first to generate certificates.
    pause
    exit /b 1
)

echo ✅ Certificates found
echo.

REM Activate virtual environment
if not exist ".venv\Scripts\activate.bat" (
    echo ❌ Virtual environment not found. Run "setup.bat" first.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
echo ✅ Virtual environment activated
echo.

REM Check if database exists
if not exist "im_server.db" (
    echo 💾 Initializing database...
    python -c "from app.db import Base, engine; Base.metadata.create_all(bind=engine)"
    echo ✅ Database initialized
    echo.
)

REM Display startup info
echo 🌐 Server starting...
echo.
echo    📍 HTTPS: https://localhost:8000
echo    📍 Web UI: https://localhost:8000/ui
echo    📍 API Docs: https://localhost:8000/docs
echo.
echo ⏸️  Press Ctrl+C to stop the server
echo.
echo ==================================
echo.

REM Start the server with TLS
python -m uvicorn app.main:app ^
    --host 0.0.0.0 ^
    --port 8000 ^
    --ssl-keyfile=certs/key.pem ^
    --ssl-certfile=certs/cert.pem ^
    --reload

pause
