"""Reference reproduction + pooled expectancy summary (research aid)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.run_m5_backtest import run_single_asset_m5_backtest

HERE = Path(__file__).resolve().parent

for sym in ["XAUUSD", "BTCUSD", "ETHUSD"]:
    r = run_single_asset_m5_backtest(sym)
    keys = ["total_trades", "win_rate_pct", "profit_factor", "total_return_pct",
            "max_drawdown_pct", "trades_per_day", "total_trading_days"]
    print(sym, {k: r[k] for k in keys})

print()
for f in ["sweep_xauusd.json", "sweep_xauusd_extra.json", "sweep_btcusd.json", "sweep_ethusd.json"]:
    p = HERE / f
    if not p.exists():
        continue
    d = json.loads(p.read_text(encoding="utf-8"))
    for res in d["results"]:
        a, b = res["IS"], res["OOS"]
        n = a["total_trades"] + b["total_trades"]
        pooled = (a["total_trades"] * a["expectancy_r"] + b["total_trades"] * b["expectancy_r"]) / n
        print(f"{d['symbol']:7s} {res['id']:<27} pooled={pooled:+.3f}R n={n:4d} "
              f"is={a['expectancy_r']:+.3f} oos={b['expectancy_r']:+.3f} "
              f"oos_win={b['win_rate_pct']:.1f} oos_tp/be/sl={b['tp_exits']}/{b['be_exits']}/{b['sl_exits']}")
