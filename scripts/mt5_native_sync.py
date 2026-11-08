"""
Direct Native MetaTrader 5 Python Gateway & Telemetry Sync.
Connects directly to MetaTrader 5 on Windows via IPC (Inter-Process Communication).
No EA, No MQL5 compiling, and No chart dragging required!
"""

import os
import sys
import time
import json
import logging
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    print("[ERROR] 'requests' package not found. Run: pip install requests")
    sys.exit(1)

try:
    import MetaTrader5 as mt5
except ImportError:
    print("[ERROR] 'MetaTrader5' package not found. Run: pip install MetaTrader5")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("MT5NativeSync")

BRIDGE_URL = os.getenv("BRIDGE_URL", "http://127.0.0.1:8000")
LOGIN = int(os.getenv("MT5_LOGIN", "416568420"))
SERVER = os.getenv("MT5_SERVER", "Exness-MT5Trial14")
PASSWORD = os.getenv("MT5_PASSWORD", "like_Apple1")
MAGIC_NUMBER = 888999

SUPPORTED_SYMBOLS = ["XAUUSD", "BTCUSD", "ETHUSD", "XAGUSD", "GBPUSD", "EURUSD", "XPTUSD", "UKOIL", "XNGUSD"]


def init_mt5() -> bool:
    """Connects to MetaTrader 5 terminal and enables all 9 specialist markets."""
    logger.info(f"Connecting to MT5 (Login: {LOGIN}, Server: {SERVER})...")
    connected = False

    # 1. Try with explicit credentials first
    if mt5.initialize(login=LOGIN, server=SERVER, password=PASSWORD):
        logger.info("[SUCCESS] Connected to MT5 with account credentials!")
        connected = True
    elif mt5.initialize():
        logger.info("[SUCCESS] Connected to active MT5 terminal session!")
        connected = True

    if not connected:
        err = mt5.last_error()
        logger.error(f"[FAILED] Could not connect to MT5 terminal: {err}")
        logger.error("Please ensure MetaTrader 5 is launched and logged in on this Windows machine.")
        return False

    # 2. Automatically enable all 9 specialist symbols in Market Watch
    logger.info("Initializing 9 Specialist Markets in MT5 Market Watch...")
    enabled_count = 0
    for sym in SUPPORTED_SYMBOLS:
        if mt5.symbol_select(sym, True):
            enabled_count += 1
            logger.info(f" • [ACTIVE] {sym:8s} enabled in Market Watch")
        else:
            logger.warning(f" • [WARN]   {sym:8s} not found in broker symbol list")

    logger.info(f"Successfully activated {enabled_count}/{len(SUPPORTED_SYMBOLS)} symbols in MT5!")
    return True


def get_account_payload() -> dict:
    """Fetches real-time account data from MT5."""
    acc = mt5.account_info()
    if acc is None:
        return {}
    return {
        "account_number": acc.login,
        "server": acc.server,
        "balance": round(float(acc.balance), 2),
        "equity": round(float(acc.equity), 2),
        "floating_pnl": round(float(acc.profit), 2),
        "margin_free": round(float(acc.margin_free), 2),
        "currency": acc.currency
    }


def get_open_positions() -> list:
    """Fetches all open positions from MT5."""
    positions = mt5.positions_get()
    result = []
    if positions:
        for p in positions:
            is_buy = (p.type == mt5.ORDER_TYPE_BUY)
            result.append({
                "ticket": p.ticket,
                "symbol": p.symbol,
                "type": "BUY" if is_buy else "SELL",
                "volume": round(float(p.volume), 2),
                "open_price": round(float(p.price_open), 5),
                "current_price": round(float(p.price_current), 5),
                "sl": round(float(p.sl), 5) if p.sl else 0.0,
                "tp": round(float(p.tp), 5) if p.tp else 0.0,
                "profit": round(float(p.profit), 2),
                "magic": p.magic,
                "time": p.time
            })
    return result


def execute_order(cmd: dict) -> dict:
    """Executes market order or close position in MT5."""
    action = cmd.get("action", "").upper()
    symbol = cmd.get("symbol", "XAUUSD").upper()
    cmd_id = cmd.get("command_id", "")

    # Ensure symbol is selected in Market Watch
    mt5.symbol_select(symbol, True)
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return {"command_id": cmd_id, "status": "REJECTED", "error": f"No tick data for {symbol}"}

    if action in ("BUY", "SELL"):
        lot = float(cmd.get("volume", cmd.get("lots", 0.01)))
        sl = float(cmd.get("sl", 0.0))
        tp = float(cmd.get("tp", 0.0))
        is_buy = (action == "BUY")
        price = tick.ask if is_buy else tick.bid
        order_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": 30,
            "magic": MAGIC_NUMBER,
            "comment": "Pilotfish AI Squad",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.warning(f"[ORDER REJECTED] {action} {symbol}: retcode={result.retcode} ({result.comment})")
            return {"command_id": cmd_id, "status": "REJECTED", "error": result.comment}

        logger.info(f"[ORDER FILLED] {action} {symbol} {lot} lots @ {result.price} (Ticket #{result.order})")
        return {
            "command_id": cmd_id,
            "status": "CONFIRMED",
            "ticket": result.order,
            "price": result.price
        }

    elif action == "CLOSE":
        ticket = int(cmd.get("ticket", 0))
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return {"command_id": cmd_id, "status": "REJECTED", "error": f"Position #{ticket} not found"}

        pos = positions[0]
        close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        close_price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": close_type,
            "price": close_price,
            "deviation": 30,
            "magic": MAGIC_NUMBER,
            "comment": "Pilotfish Close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return {"command_id": cmd_id, "status": "REJECTED", "error": result.comment}

        logger.info(f"[CLOSED] Position #{ticket} @ {result.price}")
        return {"command_id": cmd_id, "status": "CONFIRMED", "ticket": ticket}

    return {"command_id": cmd_id, "status": "UNKNOWN_ACTION"}


def sync_loop():
    """Main continuous synchronization loop covering all 9 specialist markets."""
    logger.info("Starting MT5 Direct Native Telemetry & Order Sync Loop for 9 Markets...")
    session = requests.Session()
    last_bars_upload = 0.0

    while True:
        try:
            # 1. Fetch live MT5 account info
            acc_data = get_account_payload()
            if not acc_data:
                logger.warning("Waiting for MT5 account data...")
                time.sleep(2)
                continue

            # 2. Fetch open positions across ALL 9 symbols at once
            open_positions = get_open_positions()

            # 3. Fetch primary tick for XAUUSD
            tick = mt5.symbol_info_tick("XAUUSD")
            bid = tick.bid if tick else 2650.0
            ask = tick.ask if tick else 2650.25

            # 4. Send Telemetry to Bridge
            telemetry = {
                "account_number": acc_data["account_number"],
                "server": acc_data["server"],
                "balance": acc_data["balance"],
                "equity": acc_data["equity"],
                "symbol": "XAUUSD",
                "bid": bid,
                "ask": ask,
                "open_positions": open_positions,
                "closed_orders": []
            }

            try:
                resp = session.post(f"{BRIDGE_URL}/api/mt5/telemetry", json=telemetry, timeout=1.0)
                if resp.status_code == 200:
                    logger.debug(f"Telemetry synced: Equity=${acc_data['equity']}, Positions={len(open_positions)}")
            except Exception as e:
                logger.warning(f"Bridge connection waiting at {BRIDGE_URL}: {e}")

            # 5. Periodically upload M5 bars for all 9 markets
            if time.time() - last_bars_upload > 10.0:
                last_bars_upload = time.time()
                for sym in SUPPORTED_SYMBOLS:
                    try:
                        rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 60)
                        if rates is not None and len(rates) > 0:
                            bars_payload = {
                                "symbol": sym,
                                "timeframe": "M5",
                                "bars": [
                                    {
                                        "time": int(r[0]),
                                        "open": float(r[1]),
                                        "high": float(r[2]),
                                        "low": float(r[3]),
                                        "close": float(r[4]),
                                        "volume": float(r[5])
                                    }
                                    for r in rates
                                ]
                            }
                            session.post(f"{BRIDGE_URL}/api/mt5/bars", json=bars_payload, timeout=1.5)
                    except Exception:
                        pass

            # 6. Poll and execute pending trade commands for any of the 9 symbols
            try:
                cmd_resp = session.get(f"{BRIDGE_URL}/api/mt5/commands", timeout=1.0)
                if cmd_resp.status_code == 200:
                    commands = cmd_resp.json().get("commands", [])
                    for cmd in commands:
                        if cmd:
                            exec_res = execute_order(cmd)
                            session.post(f"{BRIDGE_URL}/api/mt5/confirm", json=exec_res, timeout=1.0)
            except Exception as e:
                logger.debug(f"Command poll error: {e}")

            time.sleep(1.0)

        except KeyboardInterrupt:
            logger.info("Sync loop stopped by user.")
            break
        except Exception as e:
            logger.error(f"Sync error: {e}")
            time.sleep(2.0)


if __name__ == "__main__":
    print("=" * 60)
    print("   🚀 PILOTFISH MT5 DIRECT NATIVE SYNC GATEWAY")
    print("   No EA, No Charts, No MQL5 Compiling Needed!")
    print("=" * 60)
    if init_mt5():
        sync_loop()
    else:
        print("[EXIT] Failed to initialize MT5. Press enter to exit.")
        input()
