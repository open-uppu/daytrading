# Strategy Sweep — M5 Scalper (XAUUSD / BTCUSD / ETHUSD)

> **ขอบเขต:** งานทดลอง backtest เท่านั้น ไม่มีการเทรดจริง ไม่ได้แตะ container
> ไม่ได้แก้โค้ด production แม้แต่บรรทัดเดียว — harness ที่ใช้ sweep อยู่ใน `research/` (`strategy_sweep.py`)
> และสืบทอด (subclass) `M5BacktestEngine` เดิมโดยไม่แก้ไฟล์ต้นฉบับ
> **วันที่รัน:** 2026-11-09 (Asia/Bangkok) · **รันด้วย:** `D:\trader\daytrad\.venv\Scripts\python.exe` (Python 3.12.10, pandas 3.0.6)
> **ข้อมูล:** `data/xauusd_m5.csv` (13,634 แท่ง), `data/btcusd_m5.csv` / `ethusd_m5.csv` (17,111 แท่ง)

---

## 0) สรุปผู้บริหาร (อ่านแค่ตรงนี้ก็ได้)

1. **ห้ามเปิด trailing break-even 0.6R กับทอง M5** — นี่คือการเปลี่ยนแปลงที่ผลชัดที่สุดในรายงานนี้: เทียบกับ config เดียวกันที่ไม่มี BE (G03_rr2.0 = +0.084R IS / +0.102R OOS) การเปิด BE ที่ 0.6R ให้ **−0.211R (IS) / −0.162R (OOS)** และ BE ที่ 1.0R ก็ยังแย่ (−0.054R / −0.102R) ปัจจุบัน `config.py` ตั้ง `trailing_be_enabled=True, trailing_be_trigger_r=0.6` แต่ **backtest M5 ไม่ได้จำลอง BE เลย** → ตัวเลข backtest กับ live ไม่ตรงกัน และฝั่ง live คือฝั่งที่แย่กว่า
2. **RR ที่ดีขึ้นคือ 2.0–2.5 (จาก 1.44 ที่ hardcode อยู่)** — RR 2.5 ให้ IS +0.098R → OOS **+0.171R**, PF OOS 1.25, net OOS +5.08%; baseline ได้ IS +0.090R → OOS เพียง +0.016R (แทบศูนย์)
3. **ตัวกรอง session ของทอง (7:00–21:00 ตามเวลาในไฟล์) น่าจะกรองผิดฝั่ง** — เวลาใน CSV เป็นเวลาไทย (UTC+7) ตัวกรองนี้จึงเท่ากับ 00:00–14:00 UTC = ตัด NY afternoon (14:00–21:00 UTC) ออกทั้งช่วง ผลคือ "เทรดทั้งวัน" ชนะ baseline **ทั้ง IS และ OOS** (OOS +6.27% vs +2.85%, exp 0.147 vs 0.102, 81 vs 58 ไม้)
4. **BTCUSD / ETHUSD บน M5 ตอนนี้ขาดทุนหนักทุก config** — BTC baseline ทั้งช่วง = **−58.86%** (737 ไม้, PF 0.66) ไม่ใช่ +4.87% ตามเอกสาร และ config ที่ดีที่สุดก็ยังติดลบ (OOS exp −0.023R) → **อย่าเทรด crypto ด้วย M5 scalper เวอร์ชันนี้**
5. **ตัวเลขใน `AGENTS.md` reproduce ไม่ได้** กับโค้ดที่ commit อยู่: ทองได้ +5.78% (เอกสาร +7.75%), BTC ได้ **−58.86%** (เอกสาร +4.87%), ETH ได้ **−57.30%** (เอกสาร +1.63%) — สาเหตุที่สอดคล้องที่สุดคือ commit `e8ad97a` (19 ก.ย. 2026) ที่เพิ่ม pullback entries ให้ BTC/ETH ทำให้จำนวนไม้พุ่งจาก ~172 → 737 (BTC) และ ~396 → 1,316 (ETH)
6. **ความไม่แน่นอนสูงกว่าที่ตัวเลขดู** — SE ของ expectancy ต่อไม้อยู่ที่ ~0.10–0.22R (n=55–81 ใน OOS, และ ~0.33R สำหรับ G09 ที่ n=19) ดังนั้นส่วนต่างระหว่าง config ส่วนใหญ่ **ยังไม่ significant ทางสถิติ**; สิ่งที่พอเชื่อได้คือ "ทิศทาง" ของ BE (แย่ชัด, สอดคล้องทั้งสองช่วง) และ RR สูงขึ้น (ดีขึ้นทั้งสองช่วง)

---

## 1) อะไร "ปรับได้จริง" ในโค้ด (อ่านจากโค้ด ไม่ได้เดา)

### 1.1 ระดับ engine (`backtest/run_m5_backtest.py` — `M5BacktestEngine.__init__`)

| พารามิเตอร์ | ค่าที่ backtest ใช้จริง | หมายเหตุ |
|---|---|---|
| `risk_per_trade_pct` | `0.005` | ถูก hardcode ใน `run_single_asset_m5_backtest()` |
| `daily_target_pct` | `0.03` | lock ทั้งวันเมื่อกำไรถึง 3% |
| `daily_max_loss_pct` | `0.02` | **ไม่ตรงกับ `config.py` ที่ใช้ 0.05** |
| `max_open_positions` | `3` | hardcode |
| `cooldown_bars` | `2` (10 นาที) | hardcode |
| `min_sl_dist` | Gold 1.0 / BTC 25 / ETH 2 | กัน SL แคบเกิน |
| `spread` | Gold 0.20 / BTC 15 / ETH 1 | หัก**ครั้งเดียวตอนปิด** (ไม่ใช่ entry+exit) ไม่มี commission |
| trailing BE | **ไม่มีเลย** | `backtest/engine.py` (M15) มี แต่ M5 engine ไม่มี |

> **สำคัญ:** `run_single_asset_m5_backtest()` ไม่ได้อ่าน `config.py` เลย — แก้ `config.py` แล้ว backtest M5 จะไม่เปลี่ยน

### 1.2 ระดับกลยุทธ์ (`backtest/strategies.py` → `strategy_m5_scalper`)

| Symbol | SL | TP | RR ที่ได้จริง | Session filter |
|---|---|---|---|---|
| XAUUSD | `max(1.25*atr, 1.0)` | `1.8*atr` | **1.44** (1.8/1.25) | `7 <= hour <= 21` (เวลาในไฟล์ = UTC+7) |
| BTCUSD | `max(1.25*atr, 25)` | `1.8*atr` | 1.44 | ไม่มี |
| ETHUSD | `max(1.25*atr, 2)` | `1.8*atr` | 1.44 | ไม่มี |

ไม่มีพารามิเตอร์ `rr` / `sl_mult` / `be_trigger` / `session` ให้ปรับ → ต้องแก้โค้ดหรือ wrap เอา (งานนี้ wrap)

### 1.3 ระดับ config (`config.py`) — ค่าที่ live ใช้แต่ไม่ตรงกับ backtest

| พารามิเตอร์ | ค่า live | ค่า backtest M5 | ผล |
|---|---|---|---|
| `trailing_be_enabled` / `trailing_be_trigger_r` | `True` / `0.6` | ไม่มี BE | live ถูกตัดไม้ที่ 0.6R (ราคาปัจจุบัน) — backtest ไม่รู้เรื่อง |
| `max_open_positions` | `3` | `3` | ตรงกัน |
| `daily_max_loss_pct` | `0.05` | `0.02` | backtest เข้มกว่า live 2.5 เท่า |
| `target_rr_ratio` / `min_rr_ratio` | `2.0` / `1.3` | ไม่ได้ใช้ (hardcode 1.8/1.25) | ค่าใน config ไม่มีผลกับ M5 |

### 1.4 เวลาในข้อมูล: เป็นเวลาไทย (UTC+7) ไม่ใช่ UTC

ตรวจจากการกระจายตัวของชั่วโมงใน 61 วันของ XAUUSD: **ชั่วโมงเดียวที่แทบว่างคือ 04:00 (เหลือ 2 แท่งจาก 61 วัน)** ซึ่งตรงกับ daily break ของ CME ที่ 21:00–22:00 UTC พอดี → `file_hour = UTC + 7`
ผลที่ตามมา: ตัวกรอง `7 <= hour <= 21` ของทอง = **00:00–14:00 UTC** (เอเชีย + ลอนดอนครึ่งเช้า) และ **ตัด NY afternoon 14:00–21:00 UTC ออก** ซึ่งเป็นช่วง liquid ที่สุดของทอง
(ในการทดสอบ "ny_overlap" ผมจึงใช้ file hour 19–22 = 12:00–15:59 UTC)

---

## 2) วิธีทดสอบ

- **IS / OOS:** แบ่งตามเวลา 70% แรก / 30% หลัง (ไม่ shuffle, ไม่มี look-ahead)
  - XAUUSD: IS = 2026-07-10 11:00 → 2026-08-28 01:45 (9,543 แท่ง) · OOS = 2026-08-28 01:50 → 2026-09-19 03:55 (4,091 แท่ง)
  - BTC/ETH: IS = 2026-07-22 07:00 → 2026-09-01 21:00 (11,977 แท่ง) · OOS = 2026-09-01 21:05 → 2026-09-19 16:46 (5,134 แท่ง)
  - ทั้งสองช่วงเริ่มที่ balance $10,000 เท่ากัน, warmup 40 แท่ง
- **Fidelity check (สำคัญ):** ก่อน sweep ผมรัน engine ที่ดัดแปลงเทียบกับ `run_single_asset_m5_backtest('XAUUSD')` ตัวจริง → ได้ค่าตรงกันทุกตัว (`total_trades 177`, `win_rate 45.2`, `PF 1.11`, `return 5.78%`, `DD 7.08%`, `net_profit 577.57`) — ยืนยันว่า harness ไม่ได้เปลี่ยนพฤติกรรม baseline
- **Expectancy (R)** = ค่าเฉลี่ยของ `pnl_usd / risk_usd` ต่อไม้ โดย `risk_usd = |entry − initial_sl| × lots × contract_size` (ตัวหารเป็นความเสี่ยงตั้งต้นของไม้นั้น ไม่ใช่ % คงที่)
- **ข้อจำกัดที่ต้องรู้:**
  1. ถ้าในแท่งเดียวกันทั้ง TP และ SL โดน → engine เดิมเช็ค TP ก่อน (เอนเอียงไปทางดี) ผมคงพฤติกรรมเดิมเพื่อเทียบกันได้
  2. BE ที่ทดสอบใช้ high/low ของแท่ง (ไม่ใช่ tick) → ถ้าแท่งเดียวโดนทั้ง BE trigger และ SL เดิม จะถูกมองว่า BE ก่อน = เอนเอียงไปทางดีเช่นกัน
  3. ไม่มี slippage/commission, spread หักครั้งเดียวต่อไม้ (ของจริงมักถูกกว่าหรือแพงกว่านี้ ~ครึ่งสเปรด)
  4. OOS ยาวแค่ 18–22 วัน → n = 19–81 ไม้; SE(expectancy) ≈ 0.10–0.22R สำหรับ config ที่ n≈55–81 (และ ~0.33R สำหรับ G09 ที่ n=19) — คำนวณแบบ 2-point approximation จาก win rate + avg win/loss R เป็นค่าประมาณที่**แคบเกินจริง**
  5. sweep 14 config บน symbol เดียว = multiple testing; ค่าที่ดีที่สุดจาก OOS ก็มีโอกาสเป็น noise

### config grid ที่ใช้ (ทั้งหมดอยู่ใน `research/strategy_sweep.py`)

| ID | RR | SL×ATR | BE trigger | session | maxpos |
|---|---|---|---|---|---|
| G01_baseline | 1.44 (ตามโค้ดเดิม 1.8/1.25) | 1.25 | – | เดิม (file hour 7–21) | 3 |
| G02_rr1.5 | 1.5 | 1.25 | – | เดิม | 3 |
| G03_rr2.0 | 2.0 | 1.25 | – | เดิม | 3 |
| G04_rr2.5 | 2.5 | 1.25 | – | เดิม | 3 |
| G05_sl1.0_rr2.0 | 2.0 | 1.0 | – | เดิม | 3 |
| G06_sl1.5_rr2.0 | 2.0 | 1.5 | – | เดิม | 3 |
| G07_be0.6_rr2.0 | 2.0 | 1.25 | 0.6R | เดิม | 3 |
| G08_be1.0_rr2.0 | 2.0 | 1.25 | 1.0R | เดิม | 3 |
| G09_nyoverlap_rr2.0 | 2.0 | 1.25 | – | file hour 19–22 (=12–16 UTC) | 3 |
| G10_allday_rr2.0 | 2.0 | 1.25 | – | ไม่มี filter | 3 |
| G11_maxpos1_rr2.0 | 2.0 | 1.25 | – | เดิม | 1 |
| G12_be0.6_maxpos1_rr2.0 | 2.0 | 1.25 | 0.6R | เดิม | 1 |
| G13_allday_rr2.5 | 2.5 | 1.25 | – | ไม่มี filter | 3 |
| G14_allday_rr2.0_maxpos1 | 2.0 | 1.25 | – | ไม่มี filter | 1 |

(C01–C06 ของ crypto ใช้แกนเดียวกัน: baseline / rr2.0 / rr2.5 / be0.6 / ny_overlap / maxpos1)


---

## 3) ผล XAUUSD (14 config, IS + OOS)

`exp R` = expectancy ต่อไม้, `DD` = max drawdown จาก equity curve (รวม floating)

| Config | IS n | IS ret% | IS win% | IS PF | IS exp R | IS DD% | OOS n | OOS ret% | OOS win% | OOS PF | OOS exp R | OOS DD% |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| G01_baseline (RR 1.44, session เดิม, maxpos 3) | 119 | +5.12% | 46.2 | 1.15 | +0.090 | 7.08 | 58 | +0.49% | 43.1 | 1.03 | +0.016 | 4.91 |
| G02_rr1.5 | 119 | +6.70% | 46.2 | 1.20 | +0.118 | 6.83 | 58 | +1.28% | 43.1 | 1.07 | +0.042 | 4.81 |
| G03_rr2.0 | 115 | +4.45% | 37.4 | 1.12 | +0.084 | 8.93 | 58 | +2.85% | 37.9 | 1.15 | +0.102 | 5.88 |
| **G04_rr2.5** | 111 | +5.13% | 32.4 | 1.13 | +0.098 | 6.58 | 58 | **+5.08%** | 34.5 | **1.25** | **+0.171** | 6.61 |
| G05_sl1.0_rr2.0 | 112 | +2.66% | 36.6 | 1.07 | +0.051 | 7.30 | 58 | +5.74% | 41.4 | 1.31 | +0.197 | 4.89 |
| G06_sl1.5_rr2.0 | 115 | +2.02% | 35.7 | 1.05 | +0.039 | 7.69 | 58 | +6.11% | 41.4 | 1.34 | +0.211 | 7.13 |
| G07_be0.6_rr2.0 | 121 | **−12.29%** | 9.1 | **0.45** | **−0.211** | 12.67 | 63 | −5.16% | 12.7 | 0.60 | −0.162 | 9.05 |
| G08_be1.0_rr2.0 | 119 | −3.36% | 22.7 | 0.88 | −0.054 | 8.44 | 60 | −3.18% | 21.7 | 0.80 | −0.102 | 6.56 |
| G09_nyoverlap_rr2.0 | 42 | **+8.65%** | 47.6 | **1.73** | **+0.400** | 2.12 | 19 | +0.74% | 36.8 | 1.12 | +0.080 | 3.66 |
| G10_allday_rr2.0 | 157 | +4.92% | 36.9 | 1.10 | +0.068 | 10.47 | 81 | **+6.27%** | 39.5 | 1.24 | +0.147 | 6.38 |
| G11_maxpos1_rr2.0 | 107 | +4.67% | 37.4 | 1.14 | +0.084 | 8.67 | 55 | +3.28% | 38.2 | 1.18 | +0.111 | 5.29 |
| G12_be0.6_maxpos1_rr2.0 | 119 | −11.80% | 9.2 | 0.46 | −0.206 | 12.18 | 61 | −4.66% | 13.1 | 0.62 | −0.150 | 8.57 |
| **G13_allday_rr2.5** | 156 | +4.04% | 31.4 | 1.07 | +0.060 | 10.82 | 75 | **+8.44%** | 36.0 | **1.33** | **+0.221** | 8.10 |
| **G14_allday_rr2.0_maxpos1** | 149 | +6.24% | 37.6 | 1.13 | +0.088 | 9.84 | 77 | +5.39% | 39.0 | 1.21 | +0.131 | **5.80** |

> *หมายเหตุ win% ของ config ที่มี BE:* SL ที่ถูกเลื่อนมาที่ทุนแล้วโดน จะถูกนับเป็นไม้ "ขาดทุนเล็กน้อย" (≈ ค่า spread) ใน engine ที่ผมทดสอบ ไม่ใช่ไม้เสมอตัว/กำไรเล็กน้อยเหมือน live (live ตั้ง SL = entry + spread + buffer) → win% 9–23% ของ G07/G08/G12 จึงต่ำเกินจริง ให้ตัดสินจาก expectancy R เป็นหลัก

### จัดอันดับตาม OOS (พร้อม error bar ประมาณ)

| Config | OOS exp R | ±SE (approx) | OOS PF | OOS ret% | OOS DD% | OOS n | IS→OOS exp R | ทางออก TP/BE/SL (OOS) |
|---|---|---|---|---|---|---|---|---|
| G13_allday_rr2.5 | +0.221 | 0.194 | 1.33 | +8.44% | 8.10 | 75 | +0.161 | 27/0/48 |
| G06_sl1.5_rr2.0 | +0.211 | 0.19 | 1.34 | +6.11% | 7.13 | 58 | +0.172 | 24/0/34 |
| G05_sl1.0_rr2.0 | +0.197 | 0.19 | 1.31 | +5.74% | 4.89 | 58 | +0.146 | 24/0/34 |
| G04_rr2.5 | +0.171 | 0.22 | 1.25 | +5.08% | 6.61 | 58 | +0.073 | 20/0/38 |
| G10_allday_rr2.0 | +0.147 | 0.16 | 1.24 | +6.27% | 6.38 | 81 | +0.079 | 32/0/49 |
| G14_allday_rr2.0_maxpos1 | +0.131 | 0.167 | 1.21 | +5.39% | 5.80 | 77 | +0.043 | 30/0/47 |
| G11_maxpos1_rr2.0 | +0.111 | 0.20 | 1.18 | +3.28% | 5.29 | 55 | +0.027 | 21/0/34 |
| G03_rr2.0 | +0.102 | 0.19 | 1.15 | +2.85% | 5.88 | 58 | +0.018 | 22/0/36 |
| G09_nyoverlap_rr2.0 | +0.080 | 0.33 | 1.12 | +0.74% | 3.66 | 19 | **−0.320** | 7/0/12 |
| G02_rr1.5 | +0.042 | 0.16 | 1.07 | +1.28% | 4.81 | 58 | −0.076 | 25/0/33 |
| G01_baseline | +0.016 | 0.16 | 1.03 | +0.49% | 4.91 | 58 | −0.074 | 25/0/33 |
| G08_be1.0_rr2.0 | −0.102 | 0.14 | 0.80 | −3.18% | 6.56 | 60 | −0.048 | 13/17/30 |
| G12_be0.6_maxpos1_rr2.0 | −0.150 | 0.11 | 0.62 | −4.66% | 8.57 | 61 | +0.056 | 8/30/23 |
| G07_be0.6_rr2.0 | −0.162 | 0.10 | 0.60 | −5.16% | 9.05 | 63 | +0.049 | 8/31/24 |

**อ่านตารางให้ถูก:** ทุก config อยู่ในช่วง ±1 SE จาก baseline ⇒ **ยังสรุปเชิงสถิติไม่ได้** ว่าอันไหน "ชนะจริง" สิ่งที่ใช้ตัดสินคือ (ก) ทิศทางตรงกันทั้ง IS และ OOS (ข) กลไกที่อธิบายได้ (ค) จำนวนไม้มากพอ

### pooled expectancy (ถ่วงด้วยจำนวนไม้ทั้งสองช่วง — ใช้เป็นภาพรวมเท่านั้น)

| Config | pooled exp R | n รวม | | Config | pooled exp R | n รวม |
|---|---|---|---|---|---|---|
| G04_rr2.5 | **+0.123** | 169 | | G03_rr2.0 | +0.090 | 173 |
| G13_allday_rr2.5 | +0.112 | 231 | | G01_baseline | +0.066 | 177 |
| G14_allday_rr2.0_maxpos1 | +0.103 | 226 | | G08_be1.0_rr2.0 | −0.070 | 179 |
| G05_sl1.0_rr2.0 | +0.101 | 170 | | G12_be0.6_maxpos1_rr2.0 | −0.187 | 180 |
| G06_sl1.5_rr2.0 | +0.097 | 173 | | G07_be0.6_rr2.0 | **−0.194** | 184 |
| G10_allday_rr2.0 | +0.095 | 238 | | G09_nyoverlap_rr2.0 | (+0.300) | 61 → *n น้อยเกินกว่าจะใช้* |

(ตัด G02/G11 ซึ่งอยู่ที่ +0.093 ทั้งคู่ ออกจากตารางเพื่อความกระชับ)


---

## 4) ผล BTCUSD / ETHUSD

### BTCUSD (6 config)

| Config | IS n | IS ret% | IS PF | IS exp R | OOS n | OOS ret% | OOS PF | OOS exp R | OOS DD% |
|---|---|---|---|---|---|---|---|---|---|
| C01_baseline | 517 | −44.27% | 0.67 | −0.219 | 213 | −26.06% | 0.62 | −0.276 | 27.21 |
| C02_rr2.0 | 361 | −56.02% | 0.51 | −0.445 | 190 | −18.91% | 0.72 | −0.212 | 21.22 |
| C03_rr2.5 | 349 | −60.49% | 0.48 | −0.521 | 176 | −18.87% | 0.72 | −0.224 | 21.76 |
| C04_be0.6_rr2.0 | 427 | −61.75% | 0.25 | −0.446 | 191 | −25.19% | 0.45 | −0.299 | 26.06 |
| C05_nyoverlap_rr2.0 | 260 | −25.06% | 0.72 | −0.210 | 124 | **−1.94%** | 0.96 | **−0.023** | 9.50 |
| C06_maxpos1_rr2.0 | 415 | −42.10% | 0.68 | −0.256 | 168 | −24.04% | 0.61 | −0.323 | 25.10 |

### ETHUSD (6 config)

| Config | IS n | IS ret% | IS PF | IS exp R | OOS n | OOS ret% | OOS PF | OOS exp R | OOS DD% |
|---|---|---|---|---|---|---|---|---|---|
| C01_baseline | 1051 | −47.08% | 0.65 | −0.301 | 416 | −20.92% | 0.71 | −0.254 | 22.66 |
| C02_rr2.0 | 791 | −46.45% | 0.63 | −0.360 | 392 | −16.92% | 0.78 | −0.232 | 19.73 |
| C03_rr2.5 | 736 | −46.10% | 0.64 | −0.392 | 367 | **−11.96%** | 0.85 | **−0.210** | 20.23 |
| C04_be0.6_rr2.0 | 832 | −60.09% | 0.33 | −0.467 | 396 | −32.44% | 0.43 | −0.347 | 33.08 |
| C05_nyoverlap_rr2.0 | 400 | **−13.50%** | 0.82 | −0.199 | 138 | −24.58% | 0.34 | −0.551 | 24.58 |
| C06_maxpos1_rr2.0 | 710 | −36.74% | 0.68 | −0.332 | 293 | −19.96% | 0.67 | −0.281 | 21.08 |

**ข้อสรุป crypto:** ไม่มี config ไหนให้ expectancy เป็นบวกเลยแม้แต่ตัวเดียว (ดีสุด BTC C05 = −0.023R ซึ่งก็ยัง ≤ 0) จำนวนไม้ก็สูงมาก (BTC 517 ไม้ใน 41 วัน ≈ 12.6/วัน, ETH 1,051 ใน 41 วัน = 25.6/วัน) เทียบกับที่เอกสารอ้าง ~3 และ ~6.7 ไม้/วัน
pooled expectancy ที่ดีที่สุดก็ยังติดลบ: BTC C05 = −0.150R (baseline −0.236R) ส่วน ETH ตัวที่ดีที่สุดคือ **C01 baseline เอง = −0.288R** (config อื่นแย่กว่าทั้งหมด) ⇒ ปัญหาอยู่ที่ "สัญญาณ" ไม่ใช่ "RR/session/maxpos"

### เอกสาร vs รันซ้ำ (โค้ดเดิม ไม่แก้อะไร)

| Symbol | `AGENTS.md` อ้าง | รันซ้ำวันนี้ (full period) | ต่าง |
|---|---|---|---|
| XAUUSD | +7.75%, PF 1.13, 179 ไม้, DD 7.71% | +5.78%, PF 1.11, 177 ไม้, DD 7.08% | ใกล้เคียง (ต่างเพราะช่วงข้อมูล) |
| BTCUSD | +4.87%, PF 1.08, 172 ไม้, DD 11.5% | **−58.86%, PF 0.66, 737 ไม้, DD 58.89%** | **กลับเครื่องหมาย** |
| ETHUSD | +1.63%, PF 1.02, 396 ไม้, DD 9.03% | **−57.30%, PF 0.67, 1,316 ไม้, DD 57.33%** | **กลับเครื่องหมาย** |

สาเหตุที่สอดคล้องที่สุด: commit `e8ad97a` (2026-09-19, "enforce 10-minute cadence pacer entry with trend alignment and pullbacks") แก้ `backtest/strategies.py` 71 บรรทัด เพิ่ม pullback entry ให้ BTC/ETH → จำนวนไม้พุ่ง ~4 เท่า ตัวเลขในเอกสารจึงเป็นของโค้ดเวอร์ชันก่อนหน้า (ผมยืนยันได้แค่ว่าตัวเลขเก่า reproduce ไม่ได้ ไม่ได้ยืนยันว่า commit นั้นเป็นสาเหตุเดียว)

---

## 5) Config ที่ดีที่สุด 2–3 อันดับ และเหตุผล

### อันดับ 1 — G04: RR 2.5, SL 1.25×ATR, session เดิม, maxpos 3
- IS +0.098R → OOS **+0.171R** (OOS ดีกว่า IS = ไม่เสื่อม), PF 1.25, net OOS +5.08%, DD 6.61%
- **ทำไมดี:** เป็นการเปลี่ยนค่าเดียว (RR) ที่ monotonic ข้ามช่วง: RR 1.5 → 2.0 → 2.5 ให้ OOS exp +0.042 → +0.102 → +0.171 (แม้ IS จะไม่ monotonic ก็ตาม) และอธิบายได้เชิงกลไก: win rate ลดลง (OOS 43%→35%) แต่ payoff ที่เพิ่มขึ้นชดเชยได้มากกว่า ⇒ expectancy สูงขึ้น เพราะเมื่อ TP ไกลขึ้น ต้นทุน spread/slippage ต่อ R ก็เล็กลง
- **ความเสี่ยง:** RR สูง = win rate ต่ำลง (34%) → ต้องทนช่วงแพ้ติดกันยาวขึ้น; DD ไม่ลด (6.61% vs 4.91% baseline)

### อันดับ 2 — G10: RR 2.0, session ทั้งวัน (ไม่มีตัวกรอง), maxpos 3
- IS +0.068R → OOS **+0.147R**, PF 1.24, net OOS **+6.27%**, 81 ไม้ใน OOS (n ใหญ่สุดในกลุ่มที่ทำกำไร)
- **ทำไมดี:** "allday" ชนะ session เดิมใน**ทุกคู่ที่เทียบกันได้**: G03→G10 (2.85%→6.27% OOS), G11→G14 (3.28%→5.39%), G04→G13 (5.08%→8.44%) → ไม่ใช่ผลของ config เดียว แต่เป็นผลของ "การเอา filter ออก" ที่สอดคล้องกัน กลไก: filter ปัจจุบัน (00–14 UTC จาก timezone ที่เพี้ยน) ตัด NY afternoon ซึ่งเป็นช่วงที่ทองมีแนวโน้ม/สภาพคล่องดีที่สุด
- **ความเสี่ยง:** DD เพิ่มเป็น 6.38–10.82% (จาก 4.91%) เพราะเทรดช่วงที่ผันผวนกว่า

### อันดับ 3 (ทางเลือกเสี่ยงต่ำ) — G14: RR 2.0, session ทั้งวัน, maxpos 1
- IS +0.088R → OOS +0.131R, PF 1.21, net OOS +5.39%, **DD ต่ำสุดในกลุ่มที่กำไร (5.80%)**
- **ทำไมดี:** IS/OOS สมดุลที่สุด (ต่างกันแค่ 0.043R) และ DD ต่ำสุด — maxpos 1 ลด exposure พร้อมกันจาก 3 ไม้เหลือ 1
- **ข้อควรรู้:** net return ที่ต่ำกว่า G10 ส่วนหนึ่งมาจาก exposure ที่ลดลง ไม่ใช่ edge ที่แย่กว่า (expectancy ใกล้กัน: 0.131 vs 0.147)

---

## 6) คำเตือน overfitting — config ที่ IS ดีแต่ OOS แย่ (ชี้ให้เห็นชัด ๆ)

| Config | IS exp R | OOS exp R | อาการ |
|---|---|---|---|
| **G09_nyoverlap_rr2.0** | **+0.400R** (ดีสุดในตาราง, PF 1.73, DD 2.12%) | **+0.080R** (PF 1.12, n=19) | IS→OOS **−0.320R** — ตัวเลข IS สวยที่สุดในรายงาน แต่ OOS เกือบไม่มี edge และ n แค่ 19 ไม้ ⇒ ถ้าเลือกจาก IS จะเจ็บตัว |
| **ETH C05_nyoverlap** | −0.199R (ดีสุดของ ETH IS, −13.50%) | **−0.551R** (แย่สุดของ ETH OOS) | IS→OOS **−0.352R** — ทิศทางกลับกันสนิท |
| G06_sl1.5_rr2.0 | +0.039R (แย่สุดในกลุ่ม RR 2.0) | +0.211R (ดีสุด) | ทิศทาง**กลับกัน** (OOS ดีกว่า IS มาก) ⇒ parameter ไม่เสถียร เลือกตาม OOS อย่างเดียวก็เสี่ยง |
| G05_sl1.0_rr2.0 | +0.051R | +0.197R | เหมือนกัน — ผลของ SL multiplier แกว่งแรงทั้งสองทาง |

**บทเรียนที่ต้องถือ:** (1) อย่าเลือก config จาก IS (2) อย่าเลือกจาก OOS อย่างเดียวโดยไม่ดู IS (3) config ที่ "IS ดีมาก + n น้อย" (G09) ควรถือเป็นสมมติฐาน ไม่ใช่คำตอบ (4) ตัวเลขที่ดีที่สุดในตารางอาจเป็นแค่ 1 ใน 14 ที่ดูดีโดยบังเอิญ — ถ้าจะใช้จริงควร paper trade OOS ต่ออย่างน้อย 1–2 เดือน

---

## 7) ข้อเสนอ concretely (ระบุชื่อพารามิเตอร์จริง)

### 7.1 `config.py` (แก้ค่า)
1. **`trailing_be_enabled: bool = True` → `False`** (หรืออย่างน้อย `trailing_be_trigger_r: float = 0.6` → `1.5`+) — BE ที่ 0.6R/1.0R ทำ expectancy ตก 0.14–0.30R/ไม้ทั้งสองช่วง **ห้ามใช้ค่าปัจจุบันกับทอง M5**
2. **`max_open_positions: int = 3` → `1`** (ทดสอบแล้ว OOS: exp 0.111 vs 0.102, DD 5.29 vs 5.88 — ได้ DD ต่ำกว่าโดยไม่เสีย edge) ถ้าต้องการผลตอบแทนเท่าเดิมต้องเพิ่ม `risk_per_trade_pct` ชดเชย — **ยังไม่ได้ทดสอบ** อย่าเพิ่งทำ
3. **`daily_max_loss_pct: float = 0.05`** ให้ตรงกับ backtest ที่ใช้ `0.02` (ปัจจุบัน backtest เข้มกว่า 2.5 เท่า ทำให้ผล backtest กับ live เทียบกันไม่ได้) — ยังไม่ได้ sweep ค่านี้
4. **`target_rr_ratio: float = 2.0` → `2.5`, `min_rr_ratio: float = 1.3` → `2.0`** — แต่ค่าเหล่านี้**ยังไม่มีผล**จนกว่าจะแก้ `strategies.py` (§7.2)

### 7.2 `backtest/strategies.py` → `strategy_m5_scalper` (จุดที่ hardcode)
1. **ทอง RR:** `sl_dist = max(1.25 * atr, 1.0)` / `tp_dist = round(1.8 * atr, ...)`
   → เปลี่ยน TP เป็นคำนวณจาก `sl_dist` จริง: `tp_dist = round(sl_dist * 2.5, _price_precision_for(close_p))`
   (ปัจจุบัน RR เพี้ยนเมื่อ ATR ต่ำกว่า 0.8 เพราะ SL ถูก floor ที่ 1.0 แต่ TP ยัง = 1.8*ATR → RR ต่ำกว่า 1.44)
2. **ทอง session filter:** `if hour is not None and not (7 <= hour <= 21)` → **ลบทิ้ง** (ทดสอบแล้ว allday ชนะทั้ง IS/OOS) หรือถ้าต้องการคง filter ให้แปลงเป็น UTC ก่อนใช้:
   `utc_hour = (hour - 7) % 24` แล้วกรอง `12 <= utc_hour < 21` (NY session) — **ตัวนี้ยังไม่ได้ทดสอบ**
3. **BTC / ETH:** เปลี่ยน RR เป็น 2.0–2.5 แล้วยังขาดทุนทุกตัว ⇒ **ไม่แนะนำให้จูนต่อ** ควรปิด M5 ของ crypto (หรือย้ายไป M15 ที่มี edge) จนกว่าจะมี signal ที่ expectancy เป็นบวกจริง
4. **โครงสร้าง:** เพิ่มพารามิเตอร์เข้า `strategy_m5_scalper` แทนการ hardcode: `rr_multiple: float = 2.5`, `sl_atr_mult: float = 1.25`, `session_utc: Optional[Tuple[int,int]] = None`

### 7.3 `backtest/run_m5_backtest.py` (ทำให้ตรงกับของจริง)
1. `M5BacktestEngine` **ไม่มี trailing BE** ขณะที่ live เปิดใช้ → เพิ่ม `be_trigger_r: Optional[float]` (โค้ดอ้างอิงใน `backtest/engine.py` บรรทัด ~110–117 ที่ทำ BE ที่ 1.0R) มิฉะนั้น backtest จะประเมิน live สูงเกินจริงตลอดไป
2. `run_single_asset_m5_backtest()` ฮาร์ดโค้ด `risk_per_trade_pct=0.005`, `daily_target_pct=0.03`, `daily_max_loss_pct=0.02`, `max_open_positions=3`, `cooldown_bars=2` และ **ไม่ import ค่าเหล่านี้จาก `config`** → ควรอ่านจาก `config` หรือรับเป็นพารามิเตอร์
3. เพิ่ม `rr_multiple`, `sl_atr_mult`, `session_filter`, `be_trigger_r` เข้า signature ของ `run_single_asset_m5_backtest()` เพื่อให้ sweep ทำได้จาก CLI โดยไม่ต้อง subclass (ตอนนี้ต้อง subclass ใน `research/`)
4. Spread ถูกหักครั้งเดียวตอนปิด (`pnl = (exit-entry-spread)*...)` → ของจริงคือ spread ตอนเข้า + ตอนออก (หรือ commission) ⇒ ต้นทุนถูกไปประมาณครึ่งหนึ่ง ควรมี `commission_per_lot`

### 7.4 สิ่งที่ **ห้ามทำ** (สรุป)
- ❌ ห้ามเปิด `trailing_be` 0.6R กับ gold M5 (หลักฐานชัดทั้ง IS/OOS)
- ❌ ห้ามเทรด BTC/ETH ด้วย M5 scalper เวอร์ชันนี้ (backtest ติดลบทุก config)
- ❌ ห้ามเลือก config จาก OOS อย่างเดียว (ดู G09, G06, ETH C05)
- ❌ ห้ามอ้างตัวเลข +4.87% (BTC) / +1.63% (ETH) ในเอกสารอีกจนกว่าจะรันซ้ำได้
- ❌ ห้ามสรุปว่า config ไหน "ชนะ" จากรายงานนี้ในเชิงสถิติ — SE ≈ 0.1–0.2R และ n น้อย

---

## 8) คำสั่งที่ใช้รันทั้งหมด (reproducible)

ทำงานที่ `D:\trader\daytrad` ด้วย `.venv` (ไม่ใช้ container):

```powershell
cd D:\trader\daytrad
$py = ".\.venv\Scripts\python.exe"

# 0) baseline ตาม CLI เดิม (ยืนยันตัวเลขเอกสาร)
& $py main.py backtest --market=gold --timeframe=M5
& $py main.py backtest --market=btc --timeframe=M5
& $py main.py backtest --market=eth --timeframe=M5

# 1) XAUUSD sweep (12 config หลัก + fidelity check เทียบ run_single_asset_m5_backtest)
& $py research\strategy_sweep.py --symbol XAUUSD --configs full --verify

# 2) BTCUSD / ETHUSD sweep 6 config
& $py research\strategy_sweep.py --symbol BTCUSD --configs crypto
& $py research\strategy_sweep.py --symbol ETHUSD --configs crypto

# 3) gold combo config เพิ่มเติม (G13/G14)
& $py research\strategy_sweep.py --symbol XAUUSD --configs full --only G13_allday_rr2.5,G14_allday_rr2.0_maxpos1 --out research\sweep_xauusd_extra.json

# 4) render ตาราง markdown + pooled expectancy + reference numbers
& $py research\render_tables.py
& $py research\pooled_summary.py
```

- ผลดิบ: `research/sweep_xauusd.json`, `research/sweep_xauusd_extra.json`, `research/sweep_btcusd.json`, `research/sweep_ethusd.json`
- log: `research/log_xau.txt`, `research/log_btc.txt`, `research/log_eth.txt`, `research/log_xau_extra.txt`, `research/log_pooled.txt`
- เวลารัน: XAU ~55–62 วิ/config (14 config ≈ 13–14 นาที), BTC/ETH ~13–37 วิ/config
- หมายเหตุ: `research/strategy_sweep.py` เป็นไฟล์**ใหม่**ใน `research/` ไม่ได้แก้ไฟล์เดิมของ `daytrad` แม้แต่ไฟล์เดียว (ตรวจได้ด้วย `git status`)

---

## 9) สิ่งที่ยังไม่ได้ทดสอบ (บอกตรง ๆ ว่าไม่ได้)

- commission / slippage จริง, spread สองขา
- `daily_max_loss_pct` (0.02 vs 0.05) และ `daily_target_pct` (soft/hard target ใหม่ใน config)
- cooldown 1 vs 2 vs 3 แท่ง และ `risk_per_trade_pct` 0.5% vs 1%
- filter แบบ UTC จริง (12–21 UTC = NY session) — แนะนำเป็นงานถัดไป
- walk-forward หลาย fold / bootstrap CI (งานนี้ใช้ split เดียว 70/30 ตามที่โจทย์กำหนด)
- M15 engine (`backtest/engine.py`) และ ML filter (`--ml`) — ไม่ได้แตะ
