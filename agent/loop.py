"""
Autonomous Day Trading Loop for Gold (XAUUSD).
Orchestrates account synchronization, 3% daily target controls, chart generation,
vision analysis, pre-trade learned rule validation, execution, and mistake reflection.
"""

from typing import Dict, Any, Optional
import time
import logging
from pathlib import Path
from datetime import datetime

from config import config
from mt4.broker_interface import BaseBroker
from mt4.paper_broker import PaperTradingBroker
from mt4.bridge_server import MT4BridgeBroker
from mt5.bridge_server import MT5BridgeBroker
from risk.manager import DailySessionTracker, RiskManager
from core.chart_generator import generate_candlestick_chart
from core.vision_analyzer import VisionAnalyzer
from core.confluence import ConfluenceEngine
from learning.reflector import TradeReflector, PreTradeFilter, TradeOutcome

logger = logging.getLogger("agent_loop")


class TradingAgent:
    """Master autonomous agent controlling the daily Gold trading operations."""

    def __init__(
        self,
        broker: Optional[BaseBroker] = None,
        broker_mode: str = "paper",
        initial_balance: float = None,
        poll_interval: int = None
    ):
        self.broker_mode = broker_mode or config.broker_mode
        self.poll_interval = poll_interval or config.loop_interval_sec
        self.initial_balance = initial_balance or config.initial_balance
        
        # 1. Initialize Broker
        if broker is not None:
            self.broker = broker
        elif self.broker_mode == "mt5":
            self.broker = MT5BridgeBroker()
        elif self.broker_mode == "mt4":
            self.broker = MT4BridgeBroker()
        else:
            self.broker = PaperTradingBroker(initial_balance=self.initial_balance)
            
        # 2. Risk Management & 3% Daily Target System
        self.session_tracker = DailySessionTracker(
            starting_balance=self.initial_balance,
            target_pct=config.daily_target_pct,
            max_loss_pct=config.daily_max_loss_pct
        )
        self.risk_manager = RiskManager(session_tracker=self.session_tracker)
        
        # 3. Analysis & Multimodal Vision Engines
        self.vision_analyzer = VisionAnalyzer()
        self.confluence_engine = ConfluenceEngine(threshold=config.confluence_threshold)
        
        # 4. Self-Learning & Mistake Reflection
        self.reflector = TradeReflector()
        self.pre_trade_filter = PreTradeFilter()
        
        self.last_chart_path: Optional[Path] = None
        self.is_running: bool = False
        self.iteration_count: int = 0

    def step(self) -> Dict[str, Any]:
        """
        Executes one full iteration of the trading loop:
        1. Check newly closed trades -> run post-trade autopsy & learn rules.
        2. Query account state & sync session tracker.
        3. Check 3% daily target / drawdown bounds.
        4. If position active: monitor trailing stop / break-even.
        5. If flat: fetch market data -> generate chart -> run vision -> check confluence.
        6. Validate setup against learned rules -> execute if all pass.
        """
        self.iteration_count += 1
        log_prefix = f"[Loop #{self.iteration_count}]"
        
        # Step 1: Reconcile newly closed trades
        self._reconcile_closed_trades()
        
        # Step 2: Query Account Telemetry
        account_info = self.broker.get_account_info()
        current_balance = account_info["balance"]
        current_equity = account_info["equity"]
        self.session_tracker.check_new_session(current_balance)
        
        summary = self.session_tracker.get_summary()
        
        # Step 3: Check Daily Target and Risk Gates
        can_trade, gate_reason = self.session_tracker.can_open_new_trade()
        if not can_trade:
            logger.info(f"{log_prefix} Standby: {gate_reason}")
            return {
                "iteration": self.iteration_count,
                "status": "LOCKED",
                "reason": gate_reason,
                "session_summary": summary
            }

        # Step 4: Check Active Positions
        open_positions = self.broker.get_open_positions()
        if len(open_positions) >= config.max_open_positions:
            pos = open_positions[0]
            logger.info(f"{log_prefix} Monitoring active position #{pos['ticket']} ({pos['type']} {pos['lots']} lots). Floating PnL: ${pos.get('unrealized_pnl', 0.0):+.2f}")
            self._manage_active_position(pos)
            return {
                "iteration": self.iteration_count,
                "status": "MONITORING_POSITION",
                "position": pos,
                "session_summary": summary
            }

        # Step 5: Fetch Market Data and Render Candlestick Chart
        df_m15 = self.broker.get_market_data(symbol="XAUUSD", timeframe="M15", bars=60)
        if len(df_m15) < 30:
            logger.warning(f"{log_prefix} Insufficient bars ({len(df_m15)}). Waiting for more data.")
            return {"iteration": self.iteration_count, "status": "INSUFFICIENT_DATA"}
            
        self.last_chart_path = generate_candlestick_chart(
            df=df_m15,
            timeframe="M15",
            symbol="XAUUSD"
        )

        # Step 6: Multimodal Vision + Quant Confluence Analysis
        vision_result = self.vision_analyzer.analyze_chart(
            chart_image_path=self.last_chart_path,
            df=df_m15,
            timeframe="M15"
        )
        
        confluence = self.confluence_engine.evaluate(
            df_m15=df_m15,
            vision_result=vision_result
        )
        
        action = confluence["action"]
        score = confluence["confluence_score"]
        current_price = confluence["current_price"]
        atr = confluence["atr"]
        ema_200 = float(df_m15.iloc[-1].get('ema_200', current_price))
        nearest_sr = vision_result.get("nearest_resistance") if action == "BUY" else vision_result.get("nearest_support")

        logger.info(f"{log_prefix} Market Scan: Action={action} | Score={score:+.1f} | Price={current_price:.2f} | Pattern={confluence['pattern_detected']}")

        if action not in ["BUY", "SELL"]:
            return {
                "iteration": self.iteration_count,
                "status": "WAITING_FOR_SETUP",
                "action": "HOLD",
                "confluence": confluence,
                "session_summary": summary
            }

        # Step 7: Pre-Trade Mistake Prevention Filter (Learned Rules)
        sl_candidate, tp_candidate, rr_ratio = self.risk_manager.compute_sl_tp(
            action=action,
            entry_price=current_price,
            atr=atr
        )
        
        rule_passed, rule_reason = self.pre_trade_filter.evaluate_proposal(
            action=action,
            entry_price=current_price,
            sl_price=sl_candidate,
            ema_200=ema_200,
            atr=atr,
            nearest_sr=nearest_sr
        )
        
        if not rule_passed:
            logger.warning(f"{log_prefix} PREVENTED MISTAKE: Trade vetoed by learned rules! Reason: {rule_reason}")
            return {
                "iteration": self.iteration_count,
                "status": "VETOED_BY_LEARNED_RULE",
                "reason": rule_reason,
                "session_summary": summary
            }

        # Step 8: Risk Validation and Lot Sizing
        is_valid, risk_reason, lot_size = self.risk_manager.validate_trade_proposal(
            action=action,
            entry_price=current_price,
            sl_price=sl_candidate,
            tp_price=tp_candidate,
            equity=current_equity
        )
        
        if not is_valid:
            logger.warning(f"{log_prefix} Risk rejected trade: {risk_reason}")
            return {
                "iteration": self.iteration_count,
                "status": "RISK_REJECTED",
                "reason": risk_reason,
                "session_summary": summary
            }

        # Step 9: Order Dispatch
        order_res = self.broker.open_order(
            symbol="XAUUSD",
            order_type=action,
            lots=lot_size,
            sl=sl_candidate,
            tp=tp_candidate,
            comment=f"AgenticGold_M15_Conf{int(score)}"
        )
        
        logger.info(f"{log_prefix} [ORDER DISPATCHED] {action} {lot_size} lots on XAUUSD @ {current_price:.2f} | SL: {sl_candidate:.2f} | TP: {tp_candidate:.2f} | RR: 1:{rr_ratio}")

        return {
            "iteration": self.iteration_count,
            "status": "ORDER_PLACED",
            "order": order_res,
            "lot_size": lot_size,
            "action": action,
            "entry_price": current_price,
            "sl": sl_candidate,
            "tp": tp_candidate,
            "rr_ratio": rr_ratio,
            "confluence": confluence,
            "session_summary": summary
        }

    def _reconcile_closed_trades(self) -> None:
        """Checks broker for closed orders and triggers the Trade Reflector."""
        if hasattr(self.broker, "consume_recently_closed"):
            closed_list = self.broker.consume_recently_closed()
            for closed in closed_list:
                pnl = closed.get("pnl_usd", 0.0)
                self.session_tracker.record_closed_trade(pnl)
                
                # Build TradeOutcome
                outcome = TradeOutcome(
                    ticket=closed["ticket"],
                    symbol=closed["symbol"],
                    order_type=closed["type"],
                    open_time=closed.get("open_time", ""),
                    close_time=closed.get("close_time", ""),
                    entry_price=closed["open_price"],
                    close_price=closed["close_price"],
                    lot_size=closed["lots"],
                    sl_price=closed["sl"],
                    tp_price=closed["tp"],
                    pnl_usd=pnl,
                    pnl_pct=closed.get("pnl_pct", 0.0),
                    exit_reason=closed.get("exit_reason", "UNKNOWN"),
                    confluence_score=80.0,
                    pattern_detected="CONFIRMED_SETUP",
                    ema_200=closed.get("open_price", 2650.0),
                    atr=4.0,
                    rsi=50.0
                )
                
                # Reflect and update .md journals
                reflection = self.reflector.process_closed_trade(outcome)
                logger.info(f"[SELF-LEARNING] Autopsy #{outcome.ticket} written. Diagnosis: {reflection['diagnosis_code']}")

    def _manage_active_position(self, pos: Dict[str, Any]) -> None:
        """Manages break-even stops when trade reaches +1.0 R profit."""
        open_price = pos["open_price"]
        sl = pos["sl"]
        pos_type = pos["type"]
        current_bid = self.broker.get_account_info()["bid"]
        
        # Distance between entry and initial SL
        sl_dist = abs(open_price - sl)
        if sl_dist <= 0:
            return
            
        # If BUY and price moved >= 1.0 * sl_dist in profit, move SL to entry (Break-Even)
        if pos_type == "BUY" and (current_bid - open_price) >= sl_dist and sl < open_price:
            new_sl = open_price + 0.50  # lock in tiny profit
            self.broker.modify_order(pos["ticket"], sl=new_sl)
            logger.info(f"[POSITION MANAGEMENT] Shifted SL of #{pos['ticket']} to Break-Even ({new_sl:.2f})")
            
        # If SELL
        elif pos_type == "SELL" and (open_price - current_bid) >= sl_dist and sl > open_price:
            new_sl = open_price - 0.50
            self.broker.modify_order(pos["ticket"], sl=new_sl)
            logger.info(f"[POSITION MANAGEMENT] Shifted SL of #{pos['ticket']} to Break-Even ({new_sl:.2f})")

    def run_loop(self, max_iterations: Optional[int] = None) -> None:
        """Continuous execution loop."""
        self.is_running = True
        logger.info(f"Starting Gold Day Trading Agent Loop (Broker: {self.broker_mode}, Interval: {self.poll_interval}s)...")
        
        try:
            while self.is_running:
                result = self.step()
                
                if max_iterations and self.iteration_count >= max_iterations:
                    logger.info(f"Reached max iterations ({max_iterations}). Stopping loop.")
                    break
                    
                time.sleep(self.poll_interval)
        except KeyboardInterrupt:
            logger.info("Agent loop stopped by user.")
        finally:
            self.is_running = False
