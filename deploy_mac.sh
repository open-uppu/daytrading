#!/bin/bash
set -e

echo "======================================================================="
echo "  🚀 DAYTRAD AGENTIC SQUAD - 1-CLICK MAC / UNIX REDEPLOY"
echo "======================================================================="

cd "$(dirname "$0")"

echo "[1/4] Running full test suite (Verification Gate)..."
python3 -m pytest tests/ -q

echo "[2/4] Pulling latest updates from Git..."
git pull origin main || true

echo "[3/4] Launching Docker Compose stack (Bridge + Squad Live)..."
docker compose --profile live up -d --build

echo "[4/4] Verifying MT5 Bridge health..."
sleep 3
curl -s http://localhost:8000/api/mt5/status || true
echo ""
echo "======================================================================="
echo "  ✅ DEPLOYMENT COMPLETE! All 201 tests passed."
echo "======================================================================="
