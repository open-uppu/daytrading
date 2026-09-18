---
name: mt4-bridge
description: Communication bridge protocol connecting the Python trading agent to MetaTrader 4 via MQL4 Expert Advisor (AgenticMT4Bridge.mq4) or paper broker.
version: 1.0.0
---

# MT4 Bridge Skill

This skill defines how the agent communicates with MetaTrader 4 (MT4) terminal for live price feeds, account telemetry, and order execution.

## Communication Architecture

The bridge operates via local HTTP REST endpoints served by Python FastAPI server (`mt4/bridge_server.py`) and polled or called by `AgenticMT4Bridge.mq4` attached to the MT4 chart:

### 1. Telemetry Sync (`POST /api/mt4/telemetry`)
MT4 sends account state and market tick on every tick or candle close:
```json
{
  "account_number": 1234567,
  "balance": 10000.0,
  "equity": 10000.0,
  "symbol": "XAUUSD",
  "bid": 2650.25,
  "ask": 2650.50,
  "open_positions": [
    {
      "ticket": 987654,
      "symbol": "XAUUSD",
      "type": "BUY",
      "lots": 0.25,
      "open_price": 2648.00,
      "sl": 2643.50,
      "tp": 2657.00,
      "profit": 56.25
    }
  ]
}
```

### 2. Trade Execution (`GET /api/mt4/commands`)
The MQL4 EA polls for pending trade orders:
```json
{
  "commands": [
    {
      "id": "cmd_001",
      "action": "ORDER_OPEN",
      "symbol": "XAUUSD",
      "type": "BUY",
      "volume": 0.25,
      "sl": 2645.00,
      "tp": 2660.00,
      "magic": 888999,
      "comment": "AgenticGold_M15"
    }
  ]
}
```

### 3. Execution Acknowledgement (`POST /api/mt4/confirm`)
EA confirms order execution status and ticket number.

### 4. File-Based Pipe Fallback
If WebRequest is disabled or network sockets are restricted in MT4 terminal settings, the bridge supports writing JSON command files directly into MT4's `MQL4/Files/` directory (`commands.json` and `status.json`).
