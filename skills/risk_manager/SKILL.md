---
name: risk-manager
description: Risk management and daily target control skill enforcing 3% daily profit targets, daily drawdown limits, dynamic ATR-based lot sizing for XAUUSD, and minimum 1:1.5 to 1:2 Risk-to-Reward.
version: 1.0.0
---

# Risk Manager Skill

This skill enforces strict capital preservation and guarantees that the agent executes only mathematically sound trades aligned with the **daily 3% net profit target**.

## Core Mathematical Principles

1. **Daily Profit Target (>= 3.0%)**:
   - Starting daily balance is recorded at the start of each daily trading session (00:00 UTC / broker server rollover).
   - `Target Profit = Starting Balance * 0.03`
   - Example: On a $10,000 account, the daily target is **$300.00**.
   - **Daily Target Lockout**:
     - When cumulative closed profits for the day reach `>= 3.0%`, the state changes to `DAILY_TARGET_REACHED`.
     - No further trade entries are permitted for the rest of the day.
     - Protects capital from overtrading, greed, and evening session chop.

2. **Daily Loss Cutoff (Max -2.0%)**:
   - `Max Daily Loss = Starting Balance * 0.02`
   - Example: On a $10,000 account, maximum daily loss is **-$200.00**.
   - If cumulative daily loss hits this cutoff, all active positions are closed and trading is halted until the next day.

3. **Per-Trade Risk & Lot Sizing for Gold (XAUUSD)**:
   - Risk per trade is limited to **1.0% to 1.5%** of current equity.
   - For XAUUSD:
     - 1.00 standard lot = 100 troy ounces.
     - A $1.00 price change in Gold equals $100 profit/loss per 1.00 lot.
     - Formula:
       ```
       Risk_USD = Current_Equity * Risk_Percentage (e.g. 0.01)
       SL_Distance_USD = abs(Entry_Price - Stop_Loss_Price)
       Lot_Size = Risk_USD / (SL_Distance_USD * 100)
       Lot_Size = round(max(0.01, min(Lot_Size, Max_Allowed_Lot)), 2)
       ```
     - Example: Equity = $10,000, Risk = 1% ($100), Entry = 2650.00, SL = 2646.00 (Distance = $4.00):
       `Lot_Size = 100 / (4.00 * 100) = 0.25 lots`.
       If price hits SL, loss is exactly $100 (1.0%).

4. **Dynamic ATR-Based SL & TP**:
   - `Stop Loss = Entry - (1.5 * ATR)` for BUY, or `Entry + (1.5 * ATR)` for SELL.
   - `Take Profit = Entry + (SL_Distance * 1.5 to 2.0)` (guarantees Risk-Reward ratio >= 1:1.5 to 1:2).
   - If Risk:Reward < 1:1.5, the trade setup is rejected immediately.
