@echo off
chcp 65001 >nul
title Daytrad Agentic Squad - 1-Click Deployment (Windows Laptop)
color 0B

echo =======================================================================
echo   🚀 DAYTRAD AGENTIC SQUAD - 1-CLICK DOCKER REDEPLOY
echo =======================================================================
echo  Target: Windows Deployment Host (100.105.249.12 / localhost)
echo  Features:
echo   • Universal Broker Suffix Auto-Detection (m, c, or standard)
echo   • Cent Account (USC) & Standard Dynamic +3%% Risk Scaling
echo   • 9 Specialists (Gold, BTC, ETH, Silver, GBP, EUR, XPT, Oil, Gas)
echo   • Multi-Account Profile Support (Port 8000 Main / Port 8001 Demo)
echo =======================================================================
echo.

echo [1/4] Stopping running containers...
docker compose --profile live --profile multi down
if %ERRORLEVEL% NEQ 0 (
    echo [INFO] No active compose containers found, continuing...
)

echo.
echo [2/4] Pulling latest code and risk models from Git...
git pull origin main

echo.
echo [3/4] Building and launching containers (Bridge + Squad Live Agent)...
docker compose --profile live up -d --build
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Docker compose build/up failed! Please verify Docker Desktop is running.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo [4/4] Verifying MT5 Bridge and telemetry health...
timeout /t 5 /nobreak >nul
curl -s http://localhost:8000/api/mt5/status
echo.
echo.
echo =======================================================================
echo   ✅ 100%% TURNKEY REDEPLOY COMPLETE!
echo.
echo   • MT5 FastAPI Bridge:   http://localhost:8000
echo   • MT5 Bridge Status:    http://localhost:8000/api/mt5/status
echo   • Trader Central Hub:   http://localhost:3000 (or http://100.105.249.12:3000)
echo   • Specialist Loop:      Live (9 Assets: Gold, BTC, ETH, FX, Energy)
echo   • Log Monitoring:       docker logs -f agentic_squad_agent
echo =======================================================================
pause
