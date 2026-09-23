# M15 Multi-Market Specialist Agents — Design Spec

Date: 2026-09-23

## Problem

The squad currently trades 3 live specialists (Gold, Bitcoin, Ethereum). This
session's M15 backtest research (`backtest/run_cross_market_comparison.py`)
found validated winning strategies for 6 more markets (see AGENTS.md-style
results below). None of these are deployed as live specialist agents yet.

## Scope Decomposition

This is split into two sub-projects; this spec covers only the first.

- **Sub-project A (this spec):** Deploy live M15 agents for the 6 new
  markets, directly reusing the strategy functions the M15 backtest already
  validated. Low risk, mechanical, mirrors the existing `GoldSpecialistAgent`
  pattern exactly.
- **Sub-project B (future, separate spec):** Build M5 high-frequency
  scalpers for these markets. `strategy_m5_scalper` only has bespoke,
  hand-tuned logic for gold/btc/eth (session filters, SL/TP scaling) with
  zero validation for any of the 6 new markets. Properly building this means
  a dedicated 60-day M5 research cycle per market, the same process AGENTS.md
  documents for gold/btc/eth — a much bigger, separate effort. Not started
  until this sub-project ships and is wanted.

## Validated M15 Winners (from this session's backtest)

| Symbol | Strategy | Return | Win Rate | Max DD |
|---|---|---|---|---|
| XAGUSD (Silver) | Strategy C: Bollinger Bands Reversion | +5.66% | 87.5% | 2.25% |
| GBPUSD | Strategy A: EMA Pullback Rejection | +0.01% | 50.0% | 4.52% |
| EURUSD | Strategy D: MTF Momentum Cross | +2.65% | 50.0% | 3.84% |
| XPTUSD (Platinum) | Strategy E: Agentic Multimodal Confluence | +2.33% | 60.0% | 4.51% |
| UKOIL (Brent) | Strategy C: Bollinger Bands Reversion | +3.54% | 52.9% | 15.62% |
| XNGUSD (Natural Gas) | Strategy A: EMA Pullback Rejection | +1.82% | 63.3% | 6.02% |

GBPUSD is included despite its flat return (explicit user decision — no
statistical edge, included anyway).

## Architecture

### New agent classes

One file per market, mirroring `agents/gold_agent.py`'s shape exactly:
`agents/xag_agent.py` (`SilverSpecialistAgent`), `gbp_agent.py`
(`GbpSpecialistAgent`), `eur_agent.py` (`EurSpecialistAgent`), `xpt_agent.py`
(`PlatinumSpecialistAgent`), `ukoil_agent.py` (`UkoilSpecialistAgent`),
`xng_agent.py` (`NaturalGasSpecialistAgent`).

Each subclasses `BaseSpecialistAgent`, hardcodes `timeframe="M15"`, and pulls
`contract_size`, `min_lot`, `min_sl_dist` from
`backtest.data_loader.ASSET_SPECS[symbol]` — single source of truth with the
values today's backtest already empirically validated (a real M15 stop
distance that produced real trades), instead of re-guessing separate numbers
for the live path. `evaluate_strategy_signal` calls the exact strategy
function the backtest crowned winner for that symbol
(e.g. `strategy_bb_reversion` for XAGUSD) and raises `NotImplementedError` if
`self.timeframe != "M15"` — fails loud instead of `strategy_m5_scalper`
silently returning `HOLD` forever for an unrecognized `asset_type`.

```python
class SilverSpecialistAgent(BaseSpecialistAgent):
    def __init__(self, broker=None, broker_mode="paper", initial_balance=None,
                 journal_dir=None, max_open_positions=None, min_entry_interval_sec=None):
        spec = ASSET_SPECS["XAGUSD"]
        super().__init__(
            symbol="XAGUSD", asset_name="Silver", timeframe="M15",
            contract_size=spec["contract_size"], min_lot=spec["min_lot"], max_lot=10.0,
            min_sl_dist=spec["min_sl_dist"], broker=broker, broker_mode=broker_mode,
            initial_balance=initial_balance, journal_dir=journal_dir,
            strategy_type="mean_reversion",
            max_open_positions=max_open_positions, min_entry_interval_sec=min_entry_interval_sec
        )

    @property
    def strategy_name(self) -> str:
        return "BB_Reversion_C"

    def evaluate_strategy_signal(self, df: pd.DataFrame) -> Dict[str, Any]:
        if self.timeframe != "M15":
            raise NotImplementedError("Silver only has a validated M15 strategy; M5 is a separate future spec.")
        return strategy_bb_reversion(df, current_idx=len(df) - 1)
```

The other five follow the same shape with their own symbol/spec/strategy
function: GBPUSD -> `strategy_ema_pullback`, EURUSD -> `strategy_mtf_momentum`,
XPTUSD -> `strategy_agentic_confluence`, UKOIL -> `strategy_bb_reversion`,
XNGUSD -> `strategy_ema_pullback`.

### `SquadManager` — data-driven specialist registry

Replaces the current 3 repeated if-blocks (`agents/squad_manager.py` lines
~108-131) with a registry dict, avoiding a 9-way copy-paste:

```python
SPECIALIST_REGISTRY: Dict[str, Tuple[type, str]] = {
    "gold": (GoldSpecialistAgent, "xauusd"),
    "btc": (BtcSpecialistAgent, "btcusd"),
    "eth": (EthSpecialistAgent, "ethusd"),
    "xag": (SilverSpecialistAgent, "xagusd"),
    "gbp": (GbpSpecialistAgent, "gbpusd"),
    "eur": (EurSpecialistAgent, "eurusd"),
    "xpt": (PlatinumSpecialistAgent, "xptusd"),
}
# Excluded from "all" until their contract_size is confirmed against this
# Exness account via MT5 Market Watch -> right-click -> Specification.
GATED_SPECIALISTS: Dict[str, Tuple[type, str]] = {
    "ukoil": (UkoilSpecialistAgent, "ukoil"),
    "xng": (NaturalGasSpecialistAgent, "xngusd"),
}
```

`"all"` expands to every key in `SPECIALIST_REGISTRY` (7 agents, not 9).
`"duo"` keeps its existing `["gold", "btc"]` meaning. `ukoil`/`xng` are only
reachable by explicit name (`--agent=ukoil`); a log line at squad startup
states why they're excluded from `all`. The specialist-instantiation loop in
`__init__` becomes a single loop over `{**SPECIALIST_REGISTRY, **GATED_SPECIALISTS}`
filtered by the resolved `enabled` list, instead of one `if` block per agent.

### Fix `_portfolio_open_risk_usd`'s hardcoded contract-size dict

Currently (`agents/squad_manager.py` ~line 290):
```python
contract_sizes = {"XAUUSD": 100.0, "BTCUSD": 1.0, "ETHUSD": 1.0}
...
total += distance * lots * contract_sizes.get(symbol, 1.0)
```
For any symbol not in this 3-entry dict, open risk is estimated using a
`1.0` fallback contract size. XAGUSD's real contract size is 5000; EURUSD/
GBPUSD's is 100000. An open EURUSD position's true dollar risk would be
under-counted by ~100,000x, which would let the portfolio blow through its
daily max-loss cutoff (`SquadManager.step`'s `portfolio_status["max_loss_reached"]`
gate) without the circuit breaker ever tripping. Fix: derive this dict from
`ASSET_SPECS` (already has every symbol's real `contract_size`) instead of a
hardcoded 3-entry table, covering every currently-registered specialist
symbol (not `GATED_SPECIALISTS`, since those can't have open positions until
enabled).

### CLI (`main.py`)

Extend `--agent` choices in `cmd_run`'s parser and the loop parser to include
`xag`, `gbp`, `eur`, `xpt` (registry) and `ukoil`, `xng` (gated, explicit
opt-in only) alongside the existing `all`, `duo`, `gold`, `btc`, `eth`.

## Error Handling

- `NotImplementedError` on a non-M15 timeframe for any new agent — this is a
  live-trading safety property (no silent no-op that looks like the agent is
  running but never trades), not just a nice-to-have.
- No change to existing broker/MT5 error handling paths (`BaseSpecialistAgent`
  already handles broker errors, stale telemetry, etc. uniformly for every
  symbol).

## Testing

- One test per new agent class: constructor's `contract_size`/`min_lot`/
  `min_sl_dist` match `ASSET_SPECS[symbol]`, `strategy_name` is correct,
  `evaluate_strategy_signal` raises `NotImplementedError` when constructed
  with `timeframe="M5"`.
- `SquadManager(agents_to_enable=["all"])` instantiates exactly 7 specialists
  (not 9) and does not include `ukoil`/`xng`.
- `SquadManager(agents_to_enable=["ukoil"])` (explicit) does instantiate it.
- Regression test for `_portfolio_open_risk_usd`: an open EURUSD-scale
  position (small price-distance SL, `contract_size=100000`) must produce a
  risk estimate in the same order of magnitude as
  `distance * lots * 100000`, not the old `1.0` fallback (which would be
  ~100,000x too small).

## Out of Scope

- M5 scalpers for these 6 markets (Sub-project B, separate future spec).
- UKOIL/XNGUSD's real Exness contract size verification — user will check
  MT5 Market Watch -> Specification and provide the real values; until then
  those two agents exist in code but are excluded from `all` and require
  explicit `--agent=ukoil`/`--agent=xng` to run, with the placeholder-spec
  caveat already documented in `ASSET_SPECS`.
- Per-agent risk-budget rebalancing now that up to 7 specialists share one
  portfolio daily target lock (each specialist still sizes its own trades via
  its own `risk_pct`; the shared 3%/20% lock is unchanged). Revisit only if
  real trading shows the shared budget is a problem in practice.
