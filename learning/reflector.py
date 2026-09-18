"""
Self-Learning and Post-Trade Reflection Engine.
Conducts post-trade autopsies, diagnoses mistakes, updates markdown journals, and filters prospective trades.
"""

from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from datetime import datetime
from pydantic import BaseModel
import re
import logging
from config import config

logger = logging.getLogger("trade_reflector")


class TradeOutcome(BaseModel):
    """Encapsulates all telemetry of a completed trade."""
    ticket: int
    symbol: str = "XAUUSD"
    order_type: str  # "BUY" or "SELL"
    open_time: str
    close_time: str
    entry_price: float
    close_price: float
    lot_size: float
    sl_price: float
    tp_price: float
    pnl_usd: float
    pnl_pct: float
    exit_reason: str  # "TP_HIT", "SL_HIT", "TRAILING_STOP", "MANUAL"
    confluence_score: float
    pattern_detected: str
    ema_200: float
    atr: float
    rsi: float
    nearest_sr: Optional[float] = None
    notes: Optional[str] = ""


class TradeReflector:
    """Manages trade autopsies, mistake learning, and markdown persistence."""

    def __init__(
        self,
        trades_dir: Path = None,
        learned_rules_file: Path = None,
        mistakes_db_file: Path = None
    ):
        self.trades_dir = trades_dir or config.trades_dir
        self.learned_rules_file = learned_rules_file or config.learned_rules_file
        self.mistakes_db_file = mistakes_db_file or config.mistakes_db_file
        
        self.trades_dir.mkdir(parents=True, exist_ok=True)

    def diagnose_trade(self, trade: TradeOutcome) -> Tuple[str, str, Optional[str]]:
        """
        Diagnoses whether a mistake occurred, identifies root cause, and proposes a rule.
        Returns: (diagnosis_code, diagnosis_explanation, proposed_rule)
        """
        sl_dist = abs(trade.entry_price - trade.sl_price)
        
        # Scenario A: Losing Trade (SL Hit or negative PnL)
        if trade.pnl_usd < 0:
            # 1. Counter-trend check against EMA 200
            if trade.order_type == "BUY" and trade.entry_price < trade.ema_200:
                return (
                    "MISTAKE_COUNTER_HTF_TREND",
                    f"Bought at {trade.entry_price:.2f} while below EMA 200 ({trade.ema_200:.2f}). Gold was in macro downtrend.",
                    "RULE-HTF-TREND: Never BUY when price is below EMA 200 without verified multi-timeframe breakout."
                )
            if trade.order_type == "SELL" and trade.entry_price > trade.ema_200:
                return (
                    "MISTAKE_COUNTER_HTF_TREND",
                    f"Sold at {trade.entry_price:.2f} while above EMA 200 ({trade.ema_200:.2f}). Gold was in macro uptrend.",
                    "RULE-HTF-TREND: Never SELL when price is above EMA 200 without verified multi-timeframe breakdown."
                )
                
            # 2. Key S/R Proximity check
            if trade.nearest_sr is not None:
                sr_dist = abs(trade.entry_price - trade.nearest_sr)
                if sr_dist < (0.8 * trade.atr):
                    if trade.order_type == "BUY" and trade.entry_price <= trade.nearest_sr:
                        return (
                            "MISTAKE_TRADING_INTO_MAJOR_SR",
                            f"Bought into overhead resistance at {trade.nearest_sr:.2f} within {sr_dist:.2f} points (< 0.8 ATR).",
                            "RULE-SR-PROXIMITY: Never BUY when distance to nearest Resistance is under 1.0 ATR."
                        )
                    if trade.order_type == "SELL" and trade.entry_price >= trade.nearest_sr:
                        return (
                            "MISTAKE_TRADING_INTO_MAJOR_SR",
                            f"Sold directly into support level at {trade.nearest_sr:.2f} within {sr_dist:.2f} points (< 0.8 ATR).",
                            "RULE-SR-PROXIMITY: Never SELL when distance to nearest Support is under 1.0 ATR."
                        )
                        
            # 3. Stop loss buffer check
            if sl_dist < (1.2 * trade.atr):
                return (
                    "MISTAKE_SL_TOO_TIGHT",
                    f"Stop-loss distance ({sl_dist:.2f}$) was too tight for current ATR ({trade.atr:.2f}$). Hunted by normal gold noise.",
                    "RULE-SL-BUFFER: Minimum SL distance must be at least 1.3 * ATR to absorb market fluctuations."
                )
                
            # 4. Low volatility chop check
            if trade.atr < 2.0:
                return (
                    "MISTAKE_LOW_VOLATILITY_CHOP",
                    f"Entered trade during very low ATR ({trade.atr:.2f}$). Gold was trapped in low liquidity chop.",
                    "RULE-MIN-VOLATILITY: Cease trading when 14-period ATR is below 2.0 points."
                )
                
            # 5. General negative outcome with valid rules
            return (
                "STATISTICAL_NORMAL_LOSS",
                "Trade followed system rules; loss was within statistical distribution.",
                None
            )
            
        # Scenario B: Winning Trade (Positive PnL)
        else:
            return (
                "CLEAN_HIGH_PROBABILITY_WIN",
                f"Trade hit {trade.exit_reason} with profit of +${trade.pnl_usd:.2f} (+{trade.pnl_pct:.2f}%). Good confluence.",
                None
            )

    def write_trade_autopsy(self, trade: TradeOutcome, diagnosis_code: str, explanation: str, proposed_rule: Optional[str]) -> Path:
        """Writes an individual autopsy markdown file for the trade."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        file_path = self.trades_dir / f"{date_str}_trade_{trade.ticket}.md"
        
        status_badge = "[WIN]" if trade.pnl_usd >= 0 else "[LOSS]"
        content = f"""# Trade Autopsy: #{trade.ticket} {status_badge}

- **Symbol**: {trade.symbol} ({trade.order_type})
- **Entry Price**: {trade.entry_price:.2f} | **Exit Price**: {trade.close_price:.2f}
- **Open Time**: {trade.open_time} | **Close Time**: {trade.close_time}
- **Volume**: {trade.lot_size} lots
- **Net PnL**: ${trade.pnl_usd:+.2f} ({trade.pnl_pct:+.2f}%)
- **Exit Trigger**: `{trade.exit_reason}`
- **Confluence Score at Entry**: {trade.confluence_score}
- **Pattern Detected**: {trade.pattern_detected}

---

## Technical Context at Entry

- **EMA 200**: {trade.ema_200:.2f}
- **ATR(14)**: {trade.atr:.2f}
- **RSI(14)**: {trade.rsi:.2f}
- **Nearest S/R**: {f'{trade.nearest_sr:.2f}' if trade.nearest_sr else 'None detected'}

---

## Post-Trade Autopsy & Root Cause

- **Diagnosis Code**: `{diagnosis_code}`
- **Findings**: {explanation}

### Self-Learning Reflection
"""
        if proposed_rule:
            content += f"""
> [!IMPORTANT]
> **Actionable Lesson Learned**:
> {proposed_rule}
"""
        else:
            content += "\nExecution was aligned with system strategy guidelines.\n"

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
            
        return file_path

    def update_learned_rules_file(self, proposed_rule: str, diagnosis_code: str) -> None:
        """Appends a new rule to learned_rules.md if not already recorded."""
        if not self.learned_rules_file.exists():
            return
            
        with open(self.learned_rules_file, "r", encoding="utf-8") as f:
            existing = f.read()
            
        # Avoid duplicate rules
        if proposed_rule in existing or diagnosis_code in existing:
            return
            
        rule_block = f"""
### RULE-{datetime.now().strftime('%m%d%H%M')}: {diagnosis_code.replace('_', ' ').title()}
- **Category**: Self-Learned Protection
- **Condition**: {proposed_rule}
- **Action on Violation**: REJECT trade.
- **Confidence**: High (Derived from trade autopsy)
"""
        with open(self.learned_rules_file, "a", encoding="utf-8") as f:
            f.write(rule_block)

    def process_closed_trade(self, trade: TradeOutcome) -> Dict[str, Any]:
        """Main method to process, autopsy, and learn from a closed trade."""
        code, explanation, rule = self.diagnose_trade(trade)
        autopsy_path = self.write_trade_autopsy(trade, code, explanation, rule)
        
        if rule:
            self.update_learned_rules_file(rule, code)
            
        return {
            "ticket": trade.ticket,
            "diagnosis_code": code,
            "explanation": explanation,
            "proposed_rule": rule,
            "autopsy_path": str(autopsy_path)
        }


class PreTradeFilter:
    """Evaluates prospective trade orders against the active learned_rules.md rulebook."""

    def __init__(self, learned_rules_file: Path = None):
        self.learned_rules_file = learned_rules_file or config.learned_rules_file

    def evaluate_proposal(
        self,
        action: str,
        entry_price: float,
        sl_price: float,
        ema_200: float,
        atr: float,
        nearest_sr: Optional[float] = None
    ) -> Tuple[bool, str]:
        """
        Validates setup against learned rules before allowing trade dispatch.
        Returns: (passed: bool, reason: str)
        """
        # 1. Rule Check: Respect HTF Trend (EMA 200)
        if action == "BUY" and entry_price < ema_200:
            return False, f"RULE_VIOLATION [RULE-001]: Cannot BUY below EMA 200 ({entry_price:.2f} < {ema_200:.2f})"
        if action == "SELL" and entry_price > ema_200:
            return False, f"RULE_VIOLATION [RULE-001]: Cannot SELL above EMA 200 ({entry_price:.2f} > {ema_200:.2f})"

        # 2. Rule Check: Key S/R Proximity
        if nearest_sr is not None:
            sr_dist = abs(entry_price - nearest_sr)
            if sr_dist < (1.0 * atr):
                if action == "BUY" and entry_price <= nearest_sr:
                    return False, f"RULE_VIOLATION [RULE-002]: Cannot BUY into resistance at {nearest_sr:.2f} (dist {sr_dist:.2f} < 1.0 ATR)"
                if action == "SELL" and entry_price >= nearest_sr:
                    return False, f"RULE_VIOLATION [RULE-003]: Cannot SELL into support at {nearest_sr:.2f} (dist {sr_dist:.2f} < 1.0 ATR)"

        # 3. Rule Check: Stop-Loss buffer
        sl_dist = abs(entry_price - sl_price)
        if sl_dist < (1.2 * atr):
            return False, f"RULE_VIOLATION [RULE-004]: SL buffer too tight ({sl_dist:.2f} < 1.2 * ATR {1.2*atr:.2f})"

        return True, "Passed all pre-trade learned rules checks"
