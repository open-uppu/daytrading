"""
Research-only parameter sweep harness for the M5 scalper.

IMPORTANT: this file does NOT modify any existing daytrad source. It imports
`backtest.run_m5_backtest.M5BacktestEngine`, `backtest.strategies.strategy_m5_scalper`
and `backtest.metrics.calculate_performance_metrics` unchanged, and subclasses the
engine only to add three switches that the shipped M5 engine does not expose:
  - fixed RR multiple (instead of the strategy's hardcoded 1.8*ATR TP / 1.25*ATR SL)
  - ATR-based SL multiplier (instead of the strategy's hardcoded 1.25*ATR)
  - optional trailing break-even trigger in R (the published M5 engine has NO BE;
    only backtest/engine.py, the M15 engine, has it)

Run:
  python research/strategy_sweep.py --symbol XAUUSD --configs full --out research/sweep_xauusd.json
  python research/strategy_sweep.py --symbol XAUUSD --configs full --verify
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import numpy as np

# Run from the repo root's venv: script lives in research/, project root is its parent.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.run_m5_backtest import M5BacktestEngine
from backtest.strategies import strategy_m5_scalper, _price_precision_for
from backtest.data_loader import load_historical_data
from backtest.metrics import calculate_performance_metrics
from core.indicators import compute_all_indicators

RESEARCH_DIR = Path(__file__).resolve().parent


def _sym_specs(sym: str):
    if "XAU" in sym:
        return dict(asset_type="gold", contract_size=100.0, spread=0.20, min_sl=1.0)
    if "BTC" in sym:
        return dict(asset_type="btc", contract_size=1.0, spread=15.0, min_sl=25.0)
    return dict(asset_type="eth", contract_size=1.0, spread=1.0, min_sl=2.0)


# The cached CSVs are stamped in the HOST's local time (Asia/Bangkok, UTC+7):
# the only empty hour-of-day in 61 days of XAUUSD M5 is hour 04 (2 bars), i.e.
# the CME 21:00-22:00 UTC daily break. So a file hour H == (H - 7) UTC.
def make_signal_fn(sym: str, session: str):
    """Wraps strategy_m5_scalper, adding a session gate and exposing ATR.

    session:
      'base'      -> exactly what the shipped strategy does (Gold already has its
                     own 07:00-21:00 *file-hour* filter = 00:00-14:00 UTC;
                     BTC/ETH have no filter at all)
      'ny_overlap'-> only file hours 19-22 == 12:00-15:59 UTC (true London/NY
                     overlap). Gold's own filter would block file hour 22, so
                     for Gold the hour the strategy sees is neutralised.
      'all'       -> no session filter (for Gold the internal filter is
                     neutralised by rewriting only the LAST bar's hour).
    """
    specs = _sym_specs(sym)

    def fn(window: pd.DataFrame, idx: int) -> Dict[str, Any]:
        ts = window['timestamp'].iloc[-1]
        hour = pd.to_datetime(ts).hour

        if session == "ny_overlap" and not (19 <= hour <= 22):
            return {"action": "HOLD"}

        sig_window = window
        if session != "base" and specs["asset_type"] == "gold":
            # Only the last row's hour matters to the strategy's session filter.
            tail = window.tail(60).copy()
            new_ts = pd.to_datetime(tail['timestamp'].iloc[-1]).replace(hour=12)
            tail.iloc[-1, tail.columns.get_loc('timestamp')] = new_ts
            sig_window = tail

        sig = strategy_m5_scalper(sig_window, idx, asset_type=specs["asset_type"],
                                  use_candlestick_confirmation=True)
        if sig.get("action") in ("BUY", "SELL"):
            atr_df = compute_all_indicators(sig_window.tail(50).copy())
            sig["atr"] = float(atr_df['atr_14'].iloc[-1])
        return sig

    return fn


class SweepEngine(M5BacktestEngine):
    """M5BacktestEngine + RR / SL-multiplier / trailing-BE switches."""

    def __init__(self, rr: Optional[float] = None, sl_atr_mult: Optional[float] = None,
                 be_trigger_r: Optional[float] = None, **kw):
        super().__init__(**kw)
        self.rr = rr
        self.sl_atr_mult = sl_atr_mult
        self.be_trigger_r = be_trigger_r

    def run(self, df: pd.DataFrame, signal_fn, strategy_name: str = "M5_Scalper",
            warmup_bars: int = 40) -> Dict[str, Any]:
        balance = self.initial_balance
        equity_curve: List[float] = [self.initial_balance]
        trades: List[Dict[str, Any]] = []
        open_positions: List[Dict[str, Any]] = []

        daily_pnls: Dict[str, float] = {}
        current_day_str = ""
        daily_closed_pnl = 0.0
        daily_locked = False

        n_bars = len(df)
        ticket_counter = 1
        last_entry_bar_idx = -999
        entry_intervals: List[int] = []

        for i in range(warmup_bars, n_bars):
            row = df.iloc[i]
            timestamp = row['timestamp']
            day_str = str(timestamp).split(' ')[0] if ' ' in str(timestamp) else str(timestamp)[:10]

            if day_str != current_day_str:
                if current_day_str:
                    daily_pnls[current_day_str] = round(daily_closed_pnl, 2)
                current_day_str = day_str
                daily_closed_pnl = 0.0
                daily_locked = False

            high = float(row['high'])
            low = float(row['low'])
            close_p = float(row['close'])

            # 1. (added) trailing break-even, before the SL/TP check
            if self.be_trigger_r is not None:
                for pos in open_positions:
                    entry_p = pos['entry_price']
                    r0 = abs(entry_p - pos['initial_sl'])
                    if r0 <= 0:
                        continue
                    if pos['type'] == "BUY":
                        if (high - entry_p) >= self.be_trigger_r * r0 and pos['sl'] < entry_p:
                            pos['sl'] = entry_p
                            pos['be_moved'] = True
                    else:
                        if (entry_p - low) >= self.be_trigger_r * r0 and pos['sl'] > entry_p:
                            pos['sl'] = entry_p
                            pos['be_moved'] = True

            # 2. Manage active positions (identical to M5BacktestEngine)
            remaining_positions: List[Dict[str, Any]] = []
            for pos in open_positions:
                pos_type = pos['type']
                entry_p = pos['entry_price']
                sl_p = pos['sl']
                tp_p = pos['tp']
                lots = pos['lots']

                exit_price = None
                exit_reason = None

                if pos_type == "BUY":
                    if high >= tp_p:
                        exit_price = tp_p
                        exit_reason = "TP_HIT"
                    elif low <= sl_p:
                        exit_price = sl_p
                        exit_reason = "SL_HIT" if not pos.get('be_moved') else "BE_HIT"
                else:
                    if low <= tp_p:
                        exit_price = tp_p
                        exit_reason = "TP_HIT"
                    elif high >= sl_p:
                        exit_price = sl_p
                        exit_reason = "SL_HIT" if not pos.get('be_moved') else "BE_HIT"

                if exit_price is not None:
                    if pos_type == "BUY":
                        pnl = (exit_price - entry_p - self.spread) * lots * self.contract_size
                    else:
                        pnl = (entry_p - exit_price - self.spread) * lots * self.contract_size

                    balance += pnl
                    daily_closed_pnl += pnl
                    pos['exit_price'] = exit_price
                    pos['exit_time'] = timestamp
                    pos['exit_reason'] = exit_reason
                    pos['pnl_usd'] = round(pnl, 2)
                    pos['balance_after'] = round(balance, 2)
                    trades.append(pos)
                else:
                    remaining_positions.append(pos)

            open_positions = remaining_positions

            # 3. Daily risk limits
            daily_target_usd = balance * self.daily_target_pct
            daily_max_loss_usd = balance * self.daily_max_loss_pct
            if daily_closed_pnl >= daily_target_usd:
                daily_locked = True
            elif daily_closed_pnl <= -daily_max_loss_usd:
                daily_locked = True

            # 4. New entries
            can_enter_slot = len(open_positions) < self.max_open_positions
            can_enter_cooldown = (i - last_entry_bar_idx) >= self.cooldown_bars

            if not daily_locked and can_enter_slot and can_enter_cooldown:
                window = df.iloc[:i + 1]
                signal = signal_fn(window, i)
                action = signal.get("action", "HOLD")

                if action in ["BUY", "SELL"]:
                    sl_candidate = signal.get("sl")
                    tp_candidate = signal.get("tp")
                    atr = signal.get("atr")

                    sl_dist = abs(close_p - sl_candidate) if sl_candidate else self.min_sl_dist
                    if self.sl_atr_mult is not None and atr:
                        sl_dist = self.sl_atr_mult * atr
                        sl_candidate = None  # re-anchor below
                    sl_dist = max(sl_dist, self.min_sl_dist)

                    if sl_candidate is None:
                        sl_candidate = close_p - sl_dist if action == "BUY" else close_p + sl_dist
                    if self.rr is not None:
                        sign = 1 if action == "BUY" else -1
                        tp_candidate = round(close_p + sign * sl_dist * self.rr,
                                             _price_precision_for(close_p))
                    elif tp_candidate is None:
                        tp_dist = sl_dist * 1.5
                        tp_candidate = close_p + tp_dist if action == "BUY" else close_p - tp_dist

                    risk_usd = balance * self.risk_per_trade_pct
                    raw_lot = risk_usd / (sl_dist * self.contract_size)
                    lot = max(0.01, min(round(raw_lot, 2), 5.0))

                    new_pos = {
                        "ticket": ticket_counter,
                        "type": action,
                        "entry_price": close_p,
                        "lots": lot,
                        "sl": sl_candidate,
                        "initial_sl": sl_candidate,
                        "tp": tp_candidate,
                        "entry_time": timestamp,
                        "entry_bar": i,
                        "strategy": strategy_name,
                        "reason": signal.get("reason", "M5 Scalp"),
                        "risk_usd": round(abs(close_p - sl_candidate) * lot * self.contract_size, 2),
                    }
                    ticket_counter += 1
                    open_positions.append(new_pos)

                    if last_entry_bar_idx > 0:
                        entry_intervals.append((i - last_entry_bar_idx) * 5)
                    last_entry_bar_idx = i

            floating_pnl = 0.0
            for pos in open_positions:
                if pos['type'] == "BUY":
                    floating_pnl += (close_p - pos['entry_price'] - self.spread) * pos['lots'] * self.contract_size
                else:
                    floating_pnl += (pos['entry_price'] - close_p - self.spread) * pos['lots'] * self.contract_size
            equity_curve.append(round(balance + floating_pnl, 2))

        final_row = df.iloc[-1]
        final_close = float(final_row['close'])
        for pos in open_positions:
            if pos['type'] == "BUY":
                pnl = (final_close - pos['entry_price'] - self.spread) * pos['lots'] * self.contract_size
            else:
                pnl = (pos['entry_price'] - final_close - self.spread) * pos['lots'] * self.contract_size
            balance += pnl
            pos['exit_price'] = final_close
            pos['exit_time'] = final_row['timestamp']
            pos['exit_reason'] = "SESSION_END"
            pos['pnl_usd'] = round(pnl, 2)
            pos['balance_after'] = round(balance, 2)
            trades.append(pos)

        metrics = calculate_performance_metrics(
            initial_balance=self.initial_balance,
            equity_curve=equity_curve,
            trades=trades,
            daily_pnls=daily_pnls,
            target_daily_pct=self.daily_target_pct,
        )
        metrics["strategy_name"] = strategy_name
        metrics["trades"] = trades
        metrics["avg_minutes_between_trades"] = round(float(np.mean(entry_intervals)), 1) if entry_intervals else 0.0
        metrics["total_bars"] = n_bars
        metrics["trades_per_day"] = round(len(trades) / max(len(daily_pnls), 1), 1)
        return metrics


# ---------------------------------------------------------------- config grid
# rr / sl_mult = None means "exactly the shipped strategy values" (TP 1.8*ATR, SL 1.25*ATR).
BASE = dict(rr=None, sl_mult=None, be=None, session="base", maxpos=3, maxloss=0.02)

CONFIGS: List[Dict[str, Any]] = [
    # --- gold: full grid -------------------------------------------------
    dict(id="G01_baseline", **BASE),
    dict(id="G02_rr1.5", **{**BASE, "rr": 1.5}),
    dict(id="G03_rr2.0", **{**BASE, "rr": 2.0}),
    dict(id="G04_rr2.5", **{**BASE, "rr": 2.5}),
    dict(id="G05_sl1.0_rr2.0", **{**BASE, "rr": 2.0, "sl_mult": 1.0}),
    dict(id="G06_sl1.5_rr2.0", **{**BASE, "rr": 2.0, "sl_mult": 1.5}),
    dict(id="G07_be0.6_rr2.0", **{**BASE, "rr": 2.0, "be": 0.6}),
    dict(id="G08_be1.0_rr2.0", **{**BASE, "rr": 2.0, "be": 1.0}),
    dict(id="G09_nyoverlap_rr2.0", **{**BASE, "rr": 2.0, "session": "ny_overlap"}),
    dict(id="G10_allday_rr2.0", **{**BASE, "rr": 2.0, "session": "all"}),
    dict(id="G11_maxpos1_rr2.0", **{**BASE, "rr": 2.0, "maxpos": 1}),
    dict(id="G12_be0.6_maxpos1_rr2.0", **{**BASE, "rr": 2.0, "be": 0.6, "maxpos": 1}),
    # exploratory combos of the two axes that each looked good on their own
    dict(id="G13_allday_rr2.5", **{**BASE, "rr": 2.5, "session": "all"}),
    dict(id="G14_allday_rr2.0_maxpos1", **{**BASE, "rr": 2.0, "session": "all", "maxpos": 1}),
]

# --- BTC / ETH: smaller grid (the axes that can plausibly matter there) --
CONFIGS_CRYPTO: List[Dict[str, Any]] = [
    dict(id="C01_baseline", **BASE),
    dict(id="C02_rr2.0", **{**BASE, "rr": 2.0}),
    dict(id="C03_rr2.5", **{**BASE, "rr": 2.5}),
    dict(id="C04_be0.6_rr2.0", **{**BASE, "rr": 2.0, "be": 0.6}),
    dict(id="C05_nyoverlap_rr2.0", **{**BASE, "rr": 2.0, "session": "ny_overlap"}),
    dict(id="C06_maxpos1_rr2.0", **{**BASE, "rr": 2.0, "maxpos": 1}),
]


def run_config(sym: str, df: pd.DataFrame, cfg: Dict[str, Any], split_idx: int) -> Dict[str, Any]:
    specs = _sym_specs(sym)
    engine = SweepEngine(
        initial_balance=10000.0,
        risk_per_trade_pct=0.005,
        daily_target_pct=0.03,
        daily_max_loss_pct=cfg.get("maxloss", 0.02),
        spread=specs["spread"],
        contract_size=specs["contract_size"],
        max_open_positions=cfg["maxpos"],
        cooldown_bars=2,
        min_sl_dist=specs["min_sl"],
        rr=cfg["rr"],
        sl_atr_mult=cfg["sl_mult"],
        be_trigger_r=cfg["be"],
    )
    sig = make_signal_fn(sym, cfg["session"])

    segments = [("IS", df.iloc[:split_idx].reset_index(drop=True))]
    if split_idx < len(df):
        segments.append(("OOS", df.iloc[split_idx:].reset_index(drop=True)))

    out = {"id": cfg["id"], "symbol": sym, "cfg": cfg}
    for tag, seg in segments:
        t0 = time.time()
        m = engine.run(seg, sig, strategy_name=f"M5_{sym}_{cfg['id']}")
        trades = m.pop("trades")
        r_multiples = [t['pnl_usd'] / t['risk_usd'] for t in trades if t.get('risk_usd')]
        m["expectancy_r"] = round(float(np.mean(r_multiples)), 3) if r_multiples else 0.0
        m["avg_r_win"] = round(float(np.mean([r for r in r_multiples if r > 0])), 3) if any(r > 0 for r in r_multiples) else 0.0
        m["avg_r_loss"] = round(float(np.mean([r for r in r_multiples if r < 0])), 3) if any(r < 0 for r in r_multiples) else 0.0
        m["be_exits"] = sum(1 for t in trades if t.get('exit_reason') == "BE_HIT")
        m["sl_exits"] = sum(1 for t in trades if t.get('exit_reason') == "SL_HIT")
        m["tp_exits"] = sum(1 for t in trades if t.get('exit_reason') == "TP_HIT")
        m["date_from"] = str(seg['timestamp'].iloc[0])
        m["date_to"] = str(seg['timestamp'].iloc[-1])
        m["seg"] = tag
        m["runtime_sec"] = round(time.time() - t0, 1)
        out[tag] = m
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--configs", default="full")
    ap.add_argument("--out", default=None)
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--only", default=None, help="comma-separated config ids to run")
    args = ap.parse_args()

    sym = args.symbol.upper()
    df = load_historical_data(symbol=sym, timeframe="M5")
    df = df.dropna().reset_index(drop=True)
    split_idx = int(len(df) * 0.7)

    # Fidelity check: the baseline config must reproduce run_single_asset_m5_backtest.
    if args.verify:
        from backtest.run_m5_backtest import run_single_asset_m5_backtest
        ref = run_single_asset_m5_backtest(symbol=sym)
        baseline_cfg = dict(CONFIGS[0])
        mine = run_config(sym, df, baseline_cfg, len(df))
        keys = ["total_trades", "win_rate_pct", "profit_factor", "total_return_pct",
                "max_drawdown_pct", "net_profit"]
        print("VERIFY", sym)
        for k in keys:
            print(f"  {k:20s} ref={ref[k]!r:>12} mine={mine['IS'][k]!r}")
        same = all(abs(float(ref[k]) - float(mine['IS'][k])) < 1e-6 for k in keys)
        print("  IDENTICAL:", same)
        if not same:
            print("  !! baseline mismatch -- do not trust the sweep numbers")

    configs = CONFIGS if args.configs == "full" else CONFIGS_CRYPTO
    if args.only:
        wanted = {s.strip() for s in args.only.split(",")}
        configs = [c for c in configs if c["id"] in wanted]
        if not configs:
            raise SystemExit(f"no config matched --only={args.only}")
    results = []
    for cfg in configs:
        t0 = time.time()
        r = run_config(sym, df, cfg, split_idx)
        results.append(r)
        is_m, oos_m = r["IS"], r["OOS"]
        print(f"{cfg['id']:<26} IS n={is_m['total_trades']:>4} ret={is_m['total_return_pct']:>7.2f}% "
              f" pf={is_m['profit_factor']:>4.2f} exp={is_m['expectancy_r']:>6.3f}R dd={is_m['max_drawdown_pct']:>5.2f}% | "
              f"OOS n={oos_m['total_trades']:>4} ret={oos_m['total_return_pct']:>7.2f}% pf={oos_m['profit_factor']:>4.2f} "
              f"exp={oos_m['expectancy_r']:>6.3f}R dd={oos_m['max_drawdown_pct']:>5.2f}%  [{time.time()-t0:.0f}s]",
              flush=True)

    payload = {
        "symbol": sym,
        "bars": len(df),
        "split_idx": split_idx,
        "is_range": [str(df['timestamp'].iloc[0]), str(df['timestamp'].iloc[split_idx - 1])],
        "oos_range": [str(df['timestamp'].iloc[split_idx]), str(df['timestamp'].iloc[-1])],
        "results": results,
    }
    out = Path(args.out) if args.out else RESEARCH_DIR / f"sweep_{sym.lower()}.json"
    out.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    print("WROTE", out)


if __name__ == "__main__":
    main()
