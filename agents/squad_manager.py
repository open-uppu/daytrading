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
        total_realized_pnl = sum(ag.session_tracker.closed_pnl_today for ag in self.specialists.values())
        total_trades_today = sum(ag.session_tracker.trades_count_today for ag in self.specialists.values())
        total_wins_today = sum(ag.session_tracker.wins_count_today for ag in self.specialists.values())
        
        acc = self.broker.get_account_info()
        current_equity = acc["equity"]
        current_balance = acc["balance"]
        
        daily_return_pct = round((total_realized_pnl / self.starting_portfolio_balance) * 100.0, 2) if self.starting_portfolio_balance > 0 else 0.0
        
        target_reached = daily_return_pct >= (self.target_pct * 100.0)
        max_loss_reached = daily_return_pct <= -(self.max_loss_pct * 100.0)
        
        return {
            "starting_balance": self.starting_portfolio_balance,
            "current_balance": current_balance,
            "current_equity": current_equity,
            "realized_pnl_usd": total_realized_pnl,
            "daily_return_pct": daily_return_pct,
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
        portfolio_status = self.get_portfolio_daily_pnl()

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
            logger.warning(f"[Squad Manager] PORTFOLIO MAX DAILY LOSS CUTOFF HIT ({portfolio_status['daily_return_pct']:.2f}%). Halting squad.")
            return {
                "iteration": self.iteration_count,
                "status": "PORTFOLIO_MAX_LOSS_CUTOFF",
                "portfolio": portfolio_status,
                "specialist_results": {}
            }

        agent_results = {}
        for key, agent in self.specialists.items():
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

    def display_dashboard(self) -> None:
        """Prints a visual status dashboard of the Multi-Asset Specialist Squad."""
        p_stat = self.get_portfolio_daily_pnl()
        
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
                
                if step_res["status"] in ["PORTFOLIO_DAILY_TARGET_REACHED", "PORTFOLIO_MAX_LOSS_CUTOFF"]:
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
