"""
Base Specialist Agent for Multi-Asset Trading System.
Provides the abstract lifecycle and execution core for asset-specific specialists (Gold, Bitcoin, Ethereum).
"""

from typing import Dict, Any, Optional, Tuple
from abc import ABC, abstractmethod
from pathlib import Path
from datetime import datetime, timezone
import logging
import pandas as pd

from config import config
from mt4.broker_interface import BaseBroker
from mt4.paper_broker import PaperTradingBroker
from mt5.bridge_server import MT5BridgeBroker, MarketDataStale
from mt4.bridge_server import MT4BridgeBroker
from risk.manager import DailySessionTracker, RiskManager, load_daily_trade_state, save_daily_trade_state
from core.news_calendar import fetch_ff_calendar, get_news_window_status
from core.sentiment import get_cached_value
from core.chart_generator import generate_candlestick_chart
from core.indicators import compute_all_indicators, analyze_candlestick_patterns
from core.vision_analyzer import VisionAnalyzer
from core.ml_filter import MLQuantFilter
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
        timeframe: str = "M5",
        contract_size: float = 100.0,
        min_lot: float = 0.01,
        max_lot: float = 10.0,
        min_sl_dist: float = 2.0,
        broker: Optional[BaseBroker] = None,
        broker_mode: str = "paper",
        initial_balance: Optional[float] = None,
        journal_dir: Optional[Path] = None,
        strategy_type: str = "trend",
        max_open_positions: Optional[int] = None,
        min_entry_interval_sec: Optional[int] = None
    ):
        self.symbol = symbol
        self.asset_name = asset_name
        self.timeframe = timeframe
        self.contract_size = contract_size
        self.min_lot = min_lot
        self.max_lot = max_lot
        self.min_sl_dist = min_sl_dist
        self.strategy_type = strategy_type
        self.max_open_positions = max_open_positions or config.max_open_positions
        self.min_entry_interval_sec = min_entry_interval_sec if min_entry_interval_sec is not None else getattr(config, "min_entry_interval_sec", 300)
        self.last_entry_time: Optional[datetime] = None
        
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

        # 3. Risk & Session Management (Daily 3% target, 0.5% M5 scalper risk, 1.5% M15 risk)
        self.session_tracker = DailySessionTracker(
            starting_balance=self.initial_balance,
            target_pct=config.daily_target_pct,
            max_loss_pct=config.daily_max_loss_pct
        )
        # Restore today's already-realized PnL/ticket set so a restart cannot
        # re-count a closed trade the EA's rolling-window telemetry re-reports.
        self.daily_trade_state_file = self.journal_dir / "daily_trade_state.json"
        # Per-agent cache file (like daily_trade_state_file above): a shared
        # file across specialists would need locking since get_cached_value
        # isn't safe for concurrent writers, and would break test isolation.
        # All three symbols quote in USD, so a redundant fetch per agent per
        # TTL window (a free, keyless endpoint) is a fine tradeoff.
        self.news_calendar_cache_file = self.journal_dir / "ff_calendar_cache.json"
        _dts = load_daily_trade_state(self.daily_trade_state_file)
        self.session_tracker.closed_pnl_today = _dts["closed_pnl_today"]
        self.session_tracker.trades_count_today = _dts["trades_count_today"]
        self.session_tracker.wins_count_today = _dts["wins_count_today"]
        self.session_tracker.losses_count_today = _dts["losses_count_today"]
        trade_risk = getattr(config, "risk_per_trade_pct", 0.005) if self.timeframe == "M5" else 0.015
        target_rr = getattr(config, "target_rr_ratio", 1.5) if self.timeframe == "M5" else 2.0
        self.risk_manager = RiskManager(
            session_tracker=self.session_tracker,
            contract_size=self.contract_size,
            min_lot=self.min_lot,
            max_lot=self.max_lot,
            min_sl_dist=self.min_sl_dist,
            risk_pct=trade_risk,
            target_rr=target_rr
        )

        # 4. Multimodal Vision Engine & Machine Learning Filter
        self.vision_analyzer = VisionAnalyzer()
        self.ml_filter = MLQuantFilter(confidence_threshold=getattr(config, "ml_confidence_threshold", 0.75))
        
        # 5. Agent Runtime State
        self.last_chart_path: Optional[Path] = None
        self.last_signal: Dict[str, Any] = {"action": "HOLD"}
        self.iteration_count: int = 0
        self.known_closed_tickets: set = set(_dts["known_closed_tickets"])
        self.trailed_tickets: set = set()
        self.position_open_times: Dict[int, datetime] = {}
        self.exit_reasons: Dict[int, str] = {}
        self.be_sl_levels: Dict[int, float] = {}

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
            closed_trades = self.broker.consume_recently_closed(symbol=self.symbol)
        elif hasattr(self.broker, "get_closed_orders"):
            closed_trades = self.broker.get_closed_orders()
        elif hasattr(self.broker, "get_trade_history"):
            closed_trades = self.broker.get_trade_history(symbol=self.symbol, count=10)
        else:
            closed_trades = []

        for t in closed_trades:
            ticket = t.get("ticket")
            if ticket is None:
                logger.warning("[%s Specialist] Ignoring closed trade without ticket: %s", self.symbol, t)
                continue
            if ticket not in self.known_closed_tickets:
                self.known_closed_tickets.add(ticket)
                # Pop agent-side exit telemetry first so incomplete broker records
                # (which skip the autopsy below) cannot leave stale entries behind.
                smart_reason = self.exit_reasons.pop(ticket, None)
                be_level = self.be_sl_levels.pop(ticket, None)
                pnl = t.get("profit", t.get("pnl_usd", 0.0))
                self.session_tracker.record_closed_trade(pnl)
                save_daily_trade_state(self.daily_trade_state_file, {
                    "date": datetime.now(timezone.utc).date().isoformat(),
                    "closed_pnl_today": self.session_tracker.closed_pnl_today,
                    "trades_count_today": self.session_tracker.trades_count_today,
                    "wins_count_today": self.session_tracker.wins_count_today,
                    "losses_count_today": self.session_tracker.losses_count_today,
                    "known_closed_tickets": list(self.known_closed_tickets),
                })
                current_bal = self.session_tracker.starting_balance + self.session_tracker.closed_pnl_today
                logger.info(
                    f"[4. ปิดจริง / REAL-ORDER-CLOSED] {self.symbol} Ticket #{ticket} ออเดอร์ปิดแล้วในตลาด! "
                    f"| ราคาปิด: {t.get('close_price', 'N/A')} "
                    f"| กำไร/ขาดทุนจริง (Realized PnL): ${pnl:+.2f} "
                    f"| Balance พอร์ตล่าสุด: ${current_bal:,.2f}"
                )

                # Older bridge telemetry contains only ticket/symbol/PnL for a
                # closed deal.  It is enough for accounting, but not enough to
                # construct a TradeOutcome.  Never let an incomplete broker
                # record crash the whole squad (and therefore bypass risk
                # monitoring for the other assets).
                required_fields = ("type", "open_price", "close_price", "lots")
                missing = [field for field in required_fields if field not in t]
                if missing:
                    logger.warning(
                        "[%s Specialist] Recorded PnL for closed ticket #%s but skipped "
                        "autopsy; bridge telemetry is missing: %s",
                        self.symbol, ticket, ", ".join(missing),
                    )
                    continue

                # Resolve the TRUE exit reason instead of guessing from the sign of the PnL.
                broker_reason = t.get("exit_reason")
                close_p = t["close_price"]
                tp_p = t.get("tp") or 0.0
                # A trailed ticket has its SL parked at be_level, so it either stopped there or
                # ran to TP. Whichever level the close landed nearer to is what happened — the
                # paper broker reports its own stop-out as a plain "SL_HIT".
                stopped_at_be = bool(be_level) and (not tp_p or abs(close_p - be_level) < abs(close_p - tp_p))

                if smart_reason:
                    resolved_exit = smart_reason
                elif stopped_at_be:
                    resolved_exit = "BE_STOP"
                elif broker_reason and broker_reason != "MANUAL_CLOSE":
                    resolved_exit = broker_reason
                else:
                    resolved_exit = "TP_HIT" if pnl > 0 else "SL_HIT"

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
                    exit_reason=resolved_exit,
                    confluence_score=75.0,
                    pattern_detected=self.strategy_name,
                    ema_200=t.get("open_price", 0.0),
                    atr=self.min_sl_dist,
                    rsi=50.0
                )
                res = self.reflector.process_closed_trade(outcome)
                logger.info(
                    f"[4. ปิดจริง / AUTOPSY-SAVED] {self.symbol} บันทึกบทเรียนการเทรดสำเร็จ: "
                    f"รหัสชันสูตร: {res['diagnosis_code']} ➔ ไฟล์: {res['autopsy_path']}"
                )

    def _manage_active_position(self, pos: Dict[str, Any], df_main: Optional[pd.DataFrame] = None) -> bool:
        """
        Monitors real open position in the market:
        1. Executes Dynamic Trailing Break-Even (+0.50R trigger).
        2. Executes Smart Profit Exit (Opposite Signal, Wick Rejection, Band Touch, Stagnation)
           STRICTLY when net profit > 0, closing the position before hitting hard TP/SL.
        Returns: True if position was closed, False otherwise.
        """
        ticket = pos.get("ticket")
        p_type = pos.get("type", "UNKNOWN")
        lots = pos.get("lots", 0.0)
        open_price = float(pos.get("open_price", 0.0))
        sl = float(pos.get("sl", 0.0))
        tp = float(pos.get("tp", 0.0))
        bid = float(pos.get("bid", 0.0))
        ask = float(pos.get("ask", 0.0))
        current_p = bid if p_type == "BUY" else ask
        if current_p <= 0.0:
            if df_main is not None and len(df_main) > 0:
                current_p = float(df_main['close'].iloc[-1])
            elif hasattr(self.broker, "current_price"):
                current_p = float(self.broker.current_price)
            else:
                current_p = open_price

        # Accurate profit calculation across Live MT5 and Paper brokers
        calc_profit = (current_p - open_price) * lots * self.contract_size if p_type == "BUY" else (open_price - current_p) * lots * self.contract_size
        profit = float(pos.get("profit", pos.get("unrealized_pnl", calc_profit)))
        
        # Track holding duration
        if ticket and ticket not in self.position_open_times:
            self.position_open_times[ticket] = datetime.now()
        held_sec = (datetime.now() - self.position_open_times[ticket]).total_seconds() if ticket else 0.0

        logger.info(
            f"[มอนิเตอร์ออเดอร์จริง / REAL-POSITION] {self.symbol} Ticket #{ticket} ({p_type} {lots} lots) "
            f"| ราคาเข้า: {open_price:,.2f} ➔ ราคาสดตลาด: {current_p:,.2f} "
            f"| SL: {sl:,.2f} | TP: {tp:,.2f} "
            f"| กำไรลอยตัว (Floating PnL): ${profit:+.2f}"
        )

        # 1. Dynamic Trailing Break-Even (+0.50R Trigger)
        if getattr(config, "trailing_be_enabled", True) and ticket and ticket not in self.trailed_tickets and open_price > 0:
            sl_dist = abs(open_price - sl) if sl > 0 else (self.min_sl_dist * 1.5)
            trigger_dist = sl_dist * getattr(config, "trailing_be_trigger_r", 0.50)
            spread = config.spread_points if "XAU" in self.symbol else (15.0 if "BTC" in self.symbol else 1.0)
            
            if p_type == "BUY":
                profit_dist = current_p - open_price
                if profit_dist >= trigger_dist and (sl < open_price or sl == 0.0):
                    new_sl = round(open_price + spread + (0.05 * self.min_sl_dist), 2)
                    try:
                        self.broker.modify_order(ticket=ticket, sl=new_sl, tp=tp)
                        self.trailed_tickets.add(ticket)
                        self.be_sl_levels[ticket] = new_sl
                        logger.info(
                            f"[🎯 DYNAMIC-BE-ACTIVE] {self.symbol} Ticket #{ticket} กำไรบวกแตะ +${profit_dist:,.2f} "
                            f"(>= เป้าหมาย Trailing +${trigger_dist:,.2f}) -> เลื่อน SL มาบังหน้าทุนที่ ${new_sl:,.2f} สำเร็จ (ตัดความเสี่ยงขาดทุน 100%)!"
                        )
                    except Exception as e:
                        logger.warning(f"{self.symbol} Trailing modify failed for #{ticket}: {e}")

            elif p_type == "SELL":
                profit_dist = open_price - current_p
                if profit_dist >= trigger_dist and (sl > open_price or sl == 0.0):
                    new_sl = round(open_price - spread - (0.05 * self.min_sl_dist), 2)
                    try:
                        self.broker.modify_order(ticket=ticket, sl=new_sl, tp=tp)
                        self.trailed_tickets.add(ticket)
                        self.be_sl_levels[ticket] = new_sl
                        logger.info(
                            f"[🎯 DYNAMIC-BE-ACTIVE] {self.symbol} Ticket #{ticket} กำไรบวกแตะ +${profit_dist:,.2f} "
                            f"(>= เป้าหมาย Trailing +${trigger_dist:,.2f}) -> เลื่อน SL มาบังหน้าทุนที่ ${new_sl:,.2f} สำเร็จ (ตัดความเสี่ยงขาดทุน 100%)!"
                        )
                    except Exception as e:
                        logger.warning(f"{self.symbol} Trailing modify failed for #{ticket}: {e}")

        # 2. Smart Profit Exit Engine (Active early profit-taking without waiting for TP/SL lines)
        smart_exit_enabled = getattr(config, "smart_exit_enabled", True)
        min_profit_usd = getattr(config, "smart_exit_min_profit_usd", 0.20)
        
        # STRICT CONSTRAINT: Must be in profit (> 0 and >= min_profit_usd)
        if smart_exit_enabled and profit >= min_profit_usd and ticket:
            if df_main is None:
                try:
                    df_main = self.broker.get_market_data(symbol=self.symbol, timeframe=self.timeframe, bars=30)
                except Exception:
                    df_main = None

            if df_main is not None and len(df_main) >= 20:
                try:
                    df_ind = compute_all_indicators(df_main)
                    last_row = df_ind.iloc[-1]
                    prev_row = df_ind.iloc[-2]
                    
                    curr_close = float(last_row['close'])
                    curr_ema9 = float(last_row.get('ema_9', curr_close))
                    curr_ema21 = float(last_row.get('ema_21', curr_close))
                    curr_ema50 = float(last_row.get('ema_50', curr_close))
                    prev_ema9 = float(prev_row.get('ema_9', curr_close))
                    prev_ema21 = float(prev_row.get('ema_21', curr_close))
                    rsi = float(last_row.get('rsi_14', 50.0))
                    
                    rm = df_ind['close'].rolling(20).mean()
                    rstd = df_ind['close'].rolling(20).std()
                    upper_bb = float(rm.iloc[-1] + (rstd.iloc[-1] * 2.0))
                    lower_bb = float(rm.iloc[-1] - (rstd.iloc[-1] * 2.0))
                    
                    candle_p = analyze_candlestick_patterns(last_row, prev_row)
                    
                    should_close = False
                    exit_reason = ""
                    
                    # A. Opposite Technical Signal
                    if p_type == "BUY":
                        if (prev_ema9 >= prev_ema21 and curr_ema9 < curr_ema21) or (curr_close < curr_ema50):
                            should_close = True
                            exit_reason = "Opposite Signal (Bearish EMA Cross / Breakdown under EMA 50)"
                        elif rsi >= 70.0 and (last_row['close'] < last_row['open']):
                            should_close = True
                            exit_reason = f"RSI Overbought Reversal (RSI: {rsi:.1f})"
                    elif p_type == "SELL":
                        if (prev_ema9 <= prev_ema21 and curr_ema9 > curr_ema21) or (curr_close > curr_ema50):
                            should_close = True
                            exit_reason = "Opposite Signal (Bullish EMA Cross / Breakout above EMA 50)"
                        elif rsi <= 30.0 and (last_row['close'] > last_row['open']):
                            should_close = True
                            exit_reason = f"RSI Oversold Reversal (RSI: {rsi:.1f})"
                    
                    # B. Wick Rejection / Momentum Stall Exit
                    if not should_close:
                        wick_thresh = getattr(config, "smart_exit_wick_threshold", 0.35)
                        if p_type == "BUY" and (candle_p.get("upper_wick_ratio", 0.0) >= wick_thresh or candle_p.get("bearish_pin", False)):
                            should_close = True
                            exit_reason = f"Upper Wick Rejection ({candle_p.get('upper_wick_ratio', 0.0)*100:.0f}%)"
                        elif p_type == "SELL" and (candle_p.get("lower_wick_ratio", 0.0) >= wick_thresh or candle_p.get("bullish_pin", False)):
                            should_close = True
                            exit_reason = f"Lower Wick Rejection ({candle_p.get('lower_wick_ratio', 0.0)*100:.0f}%)"
                    
                    # C. Bollinger Band Extreme Touch Exit
                    if not should_close and upper_bb > 0:
                        if p_type == "BUY" and current_p >= upper_bb:
                            should_close = True
                            exit_reason = f"Upper Bollinger Band Touch ({current_p:,.2f} >= {upper_bb:,.2f})"
                        elif p_type == "SELL" and current_p <= lower_bb:
                            should_close = True
                            exit_reason = f"Lower Bollinger Band Touch ({current_p:,.2f} <= {lower_bb:,.2f})"
                    
                    # D. Stagnation Timeout
                    if not should_close:
                        max_hold = getattr(config, "smart_exit_max_hold_sec", 1200)
                        if held_sec >= max_hold and len(df_ind) >= 3:
                            if p_type == "BUY" and (df_ind['high'].iloc[-1] <= df_ind['high'].iloc[-2]):
                                should_close = True
                                exit_reason = f"Stagnation Timeout ({int(held_sec/60)}m in profit, momentum stalled)"
                            elif p_type == "SELL" and (df_ind['low'].iloc[-1] >= df_ind['low'].iloc[-2]):
                                should_close = True
                                exit_reason = f"Stagnation Timeout ({int(held_sec/60)}m in profit, momentum stalled)"
                                
                    if should_close:
                        logger.info(
                            f"[🎯 SMART-PROFIT-EXIT] {self.symbol} Ticket #{ticket} ({p_type} {lots} lots) "
                            f"-> ปิดทำกำไรก่อนชนเส้น TP ทันที! เหตุผล: {exit_reason} | กำไร: +${profit:,.2f}"
                        )
                        self.broker.close_order(ticket)
                        # Only attribute the exit once the close actually went through:
                        # a rejected close leaves the position open on its hard SL.
                        self.exit_reasons[ticket] = f"SMART_EXIT:{exit_reason}"
                        self.position_open_times.pop(ticket, None)
                        self._reconcile_closed_trades()
                        return True
                except Exception as e:
                    logger.warning(f"{self.symbol} Error evaluating smart profit exit for #{ticket}: {e}")

        return False

    def _check_entry_cooldown(self) -> Tuple[bool, str]:
        """Ensures at least min_entry_interval_sec (e.g. 10 minutes) between new entries."""
        if self.last_entry_time is None:
            return True, "No recent entry"
        elapsed = (datetime.now() - self.last_entry_time).total_seconds()
        if elapsed < self.min_entry_interval_sec:
            rem = int(self.min_entry_interval_sec - elapsed)
            return False, f"Cadence cooldown active ({rem}s remaining for 10-min target)"
        return True, f"Cooldown cleared ({int(elapsed)}s since last entry)"

    def step(self, allow_new_entry: bool = True) -> Dict[str, Any]:
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

        # 3. Check Open Positions for this Symbol & Manage them (Dynamic BE, Trailing, Smart Exit)
        all_open = self.broker.get_open_positions()
        symbol_positions = [p for p in all_open if p.get("symbol") == self.symbol]
        
        df_bars = None
        if symbol_positions:
            try:
                df_bars = self.broker.get_market_data(symbol=self.symbol, timeframe=self.timeframe, bars=30)
            except Exception as e:
                logger.debug(f"{prefix} Could not fetch market data for position management: {e}")

        active_positions = []
        for pos in symbol_positions:
            closed = self._manage_active_position(pos, df_main=df_bars)
            if not closed:
                active_positions.append(pos)
        symbol_positions = active_positions

        # 4. Check Risk Gates & Allowance for opening NEW positions
        if not allow_new_entry:
            if symbol_positions:
                return {
                    "symbol": self.symbol,
                    "asset": self.asset_name,
                    "iteration": self.iteration_count,
                    "status": "MONITORING_POSITION",
                    "reason": "Portfolio risk budget limit reached; monitoring active positions",
                    "position": symbol_positions[0],
                    "positions": symbol_positions,
                    "session_summary": summary
                }
            return {
                "symbol": self.symbol,
                "asset": self.asset_name,
                "iteration": self.iteration_count,
                "status": "PORTFOLIO_RISK_BUDGET_REACHED",
                "reason": "Existing open-position risk consumes the portfolio daily loss budget.",
                "session_summary": summary
            }

        can_trade, gate_reason = self.session_tracker.can_open_new_trade()
        if not can_trade:
            logger.info(f"{prefix} Standby: {gate_reason}")
            return {
                "symbol": self.symbol,
                "asset": self.asset_name,
                "iteration": self.iteration_count,
                "status": "MONITORING_POSITION" if symbol_positions else "LOCKED",
                "reason": gate_reason,
                "position": symbol_positions[0] if symbol_positions else None,
                "positions": symbol_positions,
                "session_summary": summary
            }

        news_status = {"blackout": False, "derisk": False, "reason": "disabled"}
        if getattr(config, "news_blackout_enabled", True):
            calendar = get_cached_value(
                self.news_calendar_cache_file,
                config.news_calendar_cache_ttl_sec,
                fetch_ff_calendar,
            )
            news_status = get_news_window_status(
                datetime.now(timezone.utc), calendar, config.news_blackout_window_min
            )
            if news_status["blackout"]:
                logger.info(f"{prefix} [NEWS-BLACKOUT] {news_status['reason']}")
                return {
                    "symbol": self.symbol,
                    "asset": self.asset_name,
                    "iteration": self.iteration_count,
                    "status": "NEWS_BLACKOUT_ACTIVE",
                    "reason": news_status["reason"],
                    "position": symbol_positions[0] if symbol_positions else None,
                    "positions": symbol_positions,
                    "session_summary": summary
                }

        if len(symbol_positions) >= self.max_open_positions:
            logger.info(
                f"{prefix} Max open positions reached ({len(symbol_positions)}/{self.max_open_positions}). Monitoring active scalp trades."
            )
            return {
                "symbol": self.symbol,
                "asset": self.asset_name,
                "iteration": self.iteration_count,
                "status": "MONITORING_POSITION",
                "position": symbol_positions[0],
                "positions": symbol_positions,
                "session_summary": summary
            }

        # Enforce cadence spacing -- also throttles retries after a FAILED
        # dispatch, which leaves no open position but must still cool down.
        can_enter, cooldown_reason = self._check_entry_cooldown()
        if not can_enter:
            status_note = f"Monitoring {len(symbol_positions)} position(s). " if symbol_positions else ""
            logger.info(f"{prefix} {status_note}{cooldown_reason}")
            return {
                "symbol": self.symbol,
                "asset": self.asset_name,
                "iteration": self.iteration_count,
                "status": "MONITORING_POSITION" if symbol_positions else "COOLDOWN",
                "reason": cooldown_reason,
                "position": symbol_positions[0] if symbol_positions else None,
                "positions": symbol_positions,
                "session_summary": summary
            }

        # 5. Fetch Market Data (Main Execution Timeframe e.g. M5)
        try:
            df_main = self.broker.get_market_data(symbol=self.symbol, timeframe=self.timeframe, bars=60)
        except MarketDataStale as exc:
            logger.info(f"{prefix} Market closed / feed frozen, no entry: {exc}")
            return {
                "symbol": self.symbol,
                "asset": self.asset_name,
                "iteration": self.iteration_count,
                "status": "MARKET_CLOSED",
                "reason": str(exc),
                "session_summary": summary
            }
        if len(df_main) < 30:
            logger.warning(f"{prefix} Insufficient bars ({len(df_main)}) for {self.symbol}.")
            return {
                "symbol": self.symbol,
                "asset": self.asset_name,
                "iteration": self.iteration_count,
                "status": "INSUFFICIENT_DATA"
            }

        # Compute technical indicators (EMA 20/50/200, ATR 14, RSI 14)
        df_main = compute_all_indicators(df_main)
        latest = df_main.iloc[-1]
        current_price = float(latest["close"])
        atr = float(latest.get("atr_14", self.min_sl_dist))
        ema_20 = float(latest.get("ema_20", current_price))
        ema_50 = float(latest.get("ema_50", current_price))
        ema_200 = float(latest.get("ema_200", current_price))
        rsi = float(latest.get("rsi_14", 50.0))

        # 5b. Multi-Timeframe (MTF) Macro Filter: Fetch HTF trend (M15) if running on M5
        htf_ema_200 = ema_200
        if self.timeframe == "M5" and getattr(config, "timeframe_htf", "M15"):
            try:
                df_htf = self.broker.get_market_data(symbol=self.symbol, timeframe=config.timeframe_htf, bars=60)
                if len(df_htf) >= 30:
                    df_htf = compute_all_indicators(df_htf)
                    htf_ema_200 = float(df_htf.iloc[-1].get("ema_200", ema_200))
            except Exception as e:
                logger.debug(f"{prefix} HTF fetch note: {e}")

        logger.info(
            f"[1. ได้รับค่าจริง / REAL-FEED] {self.symbol} ({self.timeframe}) "
            f"ราคาสด: ${current_price:,.2f} | Balance: ${current_balance:,.2f} | Equity: ${current_equity:,.2f} "
            f"| EMA(20/50/200): {ema_20:,.2f}/{ema_50:,.2f}/{ema_200:,.2f} | HTF EMA200: {htf_ema_200:,.2f} "
            f"| ATR: ${atr:,.2f} | RSI: {rsi:.1f}"
        )

        # 6. Candlestick Chart Generation
        chart_filename = f"{self.symbol.lower()}_{self.timeframe.lower()}.png"
        self.last_chart_path = generate_candlestick_chart(
            df=df_main,
            timeframe=self.timeframe,
            symbol=self.symbol,
            save_path=config.artifacts_dir / chart_filename
        )

        # 7. Evaluate Strategy Signal
        signal = self.evaluate_strategy_signal(df_main)
        self.last_signal = signal
        action = signal.get("action", "HOLD")
        reason = signal.get("reason", "Waiting for setup confirmation")

        logger.info(
            f"[2. คิดวิเคราะห์จริง / STRATEGY-ANALYSIS] {self.symbol} กลยุทธ์ [{self.strategy_name}] "
            f"➔ การตัดสินใจ: {action} ({reason})"
        )

        if action not in ["BUY", "SELL"]:
            # Cadence Pacer: Guarantee at least 1 order every 10 minutes (600s) on active market
            can_pacer = (
                getattr(config, "cadence_pacer_enabled", True)
                and len(symbol_positions) < self.max_open_positions
            )
            elapsed = (datetime.now() - self.last_entry_time).total_seconds() if self.last_entry_time else 999999
            # Market must be actively ticking (exclude flat/closed weekend forex)
            is_market_active = (len(df_main) >= 5) and (df_main['close'].iloc[-1] != df_main['close'].iloc[-5])

            if can_pacer and elapsed >= self.min_entry_interval_sec and is_market_active:
                sl_dist = max(1.3 * atr, self.min_sl_dist)
                tp_dist = round(1.5 * sl_dist, 2)
                if current_price >= htf_ema_200:
                    action = "BUY"
                    sl_candidate = round(current_price - sl_dist, 2)
                    tp_candidate = round(current_price + tp_dist, 2)
                    reason = f"{self.symbol} M5 Rapid Cadence Entry (Macro Bullish)"
                else:
                    action = "SELL"
                    sl_candidate = round(current_price + sl_dist, 2)
                    tp_candidate = round(current_price - tp_dist, 2)
                    reason = f"{self.symbol} M5 Rapid Cadence Entry (Macro Bearish)"

                signal = {"action": action, "sl": sl_candidate, "tp": tp_candidate, "reason": reason, "signal_type": "CADENCE_PACER"}
                logger.info(
                    f"[⏱️ CADENCE-PACER] {self.symbol} ครบกำหนด Cadence ({self.min_entry_interval_sec}s) "
                    f"-> ออกออเดอร์ตามเทรนด์ M5 ทันที: {action} (SL: ${sl_candidate:,.2f}, TP: ${tp_candidate:,.2f})"
                )
            else:
                return {
                    "symbol": self.symbol,
                    "asset": self.asset_name,
                    "iteration": self.iteration_count,
                    "status": "WAITING_FOR_SETUP",
                    "action": "HOLD",
                    "signal": signal,
                    "session_summary": summary
                }

        # 7b. Multi-Timeframe Macro Trend Alignment Gating
        if self.timeframe == "M5" and config.timeframe_htf:
            if action == "BUY" and current_price < htf_ema_200:
                logger.info(f"{prefix} [MTF-GATE] Vetoed BUY: Price (${current_price:,.2f}) is below HTF {config.timeframe_htf} EMA 200 (${htf_ema_200:,.2f})")
                return {
                    "symbol": self.symbol,
                    "asset": self.asset_name,
                    "iteration": self.iteration_count,
                    "status": "VETOED_BY_MTF_MACRO",
                    "reason": f"Price below HTF {config.timeframe_htf} EMA 200",
                    "session_summary": summary
                }
            elif action == "SELL" and current_price > htf_ema_200:
                logger.info(f"{prefix} [MTF-GATE] Vetoed SELL: Price (${current_price:,.2f}) is above HTF {config.timeframe_htf} EMA 200 (${htf_ema_200:,.2f})")
                return {
                    "symbol": self.symbol,
                    "asset": self.asset_name,
                    "iteration": self.iteration_count,
                    "status": "VETOED_BY_MTF_MACRO",
                    "reason": f"Price above HTF {config.timeframe_htf} EMA 200",
                    "session_summary": summary
                }

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
            atr=atr,
            signal_type=signal.get("signal_type")
        )

        logger.info(
            f"[2. คิดวิเคราะห์จริง / RULES-CHECK] {self.symbol} ตรวจสอบกฎความปลอดภัย (Pre-Trade Filter): "
            f"{'✅ ผ่านเงื่อนไข' if rule_passed else f'❌ ติดกฎข้อห้าม: ' + rule_reason}"
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

        # 8b. Machine Learning Meta-Labeling Confidence Gate
        if getattr(config, "ml_filter_enabled", True):
            is_cadence = (signal.get("signal_type") == "CADENCE_PACER")
            default_thresh = getattr(config, "ml_confidence_threshold", 0.75)
            ml_threshold = 0.75 if is_cadence else default_thresh
            ml_passed, ml_conf, ml_details = self.ml_filter.evaluate_proposal(
                signal=signal,
                df_window=df_main,
                asset_symbol=self.symbol,
                custom_threshold=ml_threshold
            )
            logger.info(
                f"[2. คิดวิเคราะห์จริง / ML-GATE] {self.symbol} ML Win Probability: {ml_conf:.1%} "
                f"(Threshold: {ml_threshold:.1%}) -> {'✅ ผ่านเงื่อนไข (PASS)' if ml_passed else '❌ ต่ำกว่าเกณฑ์ความมั่นใจ (VETOED)'}"
            )
            if not ml_passed:
                return {
                    "symbol": self.symbol,
                    "asset": self.asset_name,
                    "iteration": self.iteration_count,
                    "status": "VETOED_BY_ML_CONFIDENCE",
                    "reason": f"ML Confidence {ml_conf:.1%} below threshold {ml_threshold:.1%}",
                    "session_summary": summary
                }

        # 9. Risk Sizing & Order Validation
        news_extra_multiplier = config.daily_target_derisk_factor if news_status["derisk"] else 1.0
        is_valid, risk_reason, lot_size = self.risk_manager.validate_trade_proposal(
            action=action,
            entry_price=current_price,
            sl_price=sl_candidate,
            tp_price=tp_candidate,
            equity=current_equity,
            extra_multiplier=news_extra_multiplier
        )

        sl_dist = abs(current_price - sl_candidate)
        tp_dist = abs(tp_candidate - current_price)
        rr_ratio = tp_dist / max(sl_dist, 0.001)

        logger.info(
            f"[2. คิดวิเคราะห์จริง / RISK-SIZING] {self.symbol} คำนวณความเสี่ยงและขนาดสัญญา: "
            f"Lot Size = {lot_size} lots | Entry = ${current_price:,.2f} | SL = ${sl_candidate:,.2f} (เสี่ยง: ${sl_dist:,.2f}) "
            f"| TP = ${tp_candidate:,.2f} (เป้าหมาย: ${tp_dist:,.2f}) | R:R = 1:{rr_ratio:.1f} | ผลตรวจ: {risk_reason}"
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
        logger.info(
            f"[3. สั่งซื้อจริง / REAL-ORDER-DISPATCH] {self.symbol} กำลังส่งคำสั่ง {action} {lot_size} lots "
            f"ไปยังโบรกเกอร์ (SL: ${sl_candidate:,.2f}, TP: ${tp_candidate:,.2f})..."
        )
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
            self.last_entry_time = datetime.now()
            logger.error(
                f"[3. สั่งซื้อจริง / ORDER-FAILED] {self.symbol} ส่งคำสั่งล้มเหลว: {type(e).__name__}: {e}"
            )
            return {
                "symbol": self.symbol,
                "asset": self.asset_name,
                "iteration": self.iteration_count,
                "status": "BROKER_ERROR",
                "reason": f"{type(e).__name__}: {e}",
                "session_summary": summary
            }

        if order_res.get("confirmed") is False:
            self.last_entry_time = datetime.now()
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

        ticket = order_res.get("ticket")
        self.last_entry_time = datetime.now()
        logger.info(
            f"[3. สั่งซื้อจริง / REAL-ORDER-FILLED] {self.symbol} โบรกเกอร์ยืนยันคำสั่งสำเร็จ! "
            f"Ticket: #{ticket} | {action} {lot_size} lots @ ${current_price:,.2f} "
            f"(SL: ${sl_candidate:,.2f}, TP: ${tp_candidate:,.2f})"
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
