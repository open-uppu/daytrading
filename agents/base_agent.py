"""
Base Specialist Agent for Multi-Asset Trading System.
Provides the abstract lifecycle and execution core for asset-specific specialists (Gold, Bitcoin, Ethereum).
"""

from typing import Dict, Any, Optional, Tuple
from abc import ABC, abstractmethod
from pathlib import Path
from datetime import datetime
import logging
import pandas as pd

from config import config
from mt4.broker_interface import BaseBroker
from mt4.paper_broker import PaperTradingBroker
from mt5.bridge_server import MT5BridgeBroker
from mt4.bridge_server import MT4BridgeBroker
from risk.manager import DailySessionTracker, RiskManager
from core.chart_generator import generate_candlestick_chart
from core.vision_analyzer import VisionAnalyzer
from learning.reflector import TradeReflector, PreTradeFilter, TradeOutcome

logger = logging.getLogger("specialist_agent")


class BaseSpecialistAgent(ABC):
    """
    Abstract Base Class for Asset Specialists.
    Each specialist agent focuses on a single financial asset, with tailored contract sizes,
    dedicated learned rules, mistake journals, and backtested optimal strategies.
    """

    def __init__(
        self,
        symbol: str,
        asset_name: str,
        timeframe: str = "M15",
        contract_size: float = 100.0,
        min_lot: float = 0.01,
        max_lot: float = 10.0,
        min_sl_dist: float = 2.0,
        broker: Optional[BaseBroker] = None,
        broker_mode: str = "paper",
        initial_balance: Optional[float] = None,
        journal_dir: Optional[Path] = None,
        strategy_type: str = "trend"
    ):
        self.symbol = symbol
        self.asset_name = asset_name
        self.timeframe = timeframe
        self.contract_size = contract_size
        self.min_lot = min_lot
        self.max_lot = max_lot
        self.min_sl_dist = min_sl_dist
        self.strategy_type = strategy_type
        
        self.broker_mode = broker_mode or config.broker_mode
        self.initial_balance = initial_balance or config.initial_balance
        
        # 1. Broker Setup
        if broker is not None:
            self.broker = broker
        elif self.broker_mode == "mt5":
            self.broker = MT5BridgeBroker()
        elif self.broker_mode == "mt4":
            self.broker = MT4BridgeBroker()
        else:
            self.broker = PaperTradingBroker(initial_balance=self.initial_balance)
            
        # 2. Asset-Specific Journal & Learning Setup
        self.journal_dir = journal_dir or (config.project_root / "journal" / self.symbol.lower())
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        self.trades_dir = self.journal_dir / "trades"
        self.trades_dir.mkdir(parents=True, exist_ok=True)
        self.learned_rules_file = self.journal_dir / "learned_rules.md"
        self.mistakes_db_file = self.journal_dir / "mistakes_database.md"

        self.reflector = TradeReflector(
            trades_dir=self.trades_dir,
            learned_rules_file=self.learned_rules_file,
            mistakes_db_file=self.mistakes_db_file
        )
        self.pre_trade_filter = PreTradeFilter(
            learned_rules_file=self.learned_rules_file,
            enforce_ema_trend=(self.strategy_type == "trend"),
            strategy_type=self.strategy_type
        )

        # 3. Risk & Session Management (Daily 3% target, 1.5% max risk per trade)
        self.session_tracker = DailySessionTracker(
            starting_balance=self.initial_balance,
            target_pct=config.daily_target_pct,
            max_loss_pct=config.daily_max_loss_pct
        )
        self.risk_manager = RiskManager(
            session_tracker=self.session_tracker,
            contract_size=self.contract_size,
            min_lot=self.min_lot,
            max_lot=self.max_lot,
            min_sl_dist=self.min_sl_dist
        )

        # 4. Multimodal Vision Engine
        self.vision_analyzer = VisionAnalyzer()
        
        # 5. Agent Runtime State
        self.last_chart_path: Optional[Path] = None
        self.last_signal: Dict[str, Any] = {"action": "HOLD"}
        self.iteration_count: int = 0
        self.known_closed_tickets: set = set()

    @property
    @abstractmethod
    def strategy_name(self) -> str:
        """Name of the optimal strategy deployed for this specialist."""
        pass

    @abstractmethod
    def evaluate_strategy_signal(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Computes the asset-specific algorithmic trading signal.
        Returns dict with keys: 'action' (BUY/SELL/HOLD), 'sl', 'tp', 'reason', etc.
        """
        pass

    def _reconcile_closed_trades(self) -> None:
        """Checks for newly closed trades, logs autopsies, and updates learned rules."""
        if hasattr(self.broker, "consume_recently_closed"):
            closed_trades = self.broker.consume_recently_closed()
        elif hasattr(self.broker, "get_closed_orders"):
            closed_trades = self.broker.get_closed_orders()
        elif hasattr(self.broker, "get_trade_history"):
            closed_trades = self.broker.get_trade_history(symbol=self.symbol, count=10)
        else:
            closed_trades = []

        for t in closed_trades:
            ticket = t["ticket"]
            if ticket not in self.known_closed_tickets:
                self.known_closed_tickets.add(ticket)
                pnl = t.get("profit", t.get("pnl_usd", 0.0))
                self.session_tracker.record_closed_trade(pnl)
                
                # Perform post-trade autopsy & learning
                outcome = TradeOutcome(
                    ticket=ticket,
                    symbol=t.get("symbol", self.symbol),
                    order_type=t["type"],
                    open_time=t.get("open_time", datetime.now().isoformat()),
                    close_time=t.get("close_time", datetime.now().isoformat()),
                    entry_price=t["open_price"],
                    close_price=t["close_price"],
                    lot_size=t["lots"],
                    sl_price=t.get("sl", 0.0),
                    tp_price=t.get("tp", 0.0),
                    pnl_usd=pnl,
                    pnl_pct=round((pnl / self.session_tracker.starting_balance) * 100, 2),
                    exit_reason=t.get("exit_reason", "TP_HIT" if pnl > 0 else "SL_HIT"),
                    confluence_score=75.0,
                    pattern_detected=self.strategy_name,
                    ema_200=t.get("open_price", 0.0),
                    atr=self.min_sl_dist,
                    rsi=50.0
                )
                res = self.reflector.process_closed_trade(outcome)
                logger.info(f"[{self.symbol} Specialist] Trade #{ticket} autopsy complete: {res['diagnosis_code']}")

    def _manage_active_position(self, pos: Dict[str, Any]) -> None:
        """Applies trailing stops or breakeven protection on profitable positions."""
        pass

    def step(self) -> Dict[str, Any]:
        """
        Executes one complete autonomous analysis and execution cycle for this asset.
        """
        self.iteration_count += 1
        prefix = f"[{self.symbol} Specialist #{self.iteration_count}]"

        # 1. Reconcile closed trades
        self._reconcile_closed_trades()

        # 2. Query Account State & Daily Target Status
        account_info = self.broker.get_account_info()
        current_balance = account_info["balance"]
        current_equity = account_info["equity"]
        self.session_tracker.check_new_session(current_balance)
        summary = self.session_tracker.get_summary()

        # 3. Check Daily Profit Target & Risk Gates
        can_trade, gate_reason = self.session_tracker.can_open_new_trade()
        if not can_trade:
            logger.info(f"{prefix} Standby: {gate_reason}")
            return {
                "symbol": self.symbol,
                "asset": self.asset_name,
                "iteration": self.iteration_count,
                "status": "LOCKED",
                "reason": gate_reason,
                "session_summary": summary
            }

        # 4. Check Open Positions for this Symbol
        all_open = self.broker.get_open_positions()
        symbol_positions = [p for p in all_open if p.get("symbol") == self.symbol]
        
        if len(symbol_positions) >= 1:
            pos = symbol_positions[0]
            logger.info(f"{prefix} Monitoring active position #{pos['ticket']} ({pos['type']} {pos['lots']} lots).")
            self._manage_active_position(pos)
            return {
                "symbol": self.symbol,
                "asset": self.asset_name,
                "iteration": self.iteration_count,
                "status": "MONITORING_POSITION",
                "position": pos,
                "session_summary": summary
            }

        # 5. Fetch Market Data (M15)
        df_m15 = self.broker.get_market_data(symbol=self.symbol, timeframe=self.timeframe, bars=60)
        if len(df_m15) < 30:
            logger.warning(f"{prefix} Insufficient bars ({len(df_m15)}) for {self.symbol}.")
            return {
                "symbol": self.symbol,
                "asset": self.asset_name,
                "iteration": self.iteration_count,
                "status": "INSUFFICIENT_DATA"
            }

        # 6. Candlestick Chart Generation
        chart_filename = f"{self.symbol.lower()}_m15.png"
        self.last_chart_path = generate_candlestick_chart(
            df=df_m15,
            timeframe=self.timeframe,
            symbol=self.symbol,
            save_path=config.artifacts_dir / chart_filename
        )

        # 7. Evaluate Strategy Signal
        signal = self.evaluate_strategy_signal(df_m15)
        self.last_signal = signal
        action = signal.get("action", "HOLD")

        if action not in ["BUY", "SELL"]:
            return {
                "symbol": self.symbol,
                "asset": self.asset_name,
                "iteration": self.iteration_count,
                "status": "WAITING_FOR_SETUP",
                "action": "HOLD",
                "signal": signal,
                "session_summary": summary
            }

        current_price = float(df_m15.iloc[-1]["close"])
        atr = float(df_m15.iloc[-1].get("atr_14", self.min_sl_dist))
        ema_200 = float(df_m15.iloc[-1].get("ema_200", current_price))

        # SL and TP from strategy or dynamic ATR
        sl_candidate = signal.get("sl")
        tp_candidate = signal.get("tp")
        if sl_candidate is None or tp_candidate is None:
            sl_candidate, tp_candidate, _ = self.risk_manager.compute_sl_tp(
                action=action,
                entry_price=current_price,
                atr=atr
            )

        # 8. Pre-Trade Filter against Asset's Learned Rules
        rule_passed, rule_reason = self.pre_trade_filter.evaluate_proposal(
            action=action,
            entry_price=current_price,
            sl_price=sl_candidate,
            ema_200=ema_200,
            atr=atr
        )

        if not rule_passed:
            logger.warning(f"{prefix} PREVENTED MISTAKE by {self.symbol} learned rules: {rule_reason}")
            return {
                "symbol": self.symbol,
                "asset": self.asset_name,
                "iteration": self.iteration_count,
                "status": "VETOED_BY_LEARNED_RULE",
                "reason": rule_reason,
                "session_summary": summary
            }

        # 9. Risk Sizing & Order Validation
        is_valid, risk_reason, lot_size = self.risk_manager.validate_trade_proposal(
            action=action,
            entry_price=current_price,
            sl_price=sl_candidate,
            tp_price=tp_candidate,
            equity=current_equity
        )

        if not is_valid:
            logger.warning(f"{prefix} Risk rejected trade: {risk_reason}")
            return {
                "symbol": self.symbol,
                "asset": self.asset_name,
                "iteration": self.iteration_count,
                "status": "RISK_REJECTED",
                "reason": risk_reason,
                "session_summary": summary
            }

        # 10. Execute Order via Broker
        # A broker that cannot deliver the command now raises instead of
        # pretending success, so failures surface as BROKER_ERROR rather than
        # a phantom ORDER_PLACED.
        try:
            order_res = self.broker.open_order(
                symbol=self.symbol,
                order_type=action,
                lots=lot_size,
                sl=sl_candidate,
                tp=tp_candidate,
                comment=f"{self.symbol}_{self.strategy_name[:8]}"
            )
        except Exception as e:
            logger.error(
                f"{prefix} ORDER DELIVERY FAILED for {action} {lot_size} lots "
                f"{self.symbol}: {type(e).__name__}: {e}"
            )
            return {
                "symbol": self.symbol,
                "asset": self.asset_name,
                "iteration": self.iteration_count,
                "status": "BROKER_ERROR",
                "reason": f"{type(e).__name__}: {e}",
                "session_summary": summary
            }

        # A live bridge can queue a command but never hear back from the EA.
        # Report that honestly instead of claiming the order is working.
        if order_res.get("confirmed") is False:
            logger.warning(
                f"{prefix} ORDER UNCONFIRMED: {action} {lot_size} lots {self.symbol} "
                f"queued as {order_res.get('command_id')} but the EA did not confirm. "
                f"Is the EA attached to a chart and WebRequest allowed?"
            )
            return {
                "symbol": self.symbol,
                "asset": self.asset_name,
                "iteration": self.iteration_count,
                "status": "ORDER_UNCONFIRMED",
                "order": order_res,
                "strategy": self.strategy_name,
                "session_summary": summary
            }

        logger.info(
            f"{prefix} ORDER PLACED: {action} {lot_size} lots {self.symbol} @ {current_price:.2f} "
            f"(SL: {sl_candidate}, TP: {tp_candidate}"
            + (f", ticket: #{order_res.get('ticket')}" if order_res.get("ticket") else "")
            + ")"
        )
        return {
            "symbol": self.symbol,
            "asset": self.asset_name,
            "iteration": self.iteration_count,
            "status": "ORDER_PLACED",
            "order": order_res,
            "strategy": self.strategy_name,
            "session_summary": summary
        }
