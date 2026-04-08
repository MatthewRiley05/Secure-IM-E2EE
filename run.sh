#!/bin/bash

# run.sh - Start the Secure-IM-E2EE server with TLS
# Runs on https://localhost:8000

set -e

echo "🚀 Starting Secure-IM-E2EE Server"
echo "=================================="
echo ""

# Check if certificates exist
if [ ! -f "certs/cert.pem" ] || [ ! -f "certs/key.pem" ]; then
    echo "❌ Certificates not found!"
    echo "Run './setup.sh' first to generate certificates."
    exit 1
fi

echo "✅ Certificates found"

# Activate virtual environment
source .venv/bin/activate 2>/dev/null || . .venv/Scripts/activate 2>/dev/null || {
    echo "❌ Virtual environment not found. Run './setup.sh' first."
    exit 1
}

echo "✅ Virtual environment activated"
echo ""

# Check if database exists
if [ ! -f "im_server.db" ]; then
    echo "💾 Initializing database..."
    python3 -c "from app.db import Base, engine; Base.metadata.create_all(bind=engine)"
    echo "✅ Database initialized"
    echo ""
fi

# Display startup info
echo "🌐 Server starting..."
echo ""
echo "   📍 HTTPS: https://localhost:8000"
echo "   📍 Web UI: https://localhost:8000/ui"
echo "   📍 API Docs: https://localhost:8000/docs"
echo ""
echo "⏸️  Press Ctrl+C to stop the server"
echo ""
echo "=================================="
echo ""

# Start the server with TLS
# Using uvicorn with SSL certificates
python3 -m uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --ssl-keyfile=certs/key.pem \
    --ssl-certfile=certs/cert.pem \
    --reload
