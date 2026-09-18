---
name: mt5-bridge
description: Communication bridge protocol connecting the Python trading agent to MetaTrader 5 (MT5) via MQL5 Expert Advisor (AgenticMT5Bridge.mq5) or high-fidelity paper broker.
version: 2.0.0
---

# MT5 Bridge Skill

This skill defines how the agent communicates with MetaTrader 5 (MT5) for live Exness price feeds, account telemetry, and order execution.

## Account Credentials & Configuration

- **Broker**: Exness
- **Server**: `Exness-MT5Trial14`
- **Account Number**: `416387559`
- **Bridge Endpoint**: `http://127.0.0.1:8000`

## Architecture & REST Protocol

1. **Telemetry Ingestion (`POST /api/mt5/telemetry`)**:
   MT5 transmits live account equity, balance, bid, ask, and active positions:
   ```json
   {
     "account_number": 416387559,
     "server": "Exness-MT5Trial14",
     "balance": 10000.0,
     "equity": 10000.0,
     "symbol": "XAUUSD",
     "bid": 2650.50,
     "ask": 2650.75,
     "open_positions": [
       {
         "ticket": 12345678,
         "symbol": "XAUUSD",
         "type": "BUY",
         "lots": 0.20,
         "open_price": 2648.00,
         "sl": 2643.00,
         "tp": 2658.00,
         "profit": 50.00
       }
     ]
   }
   ```

2. **Command Dispatch (`GET /api/mt5/commands`)**:
   MT5 EA polls for queued trade actions:
   ```json
   {
     "commands": [
       {
         "id": "cmd_mt5_001",
         "action": "ORDER_OPEN",
         "symbol": "XAUUSD",
         "type": "BUY",
         "volume": 0.20,
         "sl": 2643.00,
         "tp": 2658.00,
         "comment": "AgenticMT5_M15"
       }
     ]
   }
   ```

3. **Trade Execution Confirmation (`POST /api/mt5/confirm`)**:
   MQL5 EA confirms fill result and order ticket.

4. **Installation on MetaTrader 5**:
   - Copy `mt5/AgenticMT5Bridge.mq5` into MT5's `MQL5/Experts/` folder.
   - Open MetaEditor 5 and press **Compile (F7)**.
   - In MT5 Tools -> Options -> Expert Advisors, check `Allow WebRequest for listed URL` and add `http://127.0.0.1:8000`.
   - Drag the EA onto the `XAUUSD` M15 chart.
