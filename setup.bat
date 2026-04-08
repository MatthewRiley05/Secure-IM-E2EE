@echo off
REM setup.bat - Complete setup script for Secure-IM-E2EE (Windows)
REM Installs all dependencies and generates TLS certificates

setlocal enabledelayedexpansion

echo.
echo ================================
echo 🔒 Secure-IM-E2EE Setup
echo ================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python not found. Please install Python 3.10 or later.
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo ✅ Python %PYTHON_VERSION% found
echo.

REM Step 1: Create virtual environment
echo 📦 Step 1: Creating virtual environment...
if exist ".venv" (
    echo    ℹ️  Virtual environment already exists
) else (
    python -m venv .venv
    echo ✅ Virtual environment created
)
echo.

REM Step 2: Activate virtual environment and install dependencies
echo 📦 Step 2: Installing dependencies...
call .venv\Scripts\activate.bat

python -m pip install --upgrade pip setuptools wheel >nul 2>&1
python -m pip install -r requirements.txt
echo ✅ Dependencies installed
echo.

REM Step 3: Generate TLS certificates
echo 🔐 Step 3: Generating TLS certificates...
if not exist "certs" mkdir certs

if exist "certs\cert.pem" (
    if exist "certs\key.pem" (
        echo    ℹ️  Certificates already exist
        goto :skip_cert
    )
)

echo    Generating self-signed certificate...
openssl req -x509 ^
    -newkey rsa:4096 ^
    -nodes ^
    -out certs\cert.pem ^
    -keyout certs\key.pem ^
    -days 365 ^
    -subj "/C=HK/ST=Hong Kong/L=Hong Kong/O=Secure-IM/CN=localhost"

echo ✅ Certificates generated

:skip_cert
echo.

REM Step 4: Create database
echo 💾 Step 4: Initializing database...
if exist "im_server.db" (
    echo    ℹ️  Database already exists
) else (
    python -c "from app.db import Base, engine; Base.metadata.create_all(bind=engine)"
    echo ✅ Database initialized
)
echo.

REM Summary
echo ================================
echo ✅ Setup Complete!
echo ================================
echo.
echo 🚀 To start the server, run:
echo    run.bat
echo.
echo 🌐 The application will be available at:
echo    https://localhost:8000
echo.
echo ⚠️  Browser Security Note:
echo    Your browser may show a security warning about the self-signed
echo    certificate. This is expected. Click 'Advanced' ^→ 'Proceed' or
echo    'Accept Risk' to continue.
echo.

pause
