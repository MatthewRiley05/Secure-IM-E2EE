#!/bin/bash

# setup.sh - Complete setup script for Secure-IM-E2EE
# Installs all dependencies and generates TLS certificates
# Works on Windows (WSL2), macOS, and Linux

set -e

echo "================================"
echo "🔒 Secure-IM-E2EE Setup"
echo "================================"
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3.10 or later."
    exit 1
fi

PYTHON_VERSION=$(python3 --version | awk '{print $2}')
echo "✅ Python $PYTHON_VERSION found"
echo ""

# Step 1: Create virtual environment
echo "📦 Step 1: Creating virtual environment..."
if [ -d ".venv" ]; then
    echo "   ℹ️  Virtual environment already exists"
else
    python3 -m venv .venv
    echo "✅ Virtual environment created"
fi
echo ""

# Step 2: Activate virtual environment and install dependencies
echo "📦 Step 2: Installing dependencies..."
source .venv/bin/activate 2>/dev/null || . .venv/Scripts/activate 2>/dev/null || true

# Check if pip is available
if ! command -v pip &> /dev/null; then
    echo "❌ pip not found. Trying python3 -m pip..."
    PYTHON_BIN="python3 -m pip"
else
    PYTHON_BIN="pip"
fi

$PYTHON_BIN install --upgrade pip setuptools wheel > /dev/null 2>&1 || true
$PYTHON_BIN install -r requirements.txt
echo "✅ Dependencies installed"
echo ""

# Step 3: Generate TLS certificates
echo "🔐 Step 3: Generating TLS certificates..."
CERTS_DIR="certs"

if [ ! -d "$CERTS_DIR" ]; then
    mkdir -p "$CERTS_DIR"
fi

if [ -f "$CERTS_DIR/cert.pem" ] && [ -f "$CERTS_DIR/key.pem" ]; then
    echo "   ℹ️  Certificates already exist"
else
    echo "   Generating self-signed certificate..."
    openssl req -x509 \
        -newkey rsa:4096 \
        -nodes \
        -out "$CERTS_DIR/cert.pem" \
        -keyout "$CERTS_DIR/key.pem" \
        -days 365 \
        -subj "/C=HK/ST=Hong Kong/L=Hong Kong/O=Secure-IM/CN=localhost" \
        2>/dev/null

    chmod 600 "$CERTS_DIR/key.pem"
    chmod 644 "$CERTS_DIR/cert.pem"
    echo "✅ Certificates generated"
fi
echo ""

# Step 4: Create database
echo "💾 Step 4: Initializing database..."
if [ -f "im_server.db" ]; then
    echo "   ℹ️  Database already exists"
else
    python3 -c "from app.db import Base, engine; Base.metadata.create_all(bind=engine)"
    echo "✅ Database initialized"
fi
echo ""

# Summary
echo "================================"
echo "✅ Setup Complete!"
echo "================================"
echo ""
echo "📋 Certificate Information:"
openssl x509 -in "$CERTS_DIR/cert.pem" -noout -dates | sed 's/^/   /'
echo ""
echo "🚀 To start the server, run:"
echo "   ./run.sh"
echo ""
echo "🌐 The application will be available at:"
echo "   https://localhost:8000"
echo ""
echo "⚠️  Browser Security Note:"
echo "   Your browser may show a security warning about the self-signed"
echo "   certificate. This is expected. Click 'Advanced' → 'Proceed' or"
echo "   'Accept Risk' to continue."
echo ""
