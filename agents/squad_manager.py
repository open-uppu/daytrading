"""
Squad Manager: Master Coordinator for Multi-Asset Specialist Agents.
Orchestrates Gold, Bitcoin, and Ethereum specialists with a unified Portfolio 3% Daily Target Lock.
"""

from typing import Dict, Any, List, Optional, Tuple, Type
from pathlib import Path
import time
import logging
from datetime import datetime, timezone, date
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.live import Live

from config import config
from mt4.broker_interface import BaseBroker
from mt4.paper_broker import PaperTradingBroker
from mt5.bridge_server import MT5BridgeBroker
from mt4.bridge_server import MT4BridgeBroker
from risk.manager import day_baseline
from backtest.data_loader import ASSET_SPECS
from agents.gold_agent import GoldSpecialistAgent
from agents.btc_agent import BtcSpecialistAgent
from agents.eth_agent import EthSpecialistAgent
from agents.xag_agent import SilverSpecialistAgent
from agents.gbp_agent import GbpSpecialistAgent
from agents.eur_agent import EurSpecialistAgent
from agents.xpt_agent import PlatinumSpecialistAgent
from agents.ukoil_agent import UkoilSpecialistAgent
from agents.xng_agent import NaturalGasSpecialistAgent
from agents.base_agent import BaseSpecialistAgent

logger = logging.getLogger("squad_manager")
console = Console()

# key -> (AgentClass, journal-subdir name, forced_timeframe). "all" expands to
# every entry here. ukoil/xng have an unconfirmed contract_size (see their
# agent module docstrings) so they live in GATED_SPECIALISTS instead:
# reachable only by explicit --agent=ukoil / --agent=xng, never by "all".
#
# forced_timeframe=None means "use whatever timeframe the squad was started
# with" (gold/btc/eth support both M5 and M15). The 6 new agents only have a
# validated M15 strategy, so their forced_timeframe is always "M15" --
# otherwise a squad started on M5 (today's live production default) would
# make every one of them raise NotImplementedError on its first step().
SPECIALIST_REGISTRY: Dict[str, Tuple[Type[BaseSpecialistAgent], str, Optional[str]]] = {
    "gold": (GoldSpecialistAgent, "xauusd", None),
    "btc": (BtcSpecialistAgent, "btcusd", None),
    "eth": (EthSpecialistAgent, "ethusd", None),
    "xag": (SilverSpecialistAgent, "xagusd", "M15"),
    "gbp": (GbpSpecialistAgent, "gbpusd", "M15"),
    "eur": (EurSpecialistAgent, "eurusd", "M15"),
    "xpt": (PlatinumSpecialistAgent, "xptusd", "M15"),
}
GATED_SPECIALISTS: Dict[str, Tuple[Type[BaseSpecialistAgent], str, Optional[str]]] = {
    "ukoil": (UkoilSpecialistAgent, "ukoil", "M15"),
    "xng": (NaturalGasSpecialistAgent, "xngusd", "M15"),
}

# Deterministic MT5 magic number per timeframe: 888900 + minutes(timeframe).
# M5 is the one exception -- it must stay 888999 to match the magic already
# in use by real open positions on the live account (see
# mt5/AgenticMT5Bridge.mq5's InpMagicNumber default). This table must be
# kept in sync with mt5/AgenticMT5Bridge.mq5's g_managedMagics[] array --
# an entry missing from either side means that timeframe's positions won't
# be reported back to the Python bridge at all.
TIMEFRAME_MAGIC: Dict[str, int] = {
    "M1": 888901,
    "M5": 888999,
    "M15": 888915,
    "M30": 888930,
    "H1": 888960,
    "H4": 889140,
    "D1": 890340,
}


def magic_for_timeframe(timeframe: str) -> int:
    try:
        return TIMEFRAME_MAGIC[timeframe.upper()]
    except KeyError:
        raise ValueError(
            f"No magic number mapping for timeframe {timeframe!r}. "
            f"Add one to TIMEFRAME_MAGIC before running this timeframe live -- "
            f"never fall back to another timeframe's magic, that would make "
            f"two instances silently share (and corrupt) each other's positions."
        )


class SquadManager:
    """
    Portfolio Orchestrator managing multiple specialist agents simultaneously.
    Enforces Portfolio-Wide 3% Daily Profit Target and Cross-Asset Risk Controls.
    """

    def __init__(
        self,
        broker: Optional[BaseBroker] = None,
        broker_mode: str = "paper",
        initial_balance: Optional[float] = None,
        agents_to_enable: Optional[List[str]] = None,
        timeframe: str = "M5",
        journal_dir: Optional[Path] = None
    ):
        self.broker_mode = broker_mode or config.broker_mode
        self.initial_balance = initial_balance or config.initial_balance
        self.timeframe = timeframe or config.timeframe_main
        
        # 1. Initialize Shared Broker
        if broker is not None:
            self.broker = broker
        elif self.broker_mode == "mt5":
            self.broker = MT5BridgeBroker()
        elif self.broker_mode == "mt4":
            self.broker = MT4BridgeBroker()
        else:
            self.broker = PaperTradingBroker(initial_balance=self.initial_balance)

        # A live account must never inherit the CLI's paper-trading default
        # ($10,000).  That would turn a 3% target on a ~$500 account into a
        # $300 target, and make the daily loss circuit breaker ineffective.
        # Use the balance reported by the terminal at process startup as this
        # session's reference point.  Explicit balances remain useful for
        # paper/backtest brokers and their deterministic tests.
        if self.broker_mode == "mt5":
            live_account = self.broker.get_account_info()
            live_balance = live_account.get("balance")
            # Only a real MT5 bridge can prove terminal connectivity.  A
            # disconnected bridge must never be allowed to start a live loop
            # against its in-memory $10,000 placeholder state.
            if isinstance(self.broker, MT5BridgeBroker) and live_account.get("connected") is not True:
                raise RuntimeError(
                    "MT5 telemetry is not connected; refusing to start live trading. "
                    "Attach the EA and verify WebRequest/bridge status first."
                )
            if isinstance(self.broker, MT5BridgeBroker):
                self._require_fresh_telemetry(live_account)
            if isinstance(live_balance, (int, float)) and live_balance > 0:
                self.initial_balance = float(live_balance)
            else:
                raise RuntimeError(
                    "MT5 account balance is unavailable; refusing to start the live squad "
                    "with a configured fallback balance. Check bridge telemetry and EA connection."
                )

        # 2. Portfolio-Level Session & 3% Profit Target Tracker
        self.session_date: date = datetime.now(timezone.utc).date()
        self.starting_portfolio_balance: float = self._day_baseline(self.initial_balance)
        self.target_pct: float = config.daily_target_pct  # 3.0% soft: specialists derisk, portfolio keeps trading
        self.hard_target_pct: float = config.daily_target_hard_pct  # 10.0% hard: locks all trading
        self.max_loss_pct: float = config.daily_max_loss_pct  # -3.0%
        self.target_profit_usd: float = self.starting_portfolio_balance * self.target_pct
        self.hard_target_profit_usd: float = self.starting_portfolio_balance * self.hard_target_pct
        self.max_loss_usd: float = self.starting_portfolio_balance * self.max_loss_pct

        # 3. Instantiate Specialist Agents
        self.specialists: Dict[str, BaseSpecialistAgent] = {}
        raw_enabled = agents_to_enable or ["gold", "btc", "eth"]
        enabled = set()
        for a in raw_enabled:
            al = a.lower()
            if al == "duo":
                enabled.update(["gold", "btc"])
            elif al == "all":
                enabled.update(SPECIALIST_REGISTRY.keys())
            else:
                enabled.add(al)

        # A symbol-name alias (e.g. "xauusd") still resolves to its registry key.
        symbol_to_key = {spec[1]: key for key, spec in {**SPECIALIST_REGISTRY, **GATED_SPECIALISTS}.items()}
        resolved = {symbol_to_key.get(e, e) for e in enabled}

        all_specialists = {**SPECIALIST_REGISTRY, **GATED_SPECIALISTS}
        gated_requested = resolved & set(GATED_SPECIALISTS.keys())
        if gated_requested:
            logger.warning(
                "[Squad Manager] %s has an unconfirmed contract_size (see its agent module docstring) -- "
                "excluded from 'all', running only because explicitly requested.",
                ", ".join(sorted(gated_requested))
            )

        for key in resolved:
            if key not in all_specialists:
                continue
            agent_cls, journal_subdir, forced_timeframe = all_specialists[key]
            effective_timeframe = forced_timeframe or self.timeframe
            self.specialists[key] = agent_cls(
                broker=self.broker,
                broker_mode=self.broker_mode,
                initial_balance=self.initial_balance,
                timeframe=effective_timeframe,
                journal_dir=(journal_dir / journal_subdir) if journal_dir else None,
                magic=magic_for_timeframe(self.timeframe)
            )

        if self.broker_mode == "mt5" and isinstance(self.broker, MT5BridgeBroker):
            # Do not let the loop start in a state where the first evaluation
            # would silently fall back to backtest data or discover a missing
            # feed only after the live process is already running.
            for specialist in self.specialists.values():
                try:
                    self.broker.get_market_data(specialist.symbol, specialist.timeframe, bars=1)
                except RuntimeError as exc:
                    raise RuntimeError(
                        f"Live bars unavailable for {specialist.symbol}; refusing to start squad: {exc}"
                    ) from exc

        self.iteration_count: int = 0
        self.is_running: bool = False

    def _day_baseline(self, balance: float) -> float:
        """Live bridge only: persist the day's first balance so restarting the squad can't reset the loss cutoff."""
        if isinstance(self.broker, MT5BridgeBroker) and not self.broker.in_process:
            return day_baseline(config.journal_dir / "daily_baseline.json", balance)
        return balance

    def check_new_session(self) -> None:
        """Resets daily portfolio tracker on new UTC date."""
        today = datetime.now(timezone.utc).date()
        if today != self.session_date:
            logger.info(f"[Squad Manager] New trading session: {today}. Resetting portfolio tracker.")
            self.session_date = today
            acc = self.broker.get_account_info()
            self.starting_portfolio_balance = self._day_baseline(acc["balance"])
            self.target_profit_usd = self.starting_portfolio_balance * self.target_pct
            self.hard_target_profit_usd = self.starting_portfolio_balance * self.hard_target_pct
            self.max_loss_usd = self.starting_portfolio_balance * self.max_loss_pct

    def get_portfolio_daily_pnl(self) -> Dict[str, Any]:
        """Calculates aggregated realized and unrealized PnL across all specialist agents."""
        self.check_new_session()
        tracker_realized_pnl = sum(ag.session_tracker.closed_pnl_today for ag in self.specialists.values())
        total_trades_today = sum(ag.session_tracker.trades_count_today for ag in self.specialists.values())
        total_wins_today = sum(ag.session_tracker.wins_count_today for ag in self.specialists.values())
        
        acc = self.broker.get_account_info()
        if self.broker_mode == "mt5" and isinstance(self.broker, MT5BridgeBroker):
            if acc.get("connected") is not True:
                raise RuntimeError("MT5 telemetry disconnected; trading is fail-closed")
            self._require_fresh_telemetry(acc)
        current_equity = acc["equity"]
        current_balance = acc["balance"]
        
        # The account is the source of truth in live mode.  Per-agent journal
        # trackers reset with the process and may miss manual/broker-side exits.
        # Preserve tracker data for paper tests, but use terminal balance and
        # equity for live target and loss decisions.
        if self.broker_mode == "mt5":
            total_realized_pnl = current_balance - self.starting_portfolio_balance
        else:
            total_realized_pnl = tracker_realized_pnl
        # Loss protection must include floating PnL in paper and live modes;
        # otherwise an open position can exceed the cutoff before it closes.
        equity_pnl = current_equity - self.starting_portfolio_balance

        daily_return_pct = round((total_realized_pnl / self.starting_portfolio_balance) * 100.0, 2) if self.starting_portfolio_balance > 0 else 0.0
        equity_return_pct = round((equity_pnl / self.starting_portfolio_balance) * 100.0, 2) if self.starting_portfolio_balance > 0 else 0.0

        target_reached = daily_return_pct >= (self.target_pct * 100.0)
        hard_target_reached = daily_return_pct >= (self.hard_target_pct * 100.0)
        max_loss_reached = equity_return_pct <= -(self.max_loss_pct * 100.0)

        return {
            "starting_balance": self.starting_portfolio_balance,
            "current_balance": current_balance,
            "current_equity": current_equity,
            "realized_pnl_usd": total_realized_pnl,
            "equity_pnl_usd": equity_pnl,
            "daily_return_pct": daily_return_pct,
            "equity_return_pct": equity_return_pct,
            "target_pct": self.target_pct * 100.0,
            "target_profit_usd": self.target_profit_usd,
            "hard_target_profit_usd": self.hard_target_profit_usd,
            "target_reached": target_reached,
            "hard_target_reached": hard_target_reached,
            "max_loss_reached": max_loss_reached,
            "total_trades_today": total_trades_today,
            "total_wins_today": total_wins_today,
            "win_rate_today": round((total_wins_today / total_trades_today * 100.0), 1) if total_trades_today > 0 else 0.0
        }

    def step(self) -> Dict[str, Any]:
        """
        Executes one evaluation round across all specialist agents.
        Enforces portfolio-wide 3% daily target cutoff.
        """
        self.iteration_count += 1
        try:
            portfolio_status = self.get_portfolio_daily_pnl()
        except RuntimeError as exc:
            logger.error("[Squad Manager] Live safety gate stopped the loop: %s", exc)
            return {
                "iteration": self.iteration_count,
                "status": "BRIDGE_UNAVAILABLE",
                "error": str(exc),
                "specialist_results": {},
            }

        realized_pnl = portfolio_status.get("realized_pnl_usd", 0.0)
        daily_pct = portfolio_status.get("daily_return_pct", 0.0)
        logger.info(
            f"[PORTFOLIO-REAL-FEED] ทุนเริ่มต้น: ${portfolio_status['starting_balance']:,.2f} "
            f"| Equity ปัจจุบัน: ${portfolio_status['current_equity']:,.2f} "
            f"| กำไรจริงวันนี้: ${realized_pnl:+.2f} ({daily_pct:+.2f}%) "
            f"| เป้าหมาย 3%: ${portfolio_status['target_profit_usd']:,.2f} "
            f"| ไม้ที่เปิดค้าง: {len(self.broker.get_open_positions())} ไม้"
        )

        # Check Portfolio-Level Target Lock (soft target only derisks each
        # specialist individually via their own session_tracker; only the
        # hard target stops the whole squad).
        if portfolio_status["hard_target_reached"]:
            logger.info(f"[Squad Manager] PORTFOLIO {self.hard_target_pct*100:.0f}% HARD TARGET ACHIEVED! (+{portfolio_status['daily_return_pct']:.2f}%). Halting all squad trades.")
            return {
                "iteration": self.iteration_count,
                "status": "PORTFOLIO_DAILY_TARGET_REACHED",
                "portfolio": portfolio_status,
                "specialist_results": {}
            }
        elif portfolio_status["target_reached"]:
            logger.info(f"[Squad Manager] Portfolio soft {self.target_pct*100:.0f}% target passed (+{portfolio_status['daily_return_pct']:.2f}%); specialists derisked, still trading toward {self.hard_target_pct*100:.0f}% hard target.")

        if portfolio_status["max_loss_reached"]:
            close_results = self._close_all_positions()
            logger.warning(f"[Squad Manager] PORTFOLIO MAX DAILY LOSS CUTOFF HIT (equity {portfolio_status['equity_return_pct']:.2f}%, realized {portfolio_status['daily_return_pct']:.2f}%). Halting squad.")
            return {
                "iteration": self.iteration_count,
                "status": "PORTFOLIO_MAX_LOSS_CUTOFF",
                "portfolio": portfolio_status,
                "close_results": close_results,
                "specialist_results": {}
            }

        portfolio_risk_reached = self._portfolio_open_risk_usd() >= (self.starting_portfolio_balance * self.max_loss_pct)
        agent_results = {}
        for key, agent in self.specialists.items():
            try:
                res = agent.step(allow_new_entry=(not portfolio_risk_reached))
                agent_results[key] = res
            except Exception as e:
                logger.error(f"[Squad Manager] Error during {agent.symbol} agent step: {e}", exc_info=True)
                agent_results[key] = {"status": "ERROR", "error": str(e)}

        return {
            "iteration": self.iteration_count,
            "status": "ACTIVE",
            "portfolio": self.get_portfolio_daily_pnl(),
            "specialist_results": agent_results
        }

    def _portfolio_open_risk_usd(self) -> float:
        """Estimate worst-case loss to each active SL across the portfolio.
        contract_sizes is derived from ASSET_SPECS (real broker contract facts)
        rather than a hand-maintained table -- a 3-entry hardcoded dict here
        once defaulted every unlisted symbol to contract_size=1.0, silently
        under-counting a EURUSD/GBPUSD position's risk by ~100,000x and a
        XAGUSD position's by ~5,000x, which could let the portfolio blow
        through its daily max-loss cutoff undetected."""
        contract_sizes = {sym: spec["contract_size"] for sym, spec in ASSET_SPECS.items()}
        total = 0.0
        for pos in self.broker.get_open_positions():
            symbol = str(pos.get("symbol", "")).upper()
            try:
                distance = abs(float(pos["open_price"]) - float(pos["sl"]))
                lots = float(pos["lots"])
            except (KeyError, TypeError, ValueError):
                # Unknown risk is unsafe: count it as the entire remaining
                # budget so another order cannot be opened beside it.
                return self.starting_portfolio_balance * self.max_loss_pct
            total += distance * lots * contract_sizes.get(symbol, 1.0)
        return total

    def _close_all_positions(self) -> Dict[int, Any]:
        """Close every open position and retain per-ticket confirmation/error."""
        results: Dict[int, Any] = {}
        for pos in self.broker.get_open_positions():
            ticket = pos.get("ticket")
            if ticket is None:
                continue
            try:
                results[int(ticket)] = self.broker.close_order(int(ticket))
            except Exception as exc:
                logger.error("[Squad Manager] Failed to close position #%s: %s", ticket, exc)
                results[int(ticket)] = {"status": "ERROR", "error": str(exc)}
        return results

    def display_dashboard(self) -> None:
        """Prints a visual status dashboard of the Multi-Asset Specialist Squad."""
        try:
            p_stat = self.get_portfolio_daily_pnl()
        except RuntimeError as exc:
            console.print(f"[bold red]Dashboard unavailable: {exc}[/bold red]")
            return
        
        target_color = "bold green" if p_stat["target_reached"] else "bold yellow"
        pnl_color = "green" if p_stat["realized_pnl_usd"] >= 0 else "red"
        
        table = Table(
            title="Multi-Asset Specialist Squad Status",
            title_style="bold cyan",
            header_style="bold magenta",
            border_style="dim"
        )
        table.add_column("Specialist", style="bold white", width=12)
        table.add_column("Symbol", style="cyan", width=10)
        table.add_column("Optimal Strategy", style="blue", width=26)
        table.add_column("Status", width=18)
        table.add_column("Today PnL", justify="right", width=12)
        table.add_column("Trades (W/L)", justify="center", width=14)

        try:
            open_positions = self.broker.get_open_positions()
        except Exception:
            open_positions = []

        for key, agent in self.specialists.items():
            summ = agent.session_tracker.get_summary()
            sym_pos = [p for p in open_positions if p.get("symbol") == agent.symbol]
            if sym_pos:
                status_text = f"Holding ({len(sym_pos)} pos)"
            elif summ.get("hard_target_reached"):
                status_text = "Target Lock"
            elif summ.get("max_loss_hit"):
                status_text = "Loss Cutoff"
            elif summ.get("target_reached"):
                status_text = "Derisked"
            else:
                status_text = "Scanning"
            
            pnl = summ.get("closed_pnl_today", 0.0)
            pnl_style = "green" if pnl >= 0 else "red"
            pnl_str = f"[{pnl_style}]${pnl:+.2f}[/{pnl_style}]"
            trades_str = f"{summ.get('trades_count', 0)} ({summ.get('wins', 0)}/{summ.get('losses', 0)})"
            
            table.add_row(
                agent.asset_name,
                agent.symbol,
                agent.strategy_name,
                status_text,
                pnl_str,
                trades_str
            )

        console.print("\n")
        console.print(Panel(
            f"[bold]Portfolio Starting Balance:[/bold] ${p_stat['starting_balance']:,.2f} | "
            f"[bold]Equity:[/bold] ${p_stat['current_equity']:,.2f} | "
            f"[bold]Realized PnL:[/bold] [{pnl_color}]${p_stat['realized_pnl_usd']:+.2f} ({p_stat['daily_return_pct']:+.2f}%)[/{pnl_color}] | "
            f"[{target_color}]Goal 3%: ${p_stat['target_profit_usd']:.2f}[/{target_color}]",
            title="[bold green]Agentic Squad Portfolio Dashboard[/bold green]",
            border_style="green"
        ))
        console.print(table)
        console.print("\n")

    def run_loop(self, max_iterations: Optional[int] = None, interval_sec: int = 10) -> None:
        """Runs the continuous multi-agent execution loop."""
        self.is_running = True
        console.print(f"[bold green]Starting Multi-Asset Specialist Squad ({', '.join(self.specialists.keys())})...[/bold green]")
        
        try:
            while self.is_running:
                step_res = self.step()
                self.display_dashboard()
                
                if step_res["status"] == "BRIDGE_UNAVAILABLE":
                    console.print(f"[bold yellow]Squad loop paused: {step_res['status']}[/bold yellow]")
                    break

                if step_res["status"] in ["PORTFOLIO_DAILY_TARGET_REACHED", "PORTFOLIO_MAX_LOSS_CUTOFF"]:
                    console.print(f"[bold yellow]Squad idle ({step_res['status']}): no new trades, still monitoring.[/bold yellow]")
                    
                if max_iterations and self.iteration_count >= max_iterations:
                    console.print(f"[bold cyan]Reached max requested iterations ({max_iterations}). Stopping.[/bold cyan]")
                    break
                    
                time.sleep(interval_sec)
        except KeyboardInterrupt:
            console.print("\n[bold yellow]Squad execution stopped by user.[/bold yellow]")
        finally:
            self.is_running = False

    @staticmethod
    def _require_fresh_telemetry(account: Dict[str, Any], max_age_sec: float = 90.0) -> None:
        """Reject missing/stale EA heartbeats before any live order can be sent."""
        raw = account.get("last_sync")
        if not raw:
            raise RuntimeError("MT5 telemetry has no last_sync heartbeat")
        try:
            stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - stamp).total_seconds()
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"Invalid MT5 telemetry timestamp: {raw!r}") from exc
        if age < 0 or age > max_age_sec:
            raise RuntimeError(f"MT5 telemetry is stale ({age:.1f}s old; limit {max_age_sec:.0f}s)")
