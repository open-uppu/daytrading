"""
Test live order execution against MT5 Bridge
"""
import time
from mt5.bridge_server import MT5BridgeBroker

def test_live_mt5_orders():
    broker = MT5BridgeBroker(host="127.0.0.1", port=8000)
    acc = broker.get_account_info()
    print(f"=== Initial MT5 Account ===")
    print(f"Account: #{acc.get('account_number')} on {acc.get('server')}")
    print(f"Balance: ${acc.get('balance'):,.2f} | Equity: ${acc.get('equity'):,.2f}")
    
    # Get BTC quote
    open_positions = acc.get("open_positions", [])
    btc_bid = None
    for p in open_positions:
        if p.get("symbol") == "BTCUSD":
            btc_bid = p.get("bid")
            break
            
    if not btc_bid:
        btc_bars = broker.get_market_data("BTCUSD", "M5", bars=5)
        btc_bid = float(btc_bars["close"].iloc[-1])
        
    print(f"\nCurrent BTCUSD Price: ~${btc_bid:,.2f}")
    
    # 1. Test BUY Order
    buy_sl = round(btc_bid - 1000.0, 2)
    buy_tp = round(btc_bid + 2000.0, 2)
    print(f"\n[1] Submitting BUY 0.01 lots BTCUSD (SL: ${buy_sl:,.2f}, TP: ${buy_tp:,.2f})...")
    
    buy_res = broker.open_order(
        symbol="BTCUSD",
        order_type="BUY",
        lots=0.01,
        sl=buy_sl,
        tp=buy_tp,
        comment="Test_BUY",
        await_confirm=True,
        confirm_timeout=10.0
    )
    print("BUY Result:", buy_res)
    buy_ticket = buy_res.get("ticket")
    
    if buy_ticket and buy_ticket > 0:
        print(f"--> BUY Order filled successfully! Ticket: #{buy_ticket}")
        time.sleep(2)
        print(f"\n[2] Closing BUY Order #{buy_ticket}...")
        close_res = broker.close_order(buy_ticket, await_confirm=True, confirm_timeout=10.0)
        print("Close Result:", close_res)
        print(f"--> BUY Order #{buy_ticket} closed successfully!")
    else:
        print("--> BUY Order failed or unconfirmed.")
        return

    # 2. Test SELL Order
    time.sleep(1)
    sell_sl = round(btc_bid + 1000.0, 2)
    sell_tp = round(btc_bid - 2000.0, 2)
    print(f"\n[3] Submitting SELL 0.01 lots BTCUSD (SL: ${sell_sl:,.2f}, TP: ${sell_tp:,.2f})...")
    
    sell_res = broker.open_order(
        symbol="BTCUSD",
        order_type="SELL",
        lots=0.01,
        sl=sell_sl,
        tp=sell_tp,
        comment="Test_SELL",
        await_confirm=True,
        confirm_timeout=10.0
    )
    print("SELL Result:", sell_res)
    sell_ticket = sell_res.get("ticket")
    
    if sell_ticket and sell_ticket > 0:
        print(f"--> SELL Order filled successfully! Ticket: #{sell_ticket}")
        time.sleep(2)
        print(f"\n[4] Closing SELL Order #{sell_ticket}...")
        close_sell_res = broker.close_order(sell_ticket, await_confirm=True, confirm_timeout=10.0)
        print("Close Result:", close_sell_res)
        print(f"--> SELL Order #{sell_ticket} closed successfully!")
    else:
        print("--> SELL Order failed or unconfirmed.")

    print("\n=== Live Test Complete ===")

if __name__ == "__main__":
    test_live_mt5_orders()
