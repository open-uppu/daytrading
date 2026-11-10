# 3-Hour Review Log

## 2026-11-09 01:00 (UTC+7) — round 0 (demo, fan-out 4 subagents)

- bridge ONLINE, acct 416568420, USD 474.68
- XAU: ตลาดปิด (แท่งสุดท้าย ศุกร์ 2026-11-06 21:55 UTC) → WAIT
- BTC: WAIT — กลาง range, ใต้ EMA20/50 M5, M15 EMA แบน
- ETH: WAIT — ใต้ EMA20/50, RSI 40, ยังไม่แตะ BB ล่างพร้อม RSI ≤ 30
- corr(BTC, ETH) = 0.923 ทิศเดียวกัน
- news: FF 429 → cache null → news gate fail-open
- **แก้บั๊กของผมเอง**: bars endpoint ใช้ `timeframe=` ไม่ใช่ `tf=` (tf= ถูกเมิน → ได้ M15 เงียบ ๆ)
- ข้อจำกัดจริง: EMA200 คำนวณไม่ได้ (มีไม่ถึง 200 แท่ง)
- decision: ไม่เปิดไม้ใหม่ทุกสินทรัพย์; รอ XAU เปิด ~05:00 ICT

---

## 2026-11-09 09:00 (UTC+7) — round 1 (fan-out 4 subagents)

**สถานะระบบ**: bridge ONLINE, MT5 connected, acct 416568420, equity 474.68
**ข้อมูล**: สดทุก symbol (age 4s), M5 step 300s ✅ (ใช้ `timeframe=` ถูกต้อง)

### ผลรายสินทรัพย์
- **XAUUSD: WAIT** — trend ขึ้น (M15 EMA20 4090.43 > EMA50 4076.07) แต่ราคา 4123 ยืดเกิน 3 ATR เหนือ EMA20, RSI 77
  - เงื่อนไขเข้า: limit BUY 4108–4112 (ต้องมี M5 ปิดเหนือ 4108), SL 4099.5, TP1 4127 / TP2 4138 (RR 1.62 / 2.67)
  - invalidation: M15 ปิดต่ำกว่า 4099.5
  - Sunday gap: ปิดศุกร์ 4071.13 → เปิด 4061.55 → low 4054.11 → วิ่งขึ้น 4127.01
- **BTC / ETH: ไม่วิเคราะห์** — ปิดการเทรด crypto M5 แล้ว (sweep: −58.86% / −57.30%)

### ข่าว/เซสชัน
- ไม่มี USD high-impact ในหน้าต่าง 02:00–05:00Z (ยืนยันจากปฏิทินภายนอก)
- **news gate ตาบอด**: FF cache null + เก่า 8 ชม. → fail open
- London open จริงคือ **08:00Z (15:00 ICT)** ไม่ใช่ 07:00Z — spread ถ่าง 14:00–16:00 ICT
- ความเสี่ยง: MID (ตลาด Asia บาง + CPI 10 พ.ย. 13:30Z)

### ปัญหาเชิงระบบที่เจอรอบนี้
1. **บอทเทรดทองไม่ได้เลยที่ risk 0.5%**: min lot 0.01 = $10.62/10.6 จุด แต่ budget = $2.33 → **reject 431 ครั้ง**
   → ต้องมีทุน ~$2,100 หรือเพิ่ม risk เป็น ~2.25% (ไม่แนะนำ) หรือเปลี่ยน instrument
2. **TP ใน live ยัง hardcode 1.5R** (`base_agent.py:664`) ทั้งที่ config ตั้ง 2.5 → แก้เป็น `config.target_rr_ratio` แล้ว (เทสต์ 210 ผ่าน)
3. ไม้ค้างจากรอบก่อน: 2 ไม้ (23:01, 23:06 UTC) SL_HIT ทั้งคู่ −$8.37, RR จริง 1.42 (ยืนยันว่าเป็นโค้ดเก่า)

### การตัดสินใจ
- คง paper loop (gold only) — แม้จะยังเทรดไม่ได้เพราะ sizing
- ไม่เปิด live
- next_check: 12:00 ICT

### Sizing feasibility (research/sizing-feasibility.md)
- ATR14 M5 = 7.95 -> SL 1.25xATR = 9.94 USD -> min lot 0.01 (1 oz)  riesgo จริง 9.94 = **2.09% equity** = 4.27x งบ 0.5%
- ต้องมี risk >= 1.07% (ที่ 466) หรือทุน >= 994 (ผ่าน gate) / >= 1988 (ได้ 0.5% จริง)
- ช่วง risk 1.07-2.13% lot ยังถูก clamp 0.01 -> risk จริงคงที่ 2.09% (config กลายเป็นตัวเลขหลอก)
- max_open_positions=1 + trailing BE off -> daily 5% cap = 2.39R => ขาดทุน 2 ไม้ (-4.19%) ไม้ที่ 3 ถูกบล็อก
- แนะนำ: เติมทุน 1,000 + risk 1% (lot 0.0101 -> 0.01, risk จริง 0.99%, 5% = 5R)
- หมายเหตุ: max_lot ทองที่ใช้จริง 10.0 (override config 5.0); XAG 5000 oz แย่กว่า, XPT 100 oz เท่ากัน

### ปิดรอบ: รัน paper แบบจำลองทุน \,000 (ไม่ได้เติมเงินจริง)
- เหตุผล: ที่ทุน 466 ทุกไม้ถูก reject (risk จริง 2.09% vs งบ 0.5%)
- ตั้ง state จำลอง journal/dev_sim1000 (balance 1000, day_start 1000) + env RISK_PER_TRADE_PCT=0.01
- ไม้แรก: BUY 0.01 @ 4129.67 | SL 4119.68 | TP 4154.21 -> **RR 2.46** (ยืนยันว่า fix TP มีผลจริง) | risk \.99 = 1.0%
- หมายเหตุ: บอทเข้าซื้อที่ 4129 หลัง analyst บอกว่า overextended (รอ 4108-4112) -> cadence pacer ฝืนเข้า
- พบ loop ซ้ำ 2 ตัว (dev_gold) จาก restart ก่อนหน้า -> kill แล้ว เหลือตัวเดียว (pid 382)
- รีวิวไม้ค้าง: 2 ไม้ (23:01, 23:06 UTC) SL_HIT ทั้งคู่ -\.37, RR จริง 1.42 = โค้ดเก่า (ก่อน fix)
- next_check: 12:00 ICT

## 2026-11-09 10:05 (UTC+7) — เปลี่ยนเป็น MT5 จริง (บัญชี demo)
- คำสั่งผู้ใช้: ให้เทรดบน MT5
- ปิด paper loop ทั้งหมด (dev_gold, dev_sim1000)
- เริ่ม: --agent=gold --mode=mt5 --interval=10 --continuous --journal-dir=journal/mt5_live
  env: RISK_PER_TRADE_PCT=0.011, CADENCE_PACER_ENABLED=false
- บัญชี: Exness-MT5Trial14 (demo) 416568420, USD 474.68
- สถานะ: HOLD (รอ setup) — queued commands = 0, open positions = 0
- ข้อจำกัด sizing: min lot 0.01 + SL ~10 จุด = risk ~\.94 = **2.09% ของทุน** (config เขียน 1.1% แต่ lot ถูก clamp)
- daily cap 5% = 2.39R => ขาดทุน 2 ไม้ (-4.19%) ไม้ที่ 3 ถูกบล็อก

## 2026-11-09 10:55 (UTC+7) — ปิด daily -5% cutoff ตามคำสั่ง
- เพิ่ม flag --no-loss-cutoff (config.daily_max_loss_cutoff_enabled=False)
- ปิดทั้ง: squad halt, specialist can_open_new_trade, remaining daily allowance, portfolio open-risk cap
- รีสตาร์ท: --agent=gold --mode=mt5 --continuous --no-loss-cutoff
- แบนเนอร์ยืนยัน: Loss Cutoff: OFF | broker margin is the only floor
- ทดสอบ 39 passed (risk/agents/cli)

## 2026-11-09 14:41 (UTC+7) — ผู้ใช้ยืนยัน: เทรดต่อ + ปรับกลยุทธ์ทุก 3 ชม.
- ไม่หยุดลูป MT5 (gold, continuous, no-loss-cutoff) ยังวิ่ง pid 559
- equity 497.20, ไม้ค้าง 0, ยัง HOLD ไม่มี ORDER_PLACED
- อัปเดต runbook Phase 3 + schedule 15/18/21/00 ให้วิเคราะห์แล้วปรับได้ 1 ปุ่มต่อรอบถ้ามีหลักฐาน
- รอบปรับจริงรอบแรก: 15:00 ICT

## 2026-11-09 15:00 (UTC+7) — รอบเทรด+ปรับกลยุทธ์
- bridge OK, loop gold mt5 continuous no-loss-cutoff ยังวิ่ง (pid 559)
- equity 497.20 (+4.74% vs day start 474.68) ไม้ค้าง 0 | ORDER_PLACED=0 | Risk rejected=0
- XAU M5 close ~4089.4 | EMA20 4099.9 EMA50 4107.7 | RSI14 27.7 (นอกกรอบ 44-68) | death cross ~23 แท่งก่อน
- XAU M15 EMA20 4106 > EMA50 4098 (ยังขาขึ้นใหญ่) แต่ราคาต่ำกว่า EMA20 = pullback ไม่ใช่เทรนด์ลงชัด
- BTC/ETH: ไม่เปิดบอท (sweep ติดลบ) | ETH bias BEAR จาก analyst
- แผน: WAIT | คงเดิม (ไม่เปิด pacer, ไม่ผ่อน RSI)
- เหตุผล Phase 3: 0 ไม้จริง แต่ MTF ขัดกัน + RSI oversold + London open spread → ยังไม่มีหลักฐานว่าต้องบังคับเข้า
- ถ้า 18:00 ยัง 0 ไม้ และ M5/M15 align ทางเดียวกัน จะเปิด cadence pacer ชั่วคราว 1 รอบ
- next_check: 18:00 ICT

## 2026-11-09 18:00 (UTC+7) — รอบเทรด+ปรับกลยุทธ์
- bridge OK, loop gold mt5 continuous no-loss-cutoff วิ่ง
- equity ~464-472, balance 454.68, day start 474.68, ประมาณ -2.3% ถึง -4.2%
- ไม้ที่เปิดในรอบนี้ 16 fills ทุก ~5 นาที เพราะนับไม้ค้างไม่เจอ (XAUUSDm != XAUUSD) เลยทะลุเพดาน 1
- ปรับ 1 อย่าง: จับคู่สัญลักษณ์แบบตัด suffix ก่อนนับ max_open_positions แล้วรีสตาร์ทลูป
- ยืนยันหลังรีสตาร์ท: Max open positions reached (5/1) — ไม่เปิดไม้ใหม่ ไม่ปิดไม้เก่า
- BTC/ETH bias ลง ไม่เปิดบอท | ข่าวใน 3 ชม. ไม่มี USD High (Bowman Low 20:40 ICT) | CPI พรุ่งนี้ 20:30 ICT
- แผน: คงทิศ WAIT สำหรับไม้ใหม่จนกว่าไม้ค้างจะต่ำกว่า 1
- next_check: 21:00 ICT
