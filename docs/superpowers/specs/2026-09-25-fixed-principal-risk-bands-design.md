# Fixed-Principal Baseline & 3-Tier Drawdown Risk Bands — Design Spec

Date: 2026-09-25

## Problem

Two related, confirmed issues in `agents/squad_manager.py`'s daily risk math:

**1. Daily baseline compounds instead of staying fixed.**

`self.starting_portfolio_balance` (`agents/squad_manager.py:151`, refreshed at
`agents/squad_manager.py:227` in `check_new_session()`) is set from
`_day_baseline(self.initial_balance)` (`agents/squad_manager.py:214-218`),
which calls `risk/manager.py::day_baseline()`. On every new UTC day, that
function persists **the broker's live balance at that moment** as the day's
baseline. This value is then used as the denominator for every daily-percent
calculation: `daily_return_pct`, `equity_return_pct`
(`agents/squad_manager.py:259-260`), `max_loss_reached`
(`agents/squad_manager.py:264`), `target_profit_usd`,
`hard_target_profit_usd`, `max_loss_usd`
(`agents/squad_manager.py:155-157`, `228-230`), and the portfolio open-risk
budget gate (`agents/squad_manager.py:337`, `409`).

Confirmed with the user (2026-09-25): they deposited 20,000 THB into the real
MT5 account, but want only **10,000 THB (~$300 USD)** used as the fixed
reference capital for every daily percentage calculation, forever — not the
live account balance, which the current code silently substitutes in on
every new day. Verified via a 7-day worked simulation the user confirmed as
correct ("ถูกต้องตามนี้"): the real account balance keeps compounding day to
day exactly as today (nothing about real broker equity changes), but the
percentage denominator for target/recovery/cutoff decisions must stay pinned
to the fixed $300 figure on every single day, never the rolling balance.

Today's per-day dollar P&L tracking itself (today's opening balance vs.
current balance/equity) is correct and must NOT change — only the
denominator used to turn that dollar P&L into a percentage changes.

**2. Single loss threshold, no graduated response.**

`config.daily_max_loss_pct` (`config.py:21`, currently `0.03`) is the only
loss threshold. At -3% the squad force-closes every position and halts
entirely for the day (`agents/squad_manager.py:326-334`). Confirmed with the
user (2026-09-25, prior AskUserQuestion rounds in this session): they want a
graduated response instead:
- 0% to -3%: unchanged, each specialist trades its normal fixed strategy.
- -3% to -5% ("RECOVERY band"): new position entries switch to a
  genuinely different, lower-historical-drawdown strategy per specialist
  (not the same strategy at reduced size, and not a fictional
  "guaranteed-win" strategy — user explicitly rejected both after being
  told no strategy wins 100%). Already-open positions are left alone,
  riding their existing SL/TP untouched.
- -5% ("HALT"): same hard-stop behavior as today's -3% cutoff — close
  everything, halt the squad for the rest of the day — just retargeted to
  the new -5% number.

## Goal

1. Introduce a single fixed reference capital (`config.fixed_principal_usd`)
   used as the denominator for all four daily percentage metrics (soft
   target, hard target, new recovery threshold, max loss threshold),
   decoupled from the live/compounding account balance. The existing
   per-day dollar P&L tracking mechanism (`_day_baseline`/`day_baseline()`,
   today's opening balance vs. current balance) is unchanged — it still
   answers "how many dollars did today's trading make or lose," which
   continues to require the real live balance at the start of today. Only
   the number that dollar P&L is divided by to get a percentage changes.
2. Add the -3%/-5% two-tier loss response described above.

**Explicitly out of scope:**
- Picking the exact recovery strategy per specialist by intuition — this
  spec defines the mechanism only; the actual strategy assignment is
  data-driven from a backtest run performed before implementation (see
  Architecture, "Recovery strategy selection").
- The loss-review harness agent (2-consecutive-HALT-day analysis and
  sandboxed strategy authoring) — separate spec,
  `docs/superpowers/specs/2026-09-25-loss-review-harness-agent-design.md`.
  That system's automated backtest gate and "beat the specialist's current
  live strategy" comparison both depend on this spec's fixed-principal
  math and recovery-band mechanism already existing, so this spec must
  ship first.
- Changing the lot-sizing formula itself, or any specialist's SL/TP logic.
- Any change to `risk/manager.py::day_baseline()` or
  `load_daily_trade_state()` — both remain exactly as they are; they still
  correctly answer "what was the real account state at the start of
  today," which this spec still needs.

## Architecture

### `config.py`

Add:
```python
fixed_principal_usd: float = 300.0  # ~10,000 THB; the user's chosen reference
    # capital for ALL daily % calculations (soft/hard target, recovery,
    # max loss) -- deliberately independent of the live/compounding
    # account balance, which may be higher (the account also holds THB
    # deposited beyond this reference amount) or may drift from trading
    # results. Confirmed 2026-09-25; update this single constant if the
    # exact USD conversion of 10,000 THB needs correcting later.
daily_recovery_loss_pct: float = 0.03  # -3%: new entries switch to each
    # specialist's designated recovery strategy; open positions untouched.
```

Change:
```python
daily_max_loss_pct: float = 0.05  # was 0.03; -5% hard stop (close everything, halt for the day)
```

### `agents/squad_manager.py`

**New attributes in `__init__` (near `agents/squad_manager.py:151-157`):**
```python
self.fixed_principal_usd: float = config.fixed_principal_usd
self.recovery_loss_pct: float = config.daily_recovery_loss_pct
```
`self.starting_portfolio_balance` stays exactly as it is today (still
sourced from `_day_baseline`) — it continues to mean "today's opening real
balance," used only for the P&L numerator.

**Denominator swap.** Everywhere `self.starting_portfolio_balance` is
currently used as a percentage denominator or to scale a threshold into a
dollar amount, replace it with `self.fixed_principal_usd`. Everywhere it is
used as the P&L numerator's reference point (today's actual opening
balance), leave it unchanged. Concretely:

- `agents/squad_manager.py:155-157` (`target_profit_usd`,
  `hard_target_profit_usd`, `max_loss_usd`): multiply by
  `self.fixed_principal_usd` instead of `self.starting_portfolio_balance`.
  Add `self.recovery_loss_usd: float = self.fixed_principal_usd * self.recovery_loss_pct`.
- `agents/squad_manager.py:228-230` (same three lines, repeated inside
  `check_new_session()`): same swap, plus refresh `self.recovery_loss_usd`.
- `agents/squad_manager.py:259-260` (`daily_return_pct`, `equity_return_pct`):
  numerator stays `total_realized_pnl` / `equity_pnl` (both still computed
  against `self.starting_portfolio_balance` as today's opening real
  balance, unchanged); denominator becomes `self.fixed_principal_usd`.
- `agents/squad_manager.py:264` (`max_loss_reached`): unchanged shape, just
  inherits the corrected `equity_return_pct`.
- New: `recovery_reached = equity_return_pct <= -(self.recovery_loss_pct * 100.0)`,
  added next to `max_loss_reached` and returned in the same status dict
  (`agents/squad_manager.py:279` area) as a new `"recovery_reached"` key.
- `agents/squad_manager.py:337` (`portfolio_risk_reached` open-risk budget
  gate) and `:409`: both currently multiply `self.starting_portfolio_balance
  * self.max_loss_pct`; change to `self.fixed_principal_usd *
  self.max_loss_pct` for the same reason — the risk budget is a fraction of
  the fixed reference capital, not the compounding balance.

**Risk-band derivation, in `step()` (around `agents/squad_manager.py:326-345`):**
```python
if portfolio_status["max_loss_reached"]:
    # unchanged: close everything, halt for the day (same code as today,
    # just now firing at -5% instead of -3%)
    ...

risk_band = "RECOVERY" if portfolio_status["recovery_reached"] else "NORMAL"
if risk_band == "RECOVERY":
    logger.info(
        f"[Squad Manager] Portfolio recovery band entered "
        f"({portfolio_status['equity_return_pct']:.2f}%); specialists "
        f"switching new entries to their recovery strategy. Open positions unaffected."
    )

portfolio_risk_reached = ...  # unchanged
agent_results = {}
for key, agent in self.specialists.items():
    res = agent.step(allow_new_entry=(not portfolio_risk_reached), risk_band=risk_band)
    ...
```

### `agents/base_agent.py`

`step()` (`agents/base_agent.py:453`) gains a `risk_band: str = "NORMAL"`
parameter, threaded to the existing signal call site
(`agents/base_agent.py:642`):
```python
def step(self, allow_new_entry: bool = True, risk_band: str = "NORMAL") -> Dict[str, Any]:
    ...
    signal = self.evaluate_strategy_signal(df_main, risk_band)
```
The abstract method signature
(`agents/base_agent.py:160`) changes from
`def evaluate_strategy_signal(self, df: pd.DataFrame) -> Dict[str, Any]:` to
`def evaluate_strategy_signal(self, df: pd.DataFrame, risk_band: str = "NORMAL") -> Dict[str, Any]:`
so every existing subclass override keeps compiling with the default; each
of the 9 subclasses is then updated individually (below).

### Recovery strategy selection (data-gathering step, before implementation)

`backtest/strategies.py` already has 5 generic, symbol-agnostic strategy
functions usable outside their currently-assigned specialist:
`strategy_ema_pullback`, `strategy_sr_breakout`, `strategy_bb_reversion`,
`strategy_mtf_momentum`, `strategy_agentic_confluence`. Before writing the
implementation plan, run the existing CLI once per symbol —
`python3 main.py backtest --market=<symbol> --timeframe=M15` — for all 9
symbols (this dispatches to `evaluate_market_strategies()`, which already
back-tests all 5 strategies per symbol and reports Max DD for each,
per `backtest/run_cross_market_comparison.py:56-73`). For each specialist,
the plan hardcodes an import of whichever of the 5 strategies showed the
lowest Max Drawdown for that symbol (ties broken by highest win rate) as
its recovery strategy — a plain Python import and one `if` branch per
agent file, no runtime lookup or new config table.

### The 9 specialist agent files

Each of `agents/{gold,btc,eth,eur,gbp,xag,xpt,ukoil,xng}_agent.py` gets:
1. One new import line for its assigned recovery strategy function (if it
   isn't already imported for its normal path).
2. `evaluate_strategy_signal` signature gains `risk_band: str = "NORMAL"`.
3. One new `if risk_band == "RECOVERY": return <recovery_fn>(df, current_idx=len(df) - 1)`
   branch, placed before the existing normal-path return(s). Gold's M5
   branch (`agents/gold_agent.py:85-88`) is untouched by this — recovery
   only applies to the M15 generic-strategy path, consistent with "no
   change to M5 scalper mechanics" from the prior multi-timeframe-backtest
   spec.

### Existing open positions at any threshold

Confirmed (2026-09-25): untouched at -3%. `agent.step()`'s existing
position-management block (`agents/base_agent.py:471-490`,
`_manage_active_position`) runs identically regardless of `risk_band` —
`risk_band` only gates which function `evaluate_strategy_signal` calls for
a *new* entry decision. At -5%, the existing `_close_all_positions()` call
(`agents/squad_manager.py:327`) is unchanged — still closes everything,
exactly like today's -3% hard stop does.

## Testing

- `tests/test_agents.py` or wherever `SquadManager`'s target/loss math is
  already covered (`grep -rn "max_loss_reached\|daily_return_pct" tests/`):
  add cases asserting `daily_return_pct`/`equity_return_pct` are computed
  against `fixed_principal_usd`, not `starting_portfolio_balance`, when the
  two differ (e.g., balance grown by a prior day's profit).
  - Follow-on day scenario: simulate a session where `starting_portfolio_balance` != `fixed_principal_usd` (e.g., account already grew from a prior day) and assert the percentages match `fixed_principal_usd`-denominated math exactly, not the old balance-denominated formula.
- New test: `recovery_reached` is `True` only in the (-5%, -3%] band, `False`
  outside it (both above -3% and below -5%, where `max_loss_reached` alone
  governs).
- New test: `agent.step(risk_band="RECOVERY")` on a specialist calls the
  recovery strategy function, not the normal one; `risk_band="NORMAL"`
  (or omitted) preserves today's exact call. Existing tests that call
  `step()` without `risk_band` must keep passing unmodified (default value
  preserves current behavior byte-for-byte).
- Run `pytest tests/ -q` after each change; must stay green throughout.

## Self-Review Notes

- **Placeholder scan:** `fixed_principal_usd = 300.0` is a concrete,
  decided value (not a TBD) — the user confirmed 10,000 THB ≈ $300 from
  prior session memory and a 7-day worked simulation using that exact
  figure ("ถูกต้องตามนี้"). If the precise USD conversion needs a few
  cents' correction later, it is a one-line change to this single
  constant.
- **Internal consistency:** the P&L numerator (today's real dollar
  movement) and the % denominator (fixed reference capital) are now two
  independently-sourced numbers where they used to be the same one
  (`starting_portfolio_balance`) — this is the entire point of the fix,
  called out explicitly in Architecture and Testing so it isn't
  re-conflated during implementation.
- **Scope check:** two tightly-coupled changes to the same file
  (`squad_manager.py`'s threshold math) bundled as one spec/plan rather
  than split, since the recovery band's percentages are meaningless without
  first fixing what they're computed against.
- **Ambiguity check:** "existing open positions at -3%" was explicitly
  confirmed (left running on old SL/TP, not touched) rather than assumed.
