"""
Squad Manager: Master Coordinator for Multi-Asset Specialist Agents.
Orchestrates Gold, Bitcoin, and Ethereum specialists with a unified Portfolio 3% Daily Target Lock.
"""

from typing import Dict, Any, List, Optional
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
from agents.gold_agent import GoldSpecialistAgent
from agents.btc_agent import BtcSpecialistAgent
from agents.eth_agent import EthSpecialistAgent
from agents.base_agent import BaseSpecialistAgent

logger = logging.getLogger("squad_manager")
console = Console()


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
        agents_to_enable: Optional[List[str]] = None
    ):
        self.broker_mode = broker_mode or config.broker_mode
        self.initial_balance = initial_balance or config.initial_balance
        
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
        self.starting_portfolio_balance: float = self.initial_balance
        self.target_pct: float = config.daily_target_pct  # 3.0%
        self.max_loss_pct: float = config.daily_max_loss_pct  # -2.0%
        self.target_profit_usd: float = self.starting_portfolio_balance * self.target_pct
        self.max_loss_usd: float = self.starting_portfolio_balance * self.max_loss_pct

        # 3. Instantiate Specialist Agents
        self.specialists: Dict[str, BaseSpecialistAgent] = {}
        enabled = [a.lower() for a in (agents_to_enable or ["gold", "btc", "eth"])]
        
        if "gold" in enabled or "xauusd" in enabled:
            self.specialists["gold"] = GoldSpecialistAgent(
                broker=self.broker,
                broker_mode=self.broker_mode,
                initial_balance=self.initial_balance
            )
        if "btc" in enabled or "btcusd" in enabled:
            self.specialists["btc"] = BtcSpecialistAgent(
                broker=self.broker,
                broker_mode=self.broker_mode,
                initial_balance=self.initial_balance
            )
        if "eth" in enabled or "ethusd" in enabled:
            self.specialists["eth"] = EthSpecialistAgent(
                broker=self.broker,
                broker_mode=self.broker_mode,
                initial_balance=self.initial_balance
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

    def check_new_session(self) -> None:
        """Resets daily portfolio tracker on new UTC date."""
        today = datetime.now(timezone.utc).date()
        if today != self.session_date:
            logger.info(f"[Squad Manager] New trading session: {today}. Resetting portfolio tracker.")
            self.session_date = today
            acc = self.broker.get_account_info()
            self.starting_portfolio_balance = acc["balance"]
            self.target_profit_usd = self.starting_portfolio_balance * self.target_pct
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
            "target_reached": target_reached,
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

        # Check Portfolio-Level Target Lock
        if portfolio_status["target_reached"]:
            logger.info(f"[Squad Manager] PORTFOLIO 3% TARGET ACHIEVED! (+{portfolio_status['daily_return_pct']:.2f}%). Halting all squad trades.")
            return {
                "iteration": self.iteration_count,
                "status": "PORTFOLIO_DAILY_TARGET_REACHED",
                "portfolio": portfolio_status,
                "specialist_results": {}
            }

        if portfolio_status["max_loss_reached"]:
            close_results = self._close_all_positions()
            logger.warning(f"[Squad Manager] PORTFOLIO MAX DAILY LOSS CUTOFF HIT ({portfolio_status['daily_return_pct']:.2f}%). Halting squad.")
            return {
                "iteration": self.iteration_count,
                "status": "PORTFOLIO_MAX_LOSS_CUTOFF",
                "portfolio": portfolio_status,
                "close_results": close_results,
                "specialist_results": {}
            }

        agent_results = {}
        for key, agent in self.specialists.items():
            # Reserve the portfolio loss budget across all symbols.  Without
            # this gate all three specialists could each open a 1% position in
            # the same round, exceeding the configured 2% portfolio cutoff.
            if self._portfolio_open_risk_usd() >= self.starting_portfolio_balance * self.max_loss_pct:
                agent_results[key] = {
                    "symbol": agent.symbol,
                    "asset": agent.asset_name,
                    "status": "PORTFOLIO_RISK_BUDGET_REACHED",
                    "reason": "Existing open-position risk consumes the portfolio daily loss budget.",
                }
                continue
            try:
                res = agent.step()
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
        """Estimate worst-case loss to each active SL across the portfolio."""
        contract_sizes = {"XAUUSD": 100.0, "BTCUSD": 1.0, "ETHUSD": 1.0}
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

        for key, agent in self.specialists.items():
            summ = agent.session_tracker.get_summary()
            status_text = "Target Lock" if summ.get("target_reached") else ("Loss Cutoff" if summ.get("max_loss_hit") else "Scanning")
            
            pnl = summ.get("closed_pnl_usd", 0.0)
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
                
                if step_res["status"] in ["PORTFOLIO_DAILY_TARGET_REACHED", "PORTFOLIO_MAX_LOSS_CUTOFF", "BRIDGE_UNAVAILABLE"]:
                    console.print(f"[bold yellow]Squad loop paused: {step_res['status']}[/bold yellow]")
                    break
                    
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
