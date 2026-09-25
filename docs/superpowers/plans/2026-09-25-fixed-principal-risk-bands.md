# Fixed-Principal Baseline & 3-Tier Drawdown Risk Bands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pin all daily percentage math (soft/hard target, new recovery threshold, max loss) to a fixed reference capital instead of the compounding live balance, and add a graduated -3%/-5% drawdown response (RECOVERY band switches new entries to a lower-risk strategy where one exists; -5% keeps today's full halt behavior).

**Architecture:** `config.py` gains three values; `agents/squad_manager.py` gains a constructor-overridable `fixed_principal_usd` used as the denominator everywhere `starting_portfolio_balance` currently doubles as one, plus a `risk_band` computed each iteration and threaded into `agent.step()`; `agents/base_agent.py` threads `risk_band` down to the per-specialist `evaluate_strategy_signal` hook; only `agents/xag_agent.py` gains real branching on it (real backtest data showed every other of the 9 specialists has no historically-better alternative to switch to).

**Tech Stack:** Python, pytest, existing `PaperTradingBroker`/`MT5BridgeBroker` test doubles.

## Global Constraints

- `fixed_principal_usd` default is `300.0` (≈10,000 THB) — a concrete, user-confirmed value, not a placeholder.
- `daily_max_loss_pct` changes from `0.03` to `0.05`. `daily_recovery_loss_pct` is new at `0.03`.
- The per-day dollar P&L numerator (today's real opening balance vs. current balance/equity, via `starting_portfolio_balance`/`_day_baseline`) is NEVER changed by this plan — only the percentage denominator changes.
- RECOVERY band applies only to `agents/xag_agent.py` behaviorally. All 9 specialists gain the `risk_band` parameter on `evaluate_strategy_signal` for interface consistency; only XAG's body branches on it.
- `pytest tests/ -q` must stay green after every task.

---

### Task 1: `config.py` — new/changed risk constants

**Files:**
- Modify: `config.py:21` (change), add two new lines near it
- Test: `tests/test_agents.py` (new test function, file already imports `from config import config`)

**Interfaces:**
- Produces: `config.fixed_principal_usd: float` (300.0), `config.daily_recovery_loss_pct: float` (0.03), `config.daily_max_loss_pct: float` (0.05, changed from 0.03) — consumed by Task 2.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_agents.py` (near the top, after the existing imports):

```python
def test_config_fixed_principal_and_risk_band_thresholds():
    assert config.fixed_principal_usd == 300.0
    assert config.daily_recovery_loss_pct == 0.03
    assert config.daily_max_loss_pct == 0.05
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_agents.py::test_config_fixed_principal_and_risk_band_thresholds -v`
Expected: FAIL — `AttributeError: 'TradingConfig' object has no attribute 'fixed_principal_usd'` (and/or `assert 0.03 == 0.05` once that attribute exists but before the value changes).

- [ ] **Step 3: Update `config.py`**

In `config.py`, change line 21 from:
```python
    daily_max_loss_pct: float = 0.03 # 3% max daily loss cutoff ($300 on $10,000)
```
to:
```python
    daily_max_loss_pct: float = 0.05 # 5% hard-stop max daily loss cutoff (close everything, halt for the day) -- against fixed_principal_usd, not the live balance
    daily_recovery_loss_pct: float = 0.03  # 3%: new entries switch to each specialist's designated recovery strategy (only XAG has one); open positions untouched
```
and add, right after `initial_balance: float = 10000.0` (`config.py:17`):
```python
    fixed_principal_usd: float = 300.0  # ~10,000 THB; the user's fixed reference capital for ALL daily % calculations (soft/hard target, recovery, max loss) -- deliberately independent of the live/compounding account balance
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_agents.py::test_config_fixed_principal_and_risk_band_thresholds -v`
Expected: PASS

- [ ] **Step 5: Run full suite, confirm nothing else broke yet (unrelated changes come in Task 2)**

Run: `python3 -m pytest tests/ -q`
Expected: some existing tests in `test_agents.py`/`test_strategy_enhancements.py` that hardcode 3%-based expectations will now fail (they still read `config.daily_max_loss_pct` == 0.03 implicitly via unchanged `SquadManager` code) — this is expected and fixed in Task 2, not this task. Confirm the failures are only in the areas Task 2 is scoped to touch (`test_squad_manager_portfolio_soft_target_does_not_lock`, `test_squad_manager_portfolio_hard_target_locks`, `test_live_squad_uses_terminal_balance_not_cli_default`, `test_portfolio_loss_cutoff_closes_floating_loss_positions`, `test_run_loop_pauses_on_max_loss_cutoff_instead_of_exiting`, `test_squad_manages_open_positions_when_risk_budget_exhausted`) — no other test file should newly fail. If anything outside that list fails, stop and report it rather than proceeding to Task 2.

- [ ] **Step 6: Commit**

```bash
git add config.py tests/test_agents.py
git commit -m "feat(config): add fixed_principal_usd + daily_recovery_loss_pct, bump max loss to 5%"
```

---

### Task 2: `agents/squad_manager.py` — fixed-principal denominator + RECOVERY threshold

**Files:**
- Modify: `agents/squad_manager.py` (constructor, `check_new_session`, `get_portfolio_daily_pnl`, `step`, `_portfolio_open_risk_usd`)
- Modify (fix 5 existing tests to match the new formula): `tests/test_agents.py`, `tests/test_strategy_enhancements.py`
- Test: `tests/test_agents.py` (new tests)

**Interfaces:**
- Consumes: `config.fixed_principal_usd`, `config.daily_recovery_loss_pct` (Task 1).
- Produces: `SquadManager.__init__(..., fixed_principal_usd: Optional[float] = None)`; `self.fixed_principal_usd: float`; `self.recovery_loss_pct: float`; `self.recovery_loss_usd: float`; `get_portfolio_daily_pnl()`'s returned dict gains a `"recovery_reached": bool` key; `step()` computes `risk_band: str` (`"NORMAL"` or `"RECOVERY"`) and passes it to `agent.step(risk_band=risk_band)` — consumed by Task 3.

#### Step 1: Write the failing tests

Add to `tests/test_agents.py`:

```python
def test_fixed_principal_usd_denominator_overridable(tmp_path):
    """Percentages must compute against fixed_principal_usd, not
    starting_portfolio_balance, even when the two differ (e.g. account
    already grew from a prior day's profit)."""
    broker = PaperTradingBroker(initial_balance=10000.0)
    squad = SquadManager(
        broker=broker, initial_balance=10000.0,
        fixed_principal_usd=300.0, journal_dir=tmp_path,
    )
    # Simulate a prior day's profit already baked into starting_portfolio_balance,
    # decoupled from fixed_principal_usd.
    squad.starting_portfolio_balance = 309.0
    broker.balance = 315.0
    broker.equity = 315.0

    p_stat = squad.get_portfolio_daily_pnl()
    # Numerator: today's real dollar move (315 - 309 = 6), unaffected by this change.
    assert p_stat["realized_pnl_usd"] == pytest.approx(6.0)
    # Denominator: fixed_principal_usd (300), NOT starting_portfolio_balance (309).
    assert p_stat["daily_return_pct"] == pytest.approx(2.0)  # 6 / 300 * 100


def test_recovery_reached_only_in_band(tmp_path):
    broker = PaperTradingBroker(initial_balance=10000.0)
    squad = SquadManager(
        broker=broker, initial_balance=10000.0,
        fixed_principal_usd=300.0, journal_dir=tmp_path,
    )
    squad.starting_portfolio_balance = 300.0

    # -2%: above recovery threshold (-3%) -- neither band active.
    broker.balance = 294.0
    broker.equity = 294.0
    p_stat = squad.get_portfolio_daily_pnl()
    assert p_stat["recovery_reached"] is False
    assert p_stat["max_loss_reached"] is False

    # -4%: inside (-5%, -3%] recovery band.
    broker.balance = 288.0
    broker.equity = 288.0
    p_stat = squad.get_portfolio_daily_pnl()
    assert p_stat["recovery_reached"] is True
    assert p_stat["max_loss_reached"] is False

    # -6%: past the hard -5% cutoff -- recovery_reached also stays True but
    # max_loss_reached governs (squad halts entirely, see step()).
    broker.balance = 282.0
    broker.equity = 282.0
    p_stat = squad.get_portfolio_daily_pnl()
    assert p_stat["max_loss_reached"] is True


def test_step_passes_recovery_risk_band_to_specialists(tmp_path, monkeypatch):
    broker = PaperTradingBroker(initial_balance=10000.0)
    squad = SquadManager(
        broker=broker, initial_balance=10000.0,
        fixed_principal_usd=300.0, agents_to_enable=["xag"], journal_dir=tmp_path,
    )
    squad.starting_portfolio_balance = 300.0
    broker.balance = 288.0  # -4%: inside recovery band
    broker.equity = 288.0

    seen_risk_bands = []
    original_step = squad.specialists["xag"].step
    def spy_step(*args, **kwargs):
        seen_risk_bands.append(kwargs.get("risk_band"))
        return original_step(*args, **kwargs)
    monkeypatch.setattr(squad.specialists["xag"], "step", spy_step)

    squad.step()
    assert seen_risk_bands == ["RECOVERY"]
```

Confirmed: `PaperTradingBroker` exposes mutable `self.balance`/`self.equity`
attributes (`mt4/paper_broker.py:22-23`), read directly by
`get_account_info()` (`mt4/paper_broker.py:71-76`) — setting them on the
`broker` instance in these tests is sufficient, no extra mocking needed.

#### Step 2: Run tests to verify they fail

Run: `python3 -m pytest tests/test_agents.py::test_fixed_principal_usd_denominator_overridable tests/test_agents.py::test_recovery_reached_only_in_band tests/test_agents.py::test_step_passes_recovery_risk_band_to_specialists -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'fixed_principal_usd'` (constructor doesn't accept it yet), and `KeyError: 'recovery_reached'`.

#### Step 3: Implement the `squad_manager.py` changes

**3a. Constructor.** Find `SquadManager.__init__`'s signature (`grep -n "def __init__" agents/squad_manager.py` — it's the constructor whose body contains line 151's `self.starting_portfolio_balance` assignment) and add `fixed_principal_usd: Optional[float] = None` as a parameter (matching the style of the existing `journal_dir: Optional[Path] = None` parameter already there). `Optional` is already imported in this file (used elsewhere for `Optional[Path]`/`Optional[int]` parameters) — confirm with `grep -n "^from typing" agents/squad_manager.py`; if `Optional` isn't imported, add it to that import line.

Replace lines 151-157:
```python
        self.starting_portfolio_balance: float = self._day_baseline(self.initial_balance)
        self.target_pct: float = config.daily_target_pct  # 3.0% soft: specialists derisk, portfolio keeps trading
        self.hard_target_pct: float = config.daily_target_hard_pct  # 10.0% hard: locks all trading
        self.max_loss_pct: float = config.daily_max_loss_pct  # -3.0%
        self.target_profit_usd: float = self.starting_portfolio_balance * self.target_pct
        self.hard_target_profit_usd: float = self.starting_portfolio_balance * self.hard_target_pct
        self.max_loss_usd: float = self.starting_portfolio_balance * self.max_loss_pct
```
with:
```python
        self.starting_portfolio_balance: float = self._day_baseline(self.initial_balance)
        self.fixed_principal_usd: float = fixed_principal_usd if fixed_principal_usd is not None else config.fixed_principal_usd
        self.target_pct: float = config.daily_target_pct  # 3.0% soft: specialists derisk, portfolio keeps trading
        self.hard_target_pct: float = config.daily_target_hard_pct  # 20.0% hard: locks all trading
        self.recovery_loss_pct: float = config.daily_recovery_loss_pct  # 3.0%: new entries switch to recovery strategy
        self.max_loss_pct: float = config.daily_max_loss_pct  # -5.0%: hard stop
        self.target_profit_usd: float = self.fixed_principal_usd * self.target_pct
        self.hard_target_profit_usd: float = self.fixed_principal_usd * self.hard_target_pct
        self.recovery_loss_usd: float = self.fixed_principal_usd * self.recovery_loss_pct
        self.max_loss_usd: float = self.fixed_principal_usd * self.max_loss_pct
```

**3b. `check_new_session()`.** Replace lines 228-230:
```python
            self.target_profit_usd = self.starting_portfolio_balance * self.target_pct
            self.hard_target_profit_usd = self.starting_portfolio_balance * self.hard_target_pct
            self.max_loss_usd = self.starting_portfolio_balance * self.max_loss_pct
```
with:
```python
            self.target_profit_usd = self.fixed_principal_usd * self.target_pct
            self.hard_target_profit_usd = self.fixed_principal_usd * self.hard_target_pct
            self.recovery_loss_usd = self.fixed_principal_usd * self.recovery_loss_pct
            self.max_loss_usd = self.fixed_principal_usd * self.max_loss_pct
```

**3c. `get_portfolio_daily_pnl()`.** Replace lines 259-264:
```python
        daily_return_pct = round((total_realized_pnl / self.starting_portfolio_balance) * 100.0, 2) if self.starting_portfolio_balance > 0 else 0.0
        equity_return_pct = round((equity_pnl / self.starting_portfolio_balance) * 100.0, 2) if self.starting_portfolio_balance > 0 else 0.0

        target_reached = daily_return_pct >= (self.target_pct * 100.0)
        hard_target_reached = daily_return_pct >= (self.hard_target_pct * 100.0)
        max_loss_reached = equity_return_pct <= -(self.max_loss_pct * 100.0)
```
with:
```python
        daily_return_pct = round((total_realized_pnl / self.fixed_principal_usd) * 100.0, 2) if self.fixed_principal_usd > 0 else 0.0
        equity_return_pct = round((equity_pnl / self.fixed_principal_usd) * 100.0, 2) if self.fixed_principal_usd > 0 else 0.0

        target_reached = daily_return_pct >= (self.target_pct * 100.0)
        hard_target_reached = daily_return_pct >= (self.hard_target_pct * 100.0)
        recovery_reached = equity_return_pct <= -(self.recovery_loss_pct * 100.0)
        max_loss_reached = equity_return_pct <= -(self.max_loss_pct * 100.0)
```
(the numerators `total_realized_pnl`/`equity_pnl` on lines 252/257 are untouched — both still computed against `self.starting_portfolio_balance`, today's real opening balance)

Add `"recovery_reached": recovery_reached,` to the returned dict, next to the existing `"max_loss_reached": max_loss_reached,` line (`agents/squad_manager.py:279`).

**3d. `_portfolio_open_risk_usd()`.** Line 409: change
```python
                return self.starting_portfolio_balance * self.max_loss_pct
```
to
```python
                return self.fixed_principal_usd * self.max_loss_pct
```

**3e. `step()`.** Line 337: change
```python
        portfolio_risk_reached = self._portfolio_open_risk_usd() >= (self.starting_portfolio_balance * self.max_loss_pct)
```
to
```python
        portfolio_risk_reached = self._portfolio_open_risk_usd() >= (self.fixed_principal_usd * self.max_loss_pct)
```

Then, between the `max_loss_reached` block (ending at line 335) and the `portfolio_risk_reached` line (337), insert:
```python
        risk_band = "RECOVERY" if portfolio_status["recovery_reached"] else "NORMAL"
        if risk_band == "RECOVERY":
            logger.info(
                f"[Squad Manager] Portfolio recovery band entered "
                f"({portfolio_status['equity_return_pct']:.2f}%); specialists "
                f"switching new entries to their recovery strategy. Open positions unaffected."
            )
```
and change the specialist loop (lines 339-342) from:
```python
        for key, agent in self.specialists.items():
            try:
                res = agent.step(allow_new_entry=(not portfolio_risk_reached))
```
to:
```python
        for key, agent in self.specialists.items():
            try:
                res = agent.step(allow_new_entry=(not portfolio_risk_reached), risk_band=risk_band)
```
(this line will fail with `TypeError: step() got an unexpected keyword argument 'risk_band'` until Task 3 adds the parameter to `BaseSpecialistAgent.step()` — expected; Task 2 and Task 3 are both required before this specific line works end-to-end. `test_step_passes_recovery_risk_band_to_specialists` above uses a monkeypatched `step` spy, so it does not depend on the real `step()` accepting the kwarg, and will pass after this task alone.)

#### Step 4: Fix the 5 existing tests broken by the denominator change

In `tests/test_agents.py`:

- `test_squad_manager_portfolio_soft_target_does_not_lock` and
  `test_squad_manager_portfolio_hard_target_locks`: add
  `fixed_principal_usd=10000.0` to each `SquadManager(...)` call, e.g.
  `SquadManager(broker=broker, initial_balance=10000.0, fixed_principal_usd=10000.0, journal_dir=tmp_path)`.
- `test_live_squad_uses_terminal_balance_not_cli_default`: leave the
  `SquadManager(...)` construction unchanged (no `fixed_principal_usd`
  override — this test is specifically about `starting_balance` reflecting
  the live terminal balance, not the `initial_balance` default). Change
  `assert status["target_profit_usd"] == 15.0` to
  `assert status["target_profit_usd"] == 9.0` (default `fixed_principal_usd`
  300.0 × `target_pct` 0.03). Update the class comment
  `# -4% equity, past the 3% max loss cutoff` to
  `# -6.67% equity against the fixed $300 principal, past the 5% max loss cutoff`.
- `test_portfolio_loss_cutoff_closes_floating_loss_positions` and
  `test_run_loop_pauses_on_max_loss_cutoff_instead_of_exiting`: after the
  existing `squad.starting_portfolio_balance = 10_000.0` line in each, add
  `squad.fixed_principal_usd = 5_000.0` (the $300 floating loss from the
  simulated price move is then -6% against 5000, past the new -5%
  threshold, so `PORTFOLIO_MAX_LOSS_CUTOFF` still fires as both tests
  require).

In `tests/test_strategy_enhancements.py`, `test_squad_manages_open_positions_when_risk_budget_exhausted`
(line 182): change
```python
    assert squad._portfolio_open_risk_usd() >= squad.starting_portfolio_balance * squad.max_loss_pct
```
to
```python
    assert squad._portfolio_open_risk_usd() >= squad.fixed_principal_usd * squad.max_loss_pct
```

#### Step 5: Run tests to verify they pass

Run: `python3 -m pytest tests/test_agents.py tests/test_strategy_enhancements.py -v`
Expected: `test_fixed_principal_usd_denominator_overridable` and
`test_recovery_reached_only_in_band` PASS.
`test_step_passes_recovery_risk_band_to_specialists` PASS (uses a
monkeypatched spy, doesn't need Task 3).
The 6 previously-broken tests now PASS again.
Other tests in these two files that call `agent.step()` directly (not
through `squad.step()`) are unaffected by this task.

Run: `python3 -m pytest tests/ -q`
Expected: failures only in tests that call `squad.step()` end-to-end (not
via a monkeypatched specialist `step`) and therefore hit the
`risk_band=risk_band` kwarg on the real (not-yet-updated)
`BaseSpecialistAgent.step()` — e.g. `test_squad_manager_portfolio_soft_target_does_not_lock`'s
own `step()` call, `test_run_loop_pauses_on_max_loss_cutoff_instead_of_exiting`,
`test_squad_manages_open_positions_when_risk_budget_exhausted`, and any
other test that runs a full `squad.step()` or `squad.run_loop()`. This is
expected — Task 3 fixes it. Confirm the failure in each case is exactly
`TypeError: step() got an unexpected keyword argument 'risk_band'`, not
something else; if any failure has a different message, stop and
investigate before proceeding to Task 3.

#### Step 6: Commit

```bash
git add agents/squad_manager.py tests/test_agents.py tests/test_strategy_enhancements.py
git commit -m "feat(squad): fixed-principal % denominator + RECOVERY band threshold"
```

---

### Task 3: `agents/base_agent.py` — thread `risk_band` through `step()`

**Files:**
- Modify: `agents/base_agent.py` (abstract method signature, `step()` signature and call site)
- Test: `tests/test_agents.py` (new test)

**Interfaces:**
- Consumes: `agent.step(risk_band=...)` calls from Task 2.
- Produces: `BaseSpecialistAgent.step(self, allow_new_entry: bool = True, risk_band: str = "NORMAL")`; abstract `evaluate_strategy_signal(self, df: pd.DataFrame, risk_band: str = "NORMAL") -> Dict[str, Any]` — consumed by Task 4 (each of the 9 concrete overrides).

#### Step 1: Write the failing test

Add to `tests/test_agents.py`:

```python
def test_base_agent_step_threads_risk_band_to_evaluate_strategy_signal(temp_journal_dir, monkeypatch):
    broker = PaperTradingBroker(initial_balance=10000.0)
    agent = GoldSpecialistAgent(broker=broker, journal_dir=temp_journal_dir / "xauusd", timeframe="M15")

    seen = []
    def fake_evaluate(df, risk_band="NORMAL"):
        seen.append(risk_band)
        return {"action": "HOLD"}
    monkeypatch.setattr(agent, "evaluate_strategy_signal", fake_evaluate)

    n = 60
    mock_df = pd.DataFrame({
        "timestamp": pd.date_range("2026-08-01 10:00", periods=n, freq="15min"),
        "open": [2000.0] * n, "high": [2001.0] * n, "low": [1999.0] * n,
        "close": [2000.0] * n, "volume": [100] * n,
    })
    agent.broker.get_market_data = lambda symbol, timeframe="M15", bars=60: mock_df.copy()

    agent.step(risk_band="RECOVERY")
    assert seen == ["RECOVERY"]

    agent.step()  # default
    assert seen == ["RECOVERY", "NORMAL"]
```

Confirmed: `step()`'s main signal-path fetch is `self.broker.get_market_data(symbol=self.symbol, timeframe=self.timeframe, bars=60)` (`agents/base_agent.py:584`) — `n=60` in `mock_df` matches exactly, and this row count is already proven sufficient by the existing `test_cadence_pacer_periodic_entry` test in `tests/test_strategy_enhancements.py`, which runs a real `agent.step()` end-to-end on a 60-row mock frame.

#### Step 2: Run test to verify it fails

Run: `python3 -m pytest tests/test_agents.py::test_base_agent_step_threads_risk_band_to_evaluate_strategy_signal -v`
Expected: FAIL — `TypeError: step() got an unexpected keyword argument 'risk_band'`.

#### Step 3: Implement

In `agents/base_agent.py`, change the abstract method (line 160) from:
```python
    def evaluate_strategy_signal(self, df: pd.DataFrame) -> Dict[str, Any]:
```
to:
```python
    def evaluate_strategy_signal(self, df: pd.DataFrame, risk_band: str = "NORMAL") -> Dict[str, Any]:
```

Change `step()`'s signature (line 453) from:
```python
    def step(self, allow_new_entry: bool = True) -> Dict[str, Any]:
```
to:
```python
    def step(self, allow_new_entry: bool = True, risk_band: str = "NORMAL") -> Dict[str, Any]:
```

Change the call site (line 642) from:
```python
        signal = self.evaluate_strategy_signal(df_main)
```
to:
```python
        signal = self.evaluate_strategy_signal(df_main, risk_band)
```

#### Step 4: Run test to verify it passes

Run: `python3 -m pytest tests/test_agents.py::test_base_agent_step_threads_risk_band_to_evaluate_strategy_signal -v`
Expected: PASS

#### Step 5: Run full suite

Run: `python3 -m pytest tests/ -q`
Expected: all previously-listed Task 2 failures (the `TypeError: step()
got an unexpected keyword argument 'risk_band'` ones) now pass, since
`step()` accepts the parameter. Any remaining failure must be investigated
before Task 4 — at this point the only still-acceptable failures are ones
where a concrete `evaluate_strategy_signal` override doesn't yet accept
`risk_band` (fixed in Task 4). Confirm any remaining failures are exactly
`TypeError: evaluate_strategy_signal() got an unexpected keyword argument 'risk_band'`
or `TypeError: ...evaluate_strategy_signal() takes 2 positional arguments but 3 were given`.

#### Step 6: Commit

```bash
git add agents/base_agent.py tests/test_agents.py
git commit -m "feat(base-agent): thread risk_band through step() to evaluate_strategy_signal"
```

---

### Task 4: The 9 specialist agent files + 5 test-mock signature fixes

**Scope note (added after Task 3's implementation):** Task 3 made
`agents/base_agent.py::step()` call
`self.evaluate_strategy_signal(df_main, risk_band)` — 2 positional args,
always. This breaks not only the 9 real subclass overrides (fixed below)
but also every test that monkeypatches `agent.evaluate_strategy_signal`
with a bare one-argument `lambda df: {...}` — the lambda receives the same
2-positional-arg call and raises `TypeError: <lambda>() takes 1 positional
argument but 2 were given`. Task 3's implementer found and enumerated
exactly 5 such tests while verifying the full suite; this task now also
fixes those 5, in addition to its original 9-agent-file scope.

**Files:**
- Modify: `agents/gold_agent.py:81`, `agents/btc_agent.py:61`, `agents/eth_agent.py:62`,
  `agents/eur_agent.py:57`, `agents/gbp_agent.py:58`, `agents/xpt_agent.py:57`,
  `agents/ukoil_agent.py:63`, `agents/xng_agent.py:63` (signature-only)
- Modify: `agents/xag_agent.py:13,57` (real behavioral branch)
- Modify: `tests/test_agent_concurrency.py:62,88`, `tests/test_mt5_bridge.py:332`,
  `tests/test_strategy_enhancements.py:70,133` (5 test-mock lambda signatures)
- Test: `tests/test_new_market_agents.py` (new), `tests/test_agents.py` (spot checks for gold/btc/eth)

#### Step 0: Fix the 5 test-mock lambda signatures

In each of these 5 locations, the existing monkeypatch is a bare one-arg
lambda standing in for a real specialist's `evaluate_strategy_signal`. Change
each from `lambda df: <body>` to `lambda df, risk_band="NORMAL": <body>` —
same pattern as the real abstract method's new default, ignoring the new
parameter since these tests don't exercise risk-band routing:

- `tests/test_agent_concurrency.py:62`: `agent.evaluate_strategy_signal = lambda df: {...}` → add `, risk_band="NORMAL"` after `df`
- `tests/test_agent_concurrency.py:88`: same pattern
- `tests/test_mt5_bridge.py:332`: same pattern
- `tests/test_strategy_enhancements.py:70`: same pattern
- `tests/test_strategy_enhancements.py:133`: same pattern (this is
  `test_cadence_pacer_periodic_entry` — the same test Task 3's brief cited
  as proof `n=60` mock rows are sufficient; confirm that reasoning still
  holds once this lambda is fixed, since it's now failing for the
  unrelated signature reason, not a row-count reason)

Run `grep -n "evaluate_strategy_signal = lambda" tests/*.py` first to
confirm these are the only 5 occurrences (Task 3's implementer's list) —
if you find a 6th, fix it too and note it in your report.

**Interfaces:**
- Consumes: `evaluate_strategy_signal(self, df, risk_band: str = "NORMAL")` abstract shape from Task 3.
- Produces: nothing further consumed by later tasks (this plan's last task).

#### Step 1: Write the failing tests

Add to `tests/test_new_market_agents.py`:

```python
import backtest.strategies as strategies


def test_xag_recovery_band_switches_to_agentic_confluence(broker, monkeypatch):
    from agents.xag_agent import SilverSpecialistAgent
    import agents.xag_agent as xag_module
    agent = SilverSpecialistAgent(broker=broker)
    df = pd.DataFrame({"close": [1.0, 2.0, 3.0]})

    monkeypatch.setattr(xag_module, "strategy_bb_reversion",
                         lambda df, current_idx: {"action": "HOLD", "picked": "normal"})
    monkeypatch.setattr(xag_module, "strategy_agentic_confluence",
                         lambda df, current_idx: {"action": "HOLD", "picked": "recovery"})

    assert agent.evaluate_strategy_signal(df)["picked"] == "normal"
    assert agent.evaluate_strategy_signal(df, risk_band="NORMAL")["picked"] == "normal"
    assert agent.evaluate_strategy_signal(df, risk_band="RECOVERY")["picked"] == "recovery"


@pytest.mark.parametrize("agent_module,agent_class,strategy_attr", [
    ("agents.eur_agent", "EurSpecialistAgent", "strategy_mtf_momentum"),
    ("agents.gbp_agent", "GbpSpecialistAgent", "strategy_ema_pullback"),
    ("agents.xpt_agent", "PlatinumSpecialistAgent", "strategy_agentic_confluence"),
    ("agents.ukoil_agent", "UkoilSpecialistAgent", "strategy_bb_reversion"),
    ("agents.xng_agent", "NaturalGasSpecialistAgent", "strategy_ema_pullback"),
])
def test_five_specialists_recovery_band_is_a_noop(broker, monkeypatch, agent_module, agent_class, strategy_attr):
    """Confirmed no-ops (2026-09-25 M15 backtest data found no alternative
    strategy for these 5 that beats their current live one) -- RECOVERY
    must call the exact same strategy function as NORMAL."""
    import importlib
    mod = importlib.import_module(agent_module)
    cls = getattr(mod, agent_class)
    agent = cls(broker=broker)
    df = pd.DataFrame({"close": [1.0, 2.0, 3.0]})

    calls = []
    def fake_strategy(df, current_idx):
        calls.append(current_idx)
        return {"action": "HOLD"}
    monkeypatch.setattr(mod, strategy_attr, fake_strategy)

    agent.evaluate_strategy_signal(df, risk_band="NORMAL")
    agent.evaluate_strategy_signal(df, risk_band="RECOVERY")
    assert len(calls) == 2  # both calls went through -- same function, no branch skipped either
```

Add to `tests/test_agents.py` (gold/btc/eth are excluded from RECOVERY
entirely -- confirm `risk_band` is accepted but has zero effect on which
branch fires):

```python
def test_gold_btc_eth_ignore_risk_band_stay_on_m5_scalper(temp_journal_dir):
    broker = PaperTradingBroker(initial_balance=10000.0)
    agent = GoldSpecialistAgent(broker=broker, journal_dir=temp_journal_dir / "xauusd", timeframe="M5")
    n = 60
    mock_df = pd.DataFrame({
        "timestamp": pd.date_range("2026-08-01 10:00", periods=n, freq="5min"),
        "open": [2000.0] * n, "high": [2001.0] * n, "low": [1999.0] * n,
        "close": [2000.0 + i * 0.1 for i in range(n)], "volume": [100] * n,
    })
    sig_normal = agent.evaluate_strategy_signal(mock_df, risk_band="NORMAL")
    sig_recovery = agent.evaluate_strategy_signal(mock_df, risk_band="RECOVERY")
    # Same strategy fn (strategy_m5_scalper) is deterministic on identical
    # input regardless of risk_band -- both calls must agree on action.
    assert sig_normal["action"] == sig_recovery["action"]
```

#### Step 2: Run tests to verify they fail

Run: `python3 -m pytest tests/test_new_market_agents.py tests/test_agents.py::test_gold_btc_eth_ignore_risk_band_stay_on_m5_scalper -v`
Expected: FAIL — `TypeError: evaluate_strategy_signal() got an unexpected keyword argument 'risk_band'` for every one of these (none of the 9 concrete overrides accept it yet).

#### Step 3: Implement — the 8 signature-only files

For each of these 8 files, change ONLY the `evaluate_strategy_signal`
line — add the parameter, change nothing else in the body:

`agents/gold_agent.py:81`: `def evaluate_strategy_signal(self, df: pd.DataFrame) -> Dict[str, Any]:` → `def evaluate_strategy_signal(self, df: pd.DataFrame, risk_band: str = "NORMAL") -> Dict[str, Any]:`

`agents/btc_agent.py:61`: same substitution.

`agents/eth_agent.py:62`: same substitution.

`agents/eur_agent.py:57`: same substitution.

`agents/gbp_agent.py:58`: same substitution.

`agents/xpt_agent.py:57`: same substitution.

`agents/ukoil_agent.py:63`: same substitution.

`agents/xng_agent.py:63`: same substitution.

#### Step 4: Implement — `agents/xag_agent.py` (real branch)

Change line 13 from:
```python
from backtest.strategies import strategy_bb_reversion
```
to:
```python
from backtest.strategies import strategy_bb_reversion, strategy_agentic_confluence
```

Change line 57 from:
```python
    def evaluate_strategy_signal(self, df: pd.DataFrame) -> Dict[str, Any]:
        if self.timeframe != "M15":
            raise NotImplementedError("Silver only has a validated M15 strategy; M5 is a separate future spec.")
        return strategy_bb_reversion(df, current_idx=len(df) - 1)
```
to:
```python
    def evaluate_strategy_signal(self, df: pd.DataFrame, risk_band: str = "NORMAL") -> Dict[str, Any]:
        if self.timeframe != "M15":
            raise NotImplementedError("Silver only has a validated M15 strategy; M5 is a separate future spec.")
        if risk_band == "RECOVERY":
            # 2026-09-25 M15 backtest: Strategy E (agentic_confluence) had
            # both lower Max DD (0.67% vs 2.25%) and a positive return
            # (+0.40%) vs. this specialist's normal Strategy C -- the only
            # one of the 9 specialists where a genuinely better recovery
            # option exists.
            return strategy_agentic_confluence(df, current_idx=len(df) - 1)
        return strategy_bb_reversion(df, current_idx=len(df) - 1)
```

#### Step 5: Run tests to verify they pass

Run: `python3 -m pytest tests/test_new_market_agents.py tests/test_agents.py::test_gold_btc_eth_ignore_risk_band_stay_on_m5_scalper -v`
Expected: all PASS.

#### Step 6: Run the full suite

Run: `python3 -m pytest tests/ -q`
Expected: 100% pass, no skips introduced. This is the final task of the
plan — a fully green suite here means the whole fixed-principal +
recovery-band feature is done end-to-end (`SquadManager.step()` →
`BaseSpecialistAgent.step()` → each specialist's `evaluate_strategy_signal`)
and every pre-existing test that needed updating for the new formula has
been updated, not just made to coincidentally still pass.

#### Step 7: Commit

```bash
git add agents/gold_agent.py agents/btc_agent.py agents/eth_agent.py agents/eur_agent.py agents/gbp_agent.py agents/xpt_agent.py agents/ukoil_agent.py agents/xng_agent.py agents/xag_agent.py tests/test_new_market_agents.py tests/test_agents.py tests/test_agent_concurrency.py tests/test_mt5_bridge.py tests/test_strategy_enhancements.py
git commit -m "feat(agents): thread risk_band through all 9 specialists + 5 test mocks; XAG gets real RECOVERY branch"
```
