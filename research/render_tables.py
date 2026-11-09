"""Render markdown tables from research/sweep_*.json (read-only, research aid)."""

import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def se_approx(m):
    """Rough SE of per-trade expectancy R from a 3-outcome approximation.

    Uses only win rate + average win/loss R (two-point variance, ignores
    dispersion inside wins/losses) -> an OPTIMISTIC (too small) error bar.
    """
    n = m["total_trades"]
    if n < 2:
        return float("nan")
    p = m["wins"] / n
    w = m["avg_r_win"] or 0.0
    l = m["avg_r_loss"] or 0.0
    sigma = math.sqrt(max(p * (1 - p), 1e-9)) * (w - l)
    return sigma / math.sqrt(n)


def fmt(v, nd=2, pct=False, sign=False):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    s = f"{v:+.{nd}f}" if sign else f"{v:.{nd}f}"
    return s + ("%" if pct else "")


def main():
    out = []
    for sym, title in [("xauusd", "XAUUSD"), ("btcusd", "BTCUSD"), ("ethusd", "ETHUSD")]:
        p = HERE / f"sweep_{sym}.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        results = list(d["results"])
        extra = HERE / f"sweep_{sym}_extra.json"
        if extra.exists():
            d2 = json.loads(extra.read_text(encoding="utf-8"))
            results += d2["results"]
        out.append((d, title, results))

    for d, title, results in out:
        print(f"\n## {title}  ({d['bars']} bars)")
        print(f"IS : {d['is_range'][0]} -> {d['is_range'][1]}")
        print(f"OOS: {d['oos_range'][0]} -> {d['oos_range'][1]}")
        print("\n| Config | IS n | IS ret% | IS win% | IS PF | IS exp R | IS DD% | OOS n | OOS ret% | OOS win% | OOS PF | OOS exp R | OOS DD% |")
        print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for r in results:
            a, b = r["IS"], r["OOS"]
            print("| {id} | {n} | {r} | {w} | {pf} | {e} | {dd} | {n2} | {r2} | {w2} | {pf2} | {e2} | {dd2} |".format(
                id=r["id"], n=a["total_trades"], r=fmt(a["total_return_pct"], 2, True, True),
                w=fmt(a["win_rate_pct"], 1), pf=fmt(a["profit_factor"], 2),
                e=fmt(a["expectancy_r"], 3, False, True), dd=fmt(a["max_drawdown_pct"], 2),
                n2=b["total_trades"], r2=fmt(b["total_return_pct"], 2, True, True),
                w2=fmt(b["win_rate_pct"], 1), pf2=fmt(b["profit_factor"], 2),
                e2=fmt(b["expectancy_r"], 3, False, True), dd2=fmt(b["max_drawdown_pct"], 2)))

        print("\n| Config | OOS exp R | SE(approx) | OOS PF | OOS ret% | OOS DD% | OOS n | IS->OOS exp R | exit mix TP/BE/SL |")
        print("|---|---|---|---|---|---|---|---|---|")
        rows = sorted(results, key=lambda r: (r["OOS"]["expectancy_r"]), reverse=True)
        for r in rows:
            a, b = r["IS"], r["OOS"]
            print("| {id} | {e} | {se} | {pf} | {r} | {dd} | {n} | {d} | {tp}/{be}/{sl} |".format(
                id=r["id"], e=fmt(b["expectancy_r"], 3, False, True), se=fmt(se_approx(b), 3),
                pf=fmt(b["profit_factor"], 2), r=fmt(b["total_return_pct"], 2, True, True),
                dd=fmt(b["max_drawdown_pct"], 2), n=b["total_trades"],
                d=fmt(b["expectancy_r"] - a["expectancy_r"], 3, False, True),
                tp=b["tp_exits"], be=b["be_exits"], sl=b["sl_exits"]))


if __name__ == "__main__":
    sys.exit(main())
