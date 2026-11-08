@echo off
title Pilotfish MT5 Direct Native Sync Gateway
color 0A

echo ==============================================================
echo        🚀 PILOTFISH MT5 DIRECT NATIVE SYNC (NO EA NEEDED)
echo ==============================================================
echo  - Connecting directly to MetaTrader 5 on Windows via Python IPC
echo  - No EA drag-and-drop, No MQL5 compiling, No chart needed!
echo ==============================================================
echo.

echo [1/2] Checking Python and dependencies...
python -m pip install --quiet MetaTrader5 requests
if %ERRORLEVEL% NEQ 0 (
    echo [WARNING] Pip install had issues. Attempting to proceed with Python...
)

echo [2/2] Launching MT5 Native Sync Service...
echo  • Target Account: 416568420
echo  • Server: Exness-MT5Trial14
echo  • Bridge URL: http://127.0.0.1:8000
echo.

python mt5_native_sync.py

pause
