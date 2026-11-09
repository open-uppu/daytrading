# ปัจจัยภายนอก (External Factors) สำหรับ XAUUSD / BTCUSD / ETHUSD
### เช็กลิสต์ที่ agent ใช้ได้ทุก 3 ชั่วโมง — วัดได้จริง อ้างอิงตรวจสอบได้

| | |
|---|---|
| **จัดทำ** | 2026-11-09 (เวลาไทย) / ตรวจข้อมูลสด 2026-11-08 ~17:55–18:20 UTC |
| **ขอบเขต** | ปัจจัยมหภาค, ปัจจัยเชิงเวลา/session, เช็กลิสต์ 6 ข้อ, แหล่งข้อมูล, ข้อจำกัด |
| **หลักการ** | ปัจจัยภายนอกใช้ **veto / ลดขนาด / เลื่อนจังหวะ** เท่านั้น — ห้ามใช้เป็นเหตุผลเข้าเทรดเดี่ยว ๆ (ดูส่วนที่ 5) |
| **สถานะโค้ด** | ไม่มีการแก้โค้ดระบบในงานนี้ — อ่าน `core/news_calendar.py`, `core/sentiment.py`, `config.py`, `backtest/data_loader.py`, แคช `journal/*/ff_calendar_cache.json` |

**ระดับหลักฐานที่ใช้ในเอกสารนี้**

- **A** = มีงานวิจัย/ข้อมูลสถาบันรองรับชัด (ลิงก์ตรงในเอกสาร)
- **B** = กลไกชัดและมีหลักฐานบางส่วน แต่ขนาด/ความแรงของผลไม่คงที่ → ใช้เป็น context ไม่ใช่สัญญาณ
- **C** = "ความเชื่อ" ที่ยังไม่มีหลักฐานพอ → ดูส่วนที่ 5 ห้ามใช้เดี่ยว

---

## 0. ของฟรีที่มีอยู่แล้วในเครื่อง (ไม่ต้องพึ่ง API เสียเงิน)

| แหล่งในโค้ด | ให้ข้อมูลอะไร | ความถี่/แคช | ข้อจำกัดที่เจอจริง |
|---|---|---|---|
| `core/news_calendar.py` → `fetch_ff_calendar()` | ปฏิทินเศรษฐกิจจาก FF/FairEconomy (JSON รายสัปดาห์, ไม่ต้องมีคีย์) | แคช **3600 วิ** (`config.news_calendar_cache_ttl_sec`) | **เจอ HTTP 429** เมื่อเรียกถี่ → ฟังก์ชันคืน `None` |
| `core/news_calendar.py` → `get_news_window_status()` | ตัดสินใจ blackout/derisk ในกรอบ **±15 นาที** (`config.news_blackout_window_min`) | เรียกทุก loop (10 วิ) จากแคชข้างบน | `calendar=None` → **fail open** (เทรดปกติ); และ `derisk` ถูกคำนวณแต่ **ไม่มีผล** กับ base agent |
| `core/sentiment.py` → `fetch_fear_greed_index()` / `fetch_fear_greed_history()` | Crypto Fear & Greed (0–100) + ประวัติรายวัน (สำหรับ backtest) | แคช **900 วิ** (`config.sentiment_cache_ttl_sec`) | ไม่มีความหมายกับทอง (โค้ดเดิมก็ข้ามให้ทองอยู่แล้ว) |
| `core/sentiment.py` → `fetch_news_sentiment()` | นับคำ bullish/bearish ในพาดหัว Google News ล่าสุด ~20 ชิ้น | TTL 900 วิ | **ไม่มี historical archive** → backtest ย้อนหลังไม่ได้; รายงานตัวเลข "ตอนนี้" เท่านั้น |
| `backtest/data_loader.py` → `fetch_yahoo_candle_data()` | OHLC จาก Yahoo Chart API (ฟรี ไม่มีคีย์) — ต่อยอดเป็น DXY / ^TNX / TIP / ^IXIC ได้ทันที | ตาม timeframe | ถ้าดึงพลาดจะ **สร้างข้อมูลสังเคราะห์** แทน (ดูส่วนที่ 5.2 ข้อ 4) |

### 0.1 ค่าที่ตรวจสดจากเครื่องนี้ (snapshot — ค่าเปลี่ยนทุกครั้งที่รัน)

| ตัวชี้วัด | ค่า | วันที่ของข้อมูล | ที่มา |
|---|---:|---|---|
| US 10Y **real** yield (TIPS, constant maturity) | **2.63%** (5Y 2.35%, 30Y 3.07%) | 2026-11-06 | [US Treasury real yield curve CSV](https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/2026/all?type=daily_treasury_real_yield_curve&field_tdr_date_value=2026&page&_format=csv) |
| US 10Y nominal (^TNX) | 4.859% → breakeven ≈ 2.23 จุด | 2026-11-06 | [Yahoo ^TNX](https://query1.finance.yahoo.com/v8/finance/chart/%5ETNX?interval=1d&range=5d) |
| DXY | 102.30 | 2026-11-06 (close) | [Yahoo DX-Y.NYB](https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB?interval=1d&range=10d) |
| Nasdaq Composite | 24,579.43 | 2026-11-06 | [Yahoo ^IXIC](https://query1.finance.yahoo.com/v8/finance/chart/%5EIXIC?interval=1d&range=5d) |
| BTC mark / funding / OI | 75,752.87 / **+0.00350% ต่อ 8 ชม.** / 96,329.842 BTC | 2026-11-08 17:56 UTC | [Binance premiumIndex](https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT), [openInterest](https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT) |
| ETH mark / funding / OI | 2,230.00 / **+0.00546% ต่อ 8 ชม.** / 2,379,476.777 ETH | 2026-11-08 17:56 UTC | [Binance ETH premiumIndex](https://fapi.binance.com/fapi/v1/premiumIndex?symbol=ETHUSDT) |
| Stablecoin total (peggedUSD) | **$293.66B** | 2026-11-08 00:00 UTC | [DefiLlama stablecoincharts](https://stablecoins.llama.fi/stablecoincharts/all) |
| Crypto Fear & Greed | **28 = Fear** | 2026-11-08 | [alternative.me F&G](https://api.alternative.me/fng/?limit=1&format=json) |
| Gold COT (COMEX, futures only) | OI 399,169 / non-commercial long 220,530 / short 40,982 → **net +179,548** | 2026-11-03 (เผยแพร่ 6 พ.ย.) | [CFTC COT public reporting](https://publicreporting.cftc.gov/resource/6dca-aqww.json) |
| Gold ETF flows | ต.ค. 2026 **+$2.7bn**, holdings **4,275t** (สถิติสูงสุด), AUM $542bn; YTD +$41bn / +246t | 2026-10-31 | [WGC Gold ETF Flows ต.ค. 2026](https://www.gold.org/goldhub/research/gold-etfs-holdings-and-flows/2026/11) |
| Central bank net purchases | ปี 2025 **863.3t** (2024: 1,092.4t); Q4 230t; NBP ซื้อมากสุด 102t | FY2025 | [WGC Gold Demand Trends FY2025 — Central Banks](https://www.gold.org/goldhub/research/gold-demand-trends/gold-demand-trends-full-year-2025/central-banks) |
| ปฏิทิน USD | ดึงได้ 101 events / 37 USD (ครั้งที่สำเร็จ) → **หลังจากนั้นโดน 429** | 2026-11-08 | [FF weekly JSON](https://nfs.faireconomy.media/ff_calendar_thisweek.json) |

> **ข้อสังเกตที่สำคัญที่สุดจากส่วนนี้:** แคช `journal/xauusd|btcusd|ethusd/ff_calendar_cache.json` ทั้งสามไฟล์ถูกเขียนเมื่อ **2026-11-08 20:23 (+07)** ด้วยค่า `{"value": null}` → ในชั่วโมงนั้น news gate **fail open** (ไม่มี blackout เลย) ทั้งที่ตลาดมีข่าว CPI ในสัปดาห์นั้น

---

## ส่วนที่ 1: ปัจจัยมหภาค

### 1.1 ทองคำ (XAUUSD)

| # | ปัจจัย | วัดจากอะไร (แหล่งฟรี) | ทิศทางที่คาด | ใช้ตอนไหน | ข้อจำกัด / ทำให้เข้าใจผิดได้อย่างไร | ระดับ |
|---|---|---|---|---|---|---|
| G1 | **อัตราดอกเบี้ยจริง 10 ปี (TIPS)** — ต้นทุนค่าเสียโอกาสของการถือทอง | US Treasury real yield CSV รายวัน หรือ [FRED DFII10 (CSV ไม่ต้องคีย์)](https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10) หรือราคา TIP (Yahoo) | จริงขึ้น → กดทอง; จริงลง → หนุนทอง (ทิศทางผกผัน) | ตั้ง **bias รายวัน–รายสัปดาห์** ก่อนเลือกฝั่ง | WGC เตือนชัดว่า **"higher real rates ไม่ได้แย่กับทองแบบไม่มีเงื่อนไข"** และอิทธิพลของ real rate ต่อทอง **ลดลงหลายทศวรรษ** เพราะดีมานด์ย้ายไปตะวันออก → [WGC reality check](https://www.gold.org/goldhub/research/gold-and-us-interest-rates-reality-check), [WGC press release](https://www.gold.org/news-and-events/press-releases/new-report-urges-investors-not-overestimate-effect-us-interest-rate) | B |
| G2 | **ดัชนีดอลลาร์ (DXY)** | [Yahoo DX-Y.NYB](https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB?interval=1d&range=10d) (ฟรี) | DXY ขึ้น → กดทอง (ทอง priced in USD) | เป็น **ตัวกรองทิศทาง** ไม่ใช่ trigger | มีช่วงที่ทองขึ้นพร้อม DXY ได้ (ดีมานด์ธนาคารกลาง/ภูมิรัฐศาสตร์ override) → อย่าใช้เป็นกฎแข็ง; ความสัมพันธ์นี้ไม่คงที่ | B |
| G3 | **ความเสี่ยงภูมิรัฐศาสตร์ (GPR)** | [GPR Index ของ Caldara–Iacoviello](https://www.matteoiacoviello.com/gpr.htm) ดาวน์โหลดรายวัน (`.xls`, ~3.2 MB, ฟรี) | GPR spike → ทองขึ้น (safe haven) | ใช้เป็น **ตัวเพิ่มความระวัง** ไม่ใช่สัญญาณซื้อ | ราคามัก **วิ่งไปก่อน** ข่าวดัง → ซื้อตามข่าว = ซื้อที่ยอด; spike แล้วมัก mean-revert | B |
| G4 | **ธนาคารกลางซื้อทอง** | WGC Gold Demand Trends รายไตรมาส + IMF IFS รายเดือน | ซื้อต่อเนื่อง → หนุนโครงสร้าง (structural bid) | ปรับ **bias ระดับเดือน/ไตรมาส** | ข้อมูลมาช้า 1–3 เดือน; WGC ระบุ **57% ของยอดปี 2025 เป็น unreported buying** → มองไม่เห็นของจริงทั้งหมด ([WGC FY2025](https://www.gold.org/goldhub/research/gold-demand-trends/gold-demand-trends-full-year-2025/central-banks)) | A- |
| G5 | **Gold ETF flows / holdings** | [WGC Gold ETF Flows](https://www.gold.org/goldhub/data/gold-etfs-holdings-and-flows) รายเดือน/รายสัปดาห์ (ฟรี) | Flow เข้า → หนุน; flow ออก → กด | ใช้ยืนยัน **ทิศทางระดับสัปดาห์** | ต.ค. 2026: holdings +19t **แต่ AUM -6%** เพราะราคาทองลง → อ่านเฉพาะ "AUM" จะสรุปผิด; ETF ยังถูกขายเพื่อ **หา cash** ตอนตลาดเครียด (US funds ไหลออก -$512mn) ไม่ใช่แค่ความเห็นเชิงทิศทาง | A- |
| G6 | **Positioning COMEX (COT)** | [CFTC COT dataset 6dca-aqww](https://publicreporting.cftc.gov/resource/6dca-aqww.json) (ฟรี, JSON) + [WGC open interest](https://www.gold.org/goldhub/data/gold-open-interest) | Net long สูงมาก = **crowded** → เสี่ยง long squeeze | ใช้เป็น **ตัววัดความแออัด** ก่อนเตรียมรับความผันผวน | ข้อมูล ณ วันอังคาร เผยแพร่วันศุกร์ → **lag 3 วัน** ใช้จับจังหวะไม่ได้; ณ 2026-11-03 net non-comm long 179.5k จาก OI 399k = สูง | A- |
| G7 | **สภาพคล่องทองรายวัน** | WGC trading volumes (LBMA/COMEX/ETF, ฟรี) | liquidity สูง → spread แคบ, breakout น่าเชื่อถือกว่า | เช็คก่อนวัดว่า "spread กว้างผิดปกติ" หรือเป็นเรื่องปกติของวันนั้น | Volumes เปลี่ยนตามฤดูกาล/อีเวนต์ (ต.ค. 2026 ลด 13% เหลือ $365bn/วัน) → เกณฑ์ spread ต้องเทียบ baseline ของช่วงเดียวกัน | B |

### 1.2 BTC / ETH

| # | ปัจจัย | วัดจากอะไร (แหล่งฟรี) | ทิศทางที่คาด | ใช้ตอนไหน | ข้อจำกัด / ทำให้เข้าใจผิดได้อย่างไร | ระดับ |
|---|---|---|---|---|---|---|
| C1 | **Funding rate ของ perpetual futures** | [Binance premiumIndex](https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT) + [fundingRate history](https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=2) (ฟรี ไม่ต้องคีย์) | Funding บวกสูง = ฝั่ง long แออัด/จ่ายแพง → เสี่ยง long squeeze; ลบสูง = ฝั่ง short แออัด → เสี่ยง short squeeze | **ทุก 3 ชม.** (funding ตั้งทุก 8 ชม.: 00/08/16 UTC) | ค่าปกติอยู่ราว baseline 0.01%/8 ชม. → ต้องเทียบ baseline ไม่ใช่เทียบศูนย์; funding บอก **ความแออัด** ไม่บอกทิศทางราคา | B |
| C2 | **Open interest** | [Binance openInterest](https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT) | OI พุ่ง + ราคาไม่ไป = leverage สะสม → สั่นแรงเมื่อถูกบังคับปิด | ใช้คู่กับ C1 ก่อนเข้าช่วง breakout | OI เดี่ยว ๆ ไม่บอกฝั่ง; ต้องดูคู่ funding + ราคา | B |
| C3 | **Stablecoin supply (สภาพคล่อง crypto)** | [DefiLlama stablecoincharts](https://stablecoins.llama.fi/stablecoincharts/all) (ฟรี) | อุปทาน stablecoin เพิ่ม = มี "เงินสด" ในระบบมากขึ้น → หนุนความต้องการสินทรัพย์เสี่ยง | ใช้เป็น **bias ระดับสัปดาห์/เดือน** | เป็นข้อมูลช้าและเป็น proxy; งานวิจัยสายตรง "stablecoin ↑ → BTC ↑" ยังบาง → ห้ามใช้เดี่ยว (จัดเป็น B/C) | C+ |
| C4 | **Correlation กับ Nasdaq** | [Yahoo ^IXIC](https://query1.finance.yahoo.com/v8/finance/chart/%5EIXIC?interval=1d&range=5d) คำนวณ rolling correlation 30/90 วันเอง | Nasdaq ลงแรง → BTC มักลงตาม (risk-off beta) | ใช้ **หรี่ size** วันที่มี Nasdaq sell-off | Correlation **ไม่คงที่**: งานวิจัยพบ rolling correlation กับ Nasdaq 100 พุ่งถึง **0.87 ในปี 2024** และแปรผันตาม regime → [arXiv:2501.09911](https://arxiv.org/abs/2501.09911v1) | B+ |
| C5 | **Halving cycle** | ตาราง issuance ของ Bitcoin (ทุก 210,000 บล็อก) | อุปทานใหม่ลดครึ่ง → หนุนราคาระยะยาว *ตามทฤษฎี* | ใช้เป็น **context เชิงโครงสร้าง** เท่านั้น | หลักฐานว่า "halving → bull run" แบบมี timing ไม่พอ; งานวิจัยสายนี้ยังสรุปไม่ได้ว่าผลคงที่ → [Stylized facts about bitcoin halving](https://www.sciencedirect.com/science/article/abs/pii/S1544612324012273), [The effect of the cryptocurrency halving event](https://www.sciencedirect.com/science/article/abs/pii/S0927538X25002501) | C |
| C6 | **Fear & Greed (crypto)** | [alternative.me F&G](https://api.alternative.me/fng/?limit=1&format=json) | สุดโต่ง (≤25 / ≥75) → contrarian *เล็กน้อย* | ใช้เป็น **ตัวชะลอ** ตอน everyone-long | ไม่มีหลักฐานว่าจับจังหวะกลับตัวได้; โค้ดเดิมใช้เกณฑ์ 25/75 ใน backtest แบบ experimental default **ปิด** | C |
| C7 | **ETF flows (spot BTC/ETH)** | Yahoo (IBIT/ETHA volume/price) หรือหน้า flows ฟรีของผู้ให้ข้อมูล | Flow เข้า → หนุน | ยืนยันทิศทางระดับสัปดาห์ | Flow ตามราคา (reflexive) ไม่ใช่ leading; ต้องแยก "flow ตามราคา" กับ "flow นำราคา" ให้ได้ก่อนใช้ | C+ |
| E1 | **ETH funding + OI** | [Binance ETH premiumIndex](https://fapi.binance.com/fapi/v1/premiumIndex?symbol=ETHUSDT) | เหมือน C1 แต่ ETH ผันผวนกว่า → extreme เกิดถี่กว่า | ทุก 3 ชม. คู่กับ BTC | ETH มักถูกเหวี่ยงจาก BTC ก่อน → funding ETH ที่สุดโต่งอาจเป็นผลจาก BTC ไม่ใช่ปัจจัยเฉพาะ ETH | B |
| E2 | **ETH/BTC ratio** | Yahoo `ETH-BTC` (รายวัน) | ratio ขึ้น = risk appetite ใน crypto ดี | ใช้เลือกว่าจะเล่น ETH หรือ BTC | เป็น **ผลลัพธ์** ของกระแสเงินมากกว่าสาเหตุ; ผันผวนสูง | B- |

### 1.3 ปัจจัยที่ใช้ร่วมกัน (ทอง + crypto)

| # | ปัจจัย | วัดจากอะไร (แหล่งฟรี) | ทิศทางที่คาด | ใช้ตอนไหน | ข้อจำกัด | ระดับ |
|---|---|---|---|---|---|---|
| S1 | **ปฏิทิน USD High-impact** | [FF calendar JSON](https://nfs.faireconomy.media/ff_calendar_thisweek.json) + [BLS CPI schedule](https://www.bls.gov/schedule/news_release/cpi.htm) + [BLS Employment Situation](https://www.bls.gov/schedule/news_release/empsit.htm) + [FOMC calendar](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm) | ก่อน/หลังข่าว: spread กว้างขึ้น ผันผวนพุ่ง ทิศทางสุ่ม | **ทุก 3 ชม.** เป็นด่านแรก (ข้อ 1 ในเช็กลิสต์) | feed โดน **429** ได้ (เจอจริง) แล้วระบบ fail open; ชื่อ event ต้อง match keyword ถึงจะ blackout | A |
| S2 | **ความคาดหวังดอกเบี้ย (FedWatch)** | [CME FedWatch](https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html) (ฟรี) | ตลาด price-in ขึ้น/ลงของ Fed → ขับ real yield → ทอง | ก่อน FOMC/CPI 1–2 วัน | หน้าเว็บเป็น JS; ต้องอ่านด้วยคน/เบราว์เซอร์ ไม่ใช่ API ฟรี | B |

**ข้อเท็จจริงเรื่อง "spread ก่อน/หลังข่าว" (S1):** งานวิจัยตลาด Treasury ของ NY Fed พบรูปแบบ intraday ชัดเจนของ **volatility, volume และ bid-ask spread** รอบเวลาประกาศข่าวมหภาค → [Fleming & Remolona, NY Fed Staff Report 9633](https://www.newyorkfed.org/research/staff_reports/research_papers/9633.html) และมีงานที่รายงานว่า **ผู้ให้สภาพคล่องถอนตัวก่อนประกาศข่าวตามกำหนด** → [Liquidity withdrawal before scheduled macroeconomic announcements](https://www.sciencedirect.com/science/article/pii/S0165176526004520) — ใช้เป็นเหตุผลว่า **ห้ามตั้ง entry ใหม่ในกรอบ ±15 นาที** รอบข่าวระดับสูง (กลไกย้ายมาที่ทองได้ แต่ต้องยืนยันด้วย tick/spread ของโบรกเกอร์ตัวเอง)

---

## ส่วนที่ 2: ปัจจัยเชิงเวลา / Session (ชั่วโมง UTC)

**หมายเหตุ DST:** เวลาข่าวสหรัฐฯ อ้าง 8:30 ET และ 14:00 ET → ช่วง **มี.ค.–พ.ย. (EDT, UTC-4)** = **12:30 / 18:00 UTC**; ช่วง **พ.ย.–มี.ค. (EST, UTC-5)** = **13:30 / 19:00 UTC** (ต้น พ.ย. 2026 อยู่โหมด EST → 13:30 UTC) — ตรวจทุกครั้งก่อนใช้ อย่าจำค่าตายตัว

| ช่วง UTC | เกิดอะไร | คาดกับ XAU | คาดกับ BTC / ETH | ใช้ทำอะไร | หลักฐาน |
|---|---|---|---|---|---|
| 00:00–06:00 | Tokyo/Sydney, โกลบอล liquidity บาง | แกว่งกรอบ แนวโน้มอ่อน; breakout หลอกง่าย | ผันผวนปานกลาง (ตรงกับ US evening) — depth บาง | ลด size / เล่น mean-reversion มากกว่า breakout | B |
| 06:00–07:00 | ก่อน London open | liquidity เริ่มหนา, spread แคบลง | ไม่ต่างชัด | เตรียมแผน ไม่เพิ่งเข้า | B |
| **07:00–12:00** | **London session** — ช่วงที่ liquidity ดีที่สุดของทอง | แนวโน้มเริ่มก่อตัว; โค้ดเดิมของระบบจำกัดทองใน 07:00–21:00 UTC → `backtest/strategies.py:387,488` | ปกติ | **หน้าต่างหลักของทอง** (momentum) | [BIS Triennial 2025: FX โลกราว $9.6 ล้านล้าน/วัน](https://www.bis.org/media-releases/20250930-global-fx-trading-hits-96-trillion-day-april-2025-and-otc-interest-rate-derivatives-surge-79) + โค้ดเดิม |
| 12:30–13:30 | **ก่อนข้อมูลสหรัฐฯ 8:30 ET** (12:30 EDT / 13:30 EST) | spread กว้างขึ้น, whipsaw, stop hunt | มักเงียบก่อนแล้วกระโดดตาม | **ห้ามเข้าใหม่**, จัดการ position เดิม | [NY Fed 9633](https://www.newyorkfed.org/research/staff_reports/research_papers/9633.html), [liquidity withdrawal](https://www.sciencedirect.com/science/article/pii/S0165176526004520) |
| **13:30–16:00** | **London–NY overlap** — deepest liquidity | range/เทรนด์กว้างที่สุดของวัน | depth ดีขึ้นตาม US session | **หน้าต่างที่ดีที่สุดในการเทรดตามเทรนด์** | B (BIS + กลไกตลาด) |
| 16:00–17:00 | London fix / European close | มี rebalancing flow, spike สั้น | ปกติ | ระวัง false breakout | B |
| 18:00–19:00 | **FOMC วันประชุม (14:00 ET)** | ผันผวนพุ่ง + spread ถ่างหนักที่วินาทีประกาศ | ผันผวนตาม risk sentiment ทันที | **ห้ามเทรดรอบ announcement**; รอ 15–30 นาที | [FOMC calendar](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm) |
| 20:00–21:00 | NY close, liquidity ลดลง | แนวโน้มของวันจบ; ระวังกลับตัว | ยังเทรดได้แต่ depth ลด | ปิด/ลด position ก่อน liquidity หาย | โค้ดเดิม (ตัด 21:00 UTC) |
| 21:00–24:00 | Late NY / After-hours | ผันผวนต่ำ, drift | ปกติ (24/7) | ไม่เปิดไม้ใหม่ของทอง | B |
| **วันศุกร์ หลัง ~20:00** | liquidity หายเร็ว, ปิดสัปดาห์ | **ความเสี่ยง gap ข้าม weekend** (ตลาดทองปิด) | ยังเทรด 24/7 แต่ spread/wick กว้างขึ้น | **ลด/ปิด position ก่อน weekend** | [รายงานตลาด: liquidity กระจุกในชั่วโมงสหรัฐฯ และ spread กว้างขึ้นช่วง weekend](https://bingx.com/ar/news/post/spot-bitcoin-etfs-concentrate-liquidity-in-u-s-hours-widening-weekend-spreads) (หลักฐานระดับข่าว — ต้องยืนยันด้วย spread ของโบรกเกอร์เอง) |
| เสาร์–อาทิตย์ | ทองปิด; crypto เปิด | — | ผันผวนต่ำแต่ wick ยาว, แท่งเทียม | **ห้ามสรุปแนวโน้มจากแท่ง weekend** | C |

**กติกาที่แนะนำสำหรับ session:** ทอง → เน้น 07:00–16:00 UTC และหยุด 12:30–13:30 รอบข่าว; crypto → ใช้ 13:30–20:00 UTC เป็นหน้าต่างหลัก แต่ **ต้องวัด spread ของตัวเอง** ไม่ใช่เชื่อตารางนี้

---

## ส่วนที่ 3: เช็กลิสต์ 6 ข้อ ใช้ได้ทุก 3 ชั่วโมง

> ตอบ ใช่/ไม่ใช่ ให้ครบ 6 ข้อก่อนเปิดไม้ใหม่ ถ้าตอบ "ใช่" ข้อ 1 → **ห้ามเปิดไม้ใหม่ทั้งหมด** (ทุกสินทรัพย์)
>
> **ลำดับรันทุก 3 ชั่วโมง (ใช้เวลา ~2 นาที):** ① ปฏิทิน/ข่าว → ② session + ระยะห่างข่าว → ③ spread ของตัวเอง → ④ funding/OI (crypto) หรือ real yield/DXY (ทอง) → ⑤ GPR/headline → ⑥ ตัดสิน veto/ลด size/เลื่อน
>
> **ความสดของข้อมูล:** ปฏิทิน = แคช 1 ชม. (ต้องรู้ว่าค่ามาจากตอนไหน) · funding/OI = 8 ชม./realtime · real yield/DXY/^IXIC = รายวัน (ใช้ค่าล่าสุด) · COT = รายสัปดาห์ (lag 3 วัน) · ETF/WGC = รายเดือน · GPR = รายวัน

**① มีข่าว USD impact สูง ในกรอบ ±15 นาทีนี้หรือไม่?**
- วัดจาก: `journal/<asset>/ff_calendar_cache.json` (TTL 1 ชม.) / ถ้า `value = null` แปลว่า feed ล้ม → **ถือว่ามีความเสี่ยง ไม่ใช่ "ปลอดข่าว"**
- ใช่ → NFP/FOMC/CPI/Interest rate = **blackout** (ไม่เปิดไม้ใหม่); High-impact อื่น = **derisk** (ลด size ครึ่ง)
- ข้อควรระวัง: ถ้า title ของ FOMC ในสัปดาห์นั้นเขียนว่า "Federal Funds Rate" เฉย ๆ จะ **ไม่ match** keyword `interest rate` → ต้องอ่าน title เองด้วย

**② ตอนนี้อยู่ในหน้าต่าง liquidity หลักหรือไม่ และห่างจาก 8:30 ET (12:30/13:30 UTC) แค่ไหน?**
- ใช่ (07:00–16:00 UTC และห่างข่าว > 30 นาที) → อนุญาตให้เล่นตามเทรนด์
- ไม่ใช่ → ลด size หรือเลื่อนไปรอบถัดไป

**③ Funding rate BTC/ETH สุดโต่งผิดปกติหรือไม่ (|rate| ≥ 0.03% ต่อ 8 ชม.) หรือ OI พุ่งแต่ราคาไม่ไป?**
- วัดจาก: Binance `premiumIndex` + `openInterest` (ฟรี) — เทียบกับ baseline 0.01%/8 ชม.
- ใช่ → **ห้ามไล่ราคาตามฝั่งที่แออัด**; ลด size; ระวัง liquidation cascade

**④ Real yield 10Y + DXY ใน 3 วันที่ผ่านมา เคลื่อนสวนทางกับฝั่งที่กำลังจะเทรดหรือไม่?**
- วัดจาก: Treasury real yield CSV (รายวัน) + Yahoo DX-Y.NYB
- ใช่ (เช่น จะ buy ทอง แต่ real yield กำลังขึ้นแรง + DXY ขึ้น) → ลด size หรือรอ confirmation จาก price action

**⑤ Spread ปัจจุบันกว้างกว่าค่าเฉลี่ย 20 แท่งเกิน ~1.5 เท่าหรือไม่?**
- วัดจาก: tick/spread จาก MT5 bridge ของตัวเอง (ไม่ต้องพึ่ง API ภายนอก)
- ใช่ → เลื่อน entry (slippage กิน edge; มักเป็นสัญญาณว่ากำลังจะมี/news หรือ liquidity หาย)

**⑥ มี headline ภูมิรัฐศาสตร์/GPR ใหม่ใน 24 ชม. และราคาวิ่งไปแล้วเกิน ~1 ATR หรือไม่?**
- วัดจาก: GPR index (รายวัน) + พาดหัวข่าว (Google News RSS ผ่าน `fetch_news_sentiment`)
- ใช่ → **ไม่ไล่ราคา** รอ retest; ข่าวเก่าที่ตลาดย่อยแล้วไม่ใช่เหตุผลเข้าเทรด

**ถ้าข้อมูลภายนอกหาย (None/429):** ให้ปฏิบัติแบบ **fail-safe** — ลด size ลงครึ่งหนึ่งหรือไม่เทรดในรอบนั้น (ต่างจากโค้ดปัจจุบันที่ fail open) เพราะการไม่รู้ว่ามีข่าว ≠ ไม่มีข่าว

---

## ส่วนที่ 4: แหล่งข้อมูลพร้อมลิงก์

### 4.1 แหล่งที่ทดสอบจากเครื่องนี้แล้ว (2026-11-08)

| แหล่ง | ลิงก์ | ให้อะไร | ฟรี/คีย์ | ความถี่ | ผลทดสอบ |
|---|---|---|---|---|---|
| FF/FairEconomy calendar | [ff_calendar_thisweek.json](https://nfs.faireconomy.media/ff_calendar_thisweek.json) | ปฏิทิน USD/EUR impact | ฟรี ไม่มีคีย์ | รายสัปดาห์ | ✅ 200 (101 events) แล้ว **429 หลังเรียกถี่** |
| alternative.me F&G | [api.alternative.me/fng](https://api.alternative.me/fng/?limit=1&format=json) | Crypto sentiment 0–100 | ฟรี | รายวัน | ✅ 200 (28 = Fear) |
| Google News RSS | [RSS search](https://news.google.com/rss/search?q=gold+price+when%3A2d&hl=en-US&gl=US&ceid=US:en) | พาดหัวข่าว (tone ปัจจุบัน) | ฟรี | realtime | ✅ 200 ผ่าน httpx / ⚠️ 503 เมื่อใช้ UA อื่น |
| US Treasury real yield | [daily_treasury_real_yield_curve CSV](https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/2026/all?type=daily_treasury_real_yield_curve&field_tdr_date_value=2026&page&_format=csv) | 5Y/10Y/30Y real yield | ฟรี | รายวัน (lag ~1 วัน) | ✅ 200 (10Y 2.63%) |
| FRED (ทางเลือก real yield) | [fredgraph.csv?id=DFII10](https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10) | 10Y real yield | ฟรี ไม่มีคีย์ (CSV) | รายวัน | ✅ 200 (99 KB) |
| Yahoo Finance chart | [DX-Y.NYB](https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB?interval=1d&range=10d) | DXY, ^TNX, TIP, ^IXIC, GLD, BTC-USD | ฟรี ไม่มีคีย์ | 1d/1h/5m | ✅ 200 ทุก symbol (บางแท่ง close = null ต้องกรอง) |
| Binance USDⓈ-M futures | [premiumIndex](https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT) / [fundingRate](https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=2) / [openInterest](https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT) | funding, mark price, OI | ฟรี ไม่มีคีย์ | realtime / 8 ชม. | ✅ 200 |
| DefiLlama stablecoins | [stablecoincharts/all](https://stablecoins.llama.fi/stablecoincharts/all) | อุปทาน stablecoin | ฟรี | รายวัน | ✅ 200 ($293.66B) |
| CFTC COT | [Socrata 6dca-aqww](https://publicreporting.cftc.gov/resource/6dca-aqww.json) | Positioning ทอง/VIX ฯลฯ | ฟรี | รายสัปดาห์ (อังคาร→ศุกร์) | ✅ 200 |
| GPR Index | [matteoiacoviello.com/gpr.htm](https://www.matteoiacoviello.com/gpr.htm) | Geopolitical Risk index | ฟรี | รายวัน/รายเดือน | ✅ ดาวน์โหลด `.xls` ได้ (3.2 MB) — อ่านต้องมี `xlrd` |
| WGC Gold ETF Flows | [gold.org/goldhub/data/gold-etfs-holdings-and-flows](https://www.gold.org/goldhub/data/gold-etfs-holdings-and-flows) | Holdings + flows | ฟรี (บางไฟล์ต้องสมัครฟรี) | รายเดือน/รายสัปดาห์ | ✅ 200 |
| CME FedWatch | [cmegroup.com/.../cme-fedwatch-tool.html](https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html) | ความน่าจะเป็นของ Fed | ฟรี | realtime | ✅ 200 (เป็น JS ต้องอ่านด้วยเบราว์เซอร์) |

**แหล่งที่ไม่ผ่านจากเครื่องนี้ (อย่าพึ่งพา):**
- Bybit / OKX public API → DNS resolve ไม่ได้ (`api.bybit.com`, `www.okx.com`)
- Binance docs pages → HTTP 202 + body ว่าง (bot protection)
- ScienceDirect บทความเต็ม → 403 (อ่านได้แค่ title/abstract จาก search)

### 4.2 งานวิจัย/เอกสารอ้างอิง

| หัวข้อ | แหล่ง | สาระสำคัญที่ใช้ |
|---|---|---|
| ทองกับ real yield | [WGC — Gold and US interest rates: a reality check](https://www.gold.org/goldhub/research/gold-and-us-interest-rates-reality-check) | real yield สูงไม่ใช่ลบกับทองแบบไม่มีเงื่อนไข; อิทธิพลลดลงตามกาลเวลา |
| ทองกับ real yield (สรุปข่าว) | [WGC press release](https://www.gold.org/news-and-events/press-releases/new-report-urges-investors-not-overestimate-effect-us-interest-rate) | เตือนอย่าประเมินผลของดอกเบี้ยสูงเกินจริง |
| ธนาคารกลางซื้อทอง | [WGC Gold Demand Trends FY2025 — Central Banks](https://www.gold.org/goldhub/research/gold-demand-trends/gold-demand-trends-full-year-2025/central-banks) | 863.3t ปี 2025; 57% เป็น unreported buying |
| Gold ETF flows | [WGC Gold ETF Flows ต.ค. 2026](https://www.gold.org/goldhub/research/gold-etfs-holdings-and-flows/2026/11) | +$2.7bn, holdings 4,275t; ETF ขายเพื่อ liquidity ได้ |
| Spread รอบข่าว (ตลาด Treasury) | [Fleming & Remolona, NY Fed Staff Report 9633](https://www.newyorkfed.org/research/staff_reports/research_papers/9633.html) | volatility/volume/spread มีรูปแบบชัดรอบประกาศข่าว |
| สภาพคล่องหดก่อนข่าว | [Liquidity withdrawal before scheduled macroeconomic announcements](https://www.sciencedirect.com/science/article/pii/S0165176526004520) | ผู้ให้สภาพคล่องถอนตัวก่อนประกาศ |
| Gold intraday jumps | [What triggers intraday price jumps and co-jumps in gold?](https://www.sciencedirect.com/science/article/abs/pii/S1057521925004673) | งานวิจัยเชิงประจักษ์เรื่องการกระโดดของราคาทองระหว่างวัน (อ่าน abstract ก่อนอ้างอิงเชิงตัวเลข) |
| BTC–Nasdaq correlation | [arXiv:2501.09911 — Institutional Adoption and Correlation Dynamics](https://arxiv.org/abs/2501.09911v1) | rolling correlation กับ Nasdaq 100 พุ่งถึง 0.87 ในปี 2024, แปรผันตาม regime |
| Halving | [Some stylized facts about bitcoin halving](https://www.sciencedirect.com/science/article/abs/pii/S1544612324012273) / [The effect of the cryptocurrency halving event](https://www.sciencedirect.com/science/article/abs/pii/S0927538X25002501) | หลักฐานเชิงวิชาการยังไม่สรุปผล/ทิศทางที่แน่นอน |
| FX liquidity ระดับโลก | [BIS Triennial Survey 2025 (media release)](https://www.bis.org/media-releases/20250930-global-fx-trading-hits-96-trillion-day-april-2025-and-otc-interest-rate-derivatives-surge-79) | FX turnover $9.6 ล้านล้าน/วัน (เม.ย. 2025) |
| ตารางข่าวทางการ | [BLS CPI](https://www.bls.gov/schedule/news_release/cpi.htm) / [BLS Employment Situation](https://www.bls.gov/schedule/news_release/empsit.htm) / [FOMC calendar](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm) | เวลาปล่อยข่าวจริง (8:30 ET / 14:00 ET) |

---

## ส่วนที่ 5: ข้อจำกัด — อะไรคือ "ความเชื่อที่ยังไม่มีหลักฐานพอ"

### 5.1 ความเชื่อที่ห้ามใช้เป็นเหตุผลเข้าเทรดเดี่ยว ๆ

| ความเชื่อ | ทำไมยังไม่พอ | ใช้อะไรแทน |
|---|---|---|
| "วันศุกร์ตลาดแย่/กลับตัวเสมอ" | ไม่มีงานวิจัยรองรับเป็นกฎ; ที่จริงคือ **liquidity ลดลง** ก่อน weekend → ผันผวน/ gap ไม่ใช่ทิศทาง | ใช้ข้อเท็จจริงเรื่อง liquidity + ลด size ก่อนปิดสัปดาห์ |
| "Halving แล้ว BTC ต้อง bull" | งานวิชาการยังไม่สรุปผลที่คงที่ (C5) | ใช้เป็น context โครงสร้าง ไม่ใช่ timing |
| "Fear & Greed สุดโต่ง = จุดกลับตัว" | เป็น contrarian folklore; เกณฑ์ 25/75 ในโค้ดเป็น experimental ที่ **default ปิด** | ใช้เป็นตัวชะลอ ไม่ใช่สัญญาณกลับตัว |
| "Stablecoin เพิ่ม → BTC ขึ้นพรุ่งนี้" | เป็น proxy ที่ช้าและ causality ไม่ชัด | ใช้เป็น bias ระดับสัปดาห์/เดือน |
| "ทองขึ้นเพราะสงคราม" | GPR spike มักถูก price ไปก่อน; ซื้อตามข่าว = ซื้อที่ยอด | ใช้ GPR เป็นตัวเพิ่มความระวัง + รอ retest |
| "DXY ขึ้น → ทองต้องลง" | มีช่วงที่ทองขึ้นพร้อม DXY (ดีมานด์ธนาคารกลาง/ภูมิรัฐศาสตร์) | ใช้เป็นตัวกรองนุ่ม ๆ ไม่ใช่กฎแข็ง |
| "Funding > 0.03% = จุดท็อป" | 0.03% เป็น "elevated" ที่คนพูดถึงกัน แต่ไม่มีหลักฐานว่าเป็นจุดกลับตัว | ใช้เป็น **มาตรวัดความแออัด** แล้วลด size |
| "Correlation BTC–Nasdaq คงที่" | 0.87 ในปี 2024 แต่เปลี่ยนตาม regime | คำนวณ rolling correlation เองทุกสัปดาห์ |
| "เปิด London = ต้อง breakout" | session open ไม่ได้แปลว่ามี edge; ขึ้นกับ flow วันนั้น | ใช้ session เป็น **ตัวเลือกเวลา** ไม่ใช่สัญญาณ |

### 5.2 กับดักข้อมูลในระบบนี้ (ตรวจจากโค้ด/แคชจริง)

1. **FF calendar fail open + 429:** `fetch_ff_calendar()` กลืน exception ทุกชนิดแล้วคืน `None`; `get_news_window_status(None)` คืน `"calendar unavailable, trading normally"` → **ไม่มีข่าว = เทรดปกติ** ซึ่งอันตราย. เจอจริง: แคชทั้ง 3 สินทรัพย์เป็น `{"value": null}` (2026-11-08 20:23) และยิงซ้ำ ๆ แล้วได้ **HTTP 429** (แม้เปลี่ยน UA) → rate-limit ระดับ IP
2. **TTL ทำให้ความล้มเหลวค้าง 1 ชั่วโมง:** `get_cached_value` แคชค่า `None` ไว้ด้วย (bounded by TTL) → 429 ครั้งเดียว = ไม่มี news gate ไป 1 ชม.
3. **Sentiment ไม่ได้ต่อกับ live agent:** `fetch_fear_greed_index()` / `fetch_news_sentiment()` ถูกใช้แค่ใน `backtest/strategies.py` แบบ experimental (default `False`) — grep แล้วไม่มีการเรียกใน `agents/` → F&G/ข่าว **ยังไม่ถูกใช้ตัดสินใจจริง**
4. **ข้อมูลสังเคราะห์ปนเข้า CSV:** `backtest/data_loader.py` (`generate_fallback_data`) สร้างราคาสังเคราะห์เมื่อ Yahoo ล้ม แล้ว **เขียนทับ CSV** ที่ path เดียวกับข้อมูลจริง → งานวิจัย/backtest ที่อ่านไฟล์นั้นอาจวิเคราะห์ข้อมูลปลอมโดยไม่รู้ตัว
5. **COT lag 3 วัน / WGC lag 1 เดือน:** ตัวเลข positioning ที่เห็นไม่ใช่สถานะปัจจุบัน → ใช้จับจังหวะไม่ได้
6. **ข่าว tone ไม่มี archive:** Google News RSS ให้เฉพาะ "ตอนนี้" → backtest sentiment ข่าวย้อนหลังไม่ได้จริง (โค้ดเดิมใส่ค่าเดียวทั้ง run)
7. **Timezone/DST:** 8:30 ET = 12:30 หรือ 13:30 UTC ขึ้นกับฤดู; พลาด 1 ชั่วโมง = blackout ผิดเวลา
8. **GPR ต้องมี `xlrd`:** ดาวน์โหลด `.xls` ได้ แต่ `pandas.read_excel` ล้มด้วย `ImportError: Install xlrd` (venv นี้ยังไม่มี) → ต้องติดตั้งก่อนใช้
9. **`derisk` ถูกคำนวณแต่ไม่ถูกใช้:** `agents/base_agent.py` ตรวจแค่ `news_status["blackout"]` แล้ว return; สถานะ `derisk` (ข่าว High-impact อื่นที่ไม่ใช่ NFP/FOMC/CPI) **ไม่มีผลกับขนาดไม้** → ต้องลด size เองตามเช็กลิสต์ข้อ ①

### 5.3 กติกาการใช้ (บังคับ)

1. ปัจจัยภายนอก **ห้ามเป็นเหตุผลเดียวในการเข้าเทรด** — ต้องมีสัญญาณจาก price action/strategy ของระบบก่อน
2. ปัจจัยภายนอกใช้ได้ 3 อย่างเท่านั้น: **(ก) veto** (ห้ามเข้า), **(ข) ลด size**, **(ค) เลื่อนเวลา**
3. ถ้าข้อมูลภายนอกขาด → **fail-safe** (ลด size/ไม่เทรด) ไม่ใช่ fail open
4. ตัวเลขทุกตัวในเอกสารนี้เป็น snapshot — **ห้าม quote ซ้ำโดยไม่เช็คเวลา**; ให้รันใหม่ทุกครั้ง
5. ทุกครั้งที่จะอ้าง "สถิติ" ต้องมีแหล่ง + วันที่ + ช่วงตัวอย่าง ไม่งั้นให้เขียนว่า "ไม่มีข้อมูล"
6. **เกณฑ์ตัวเลขในเช็กลิสต์เป็น rule-of-thumb ไม่ใช่ผลวิจัย:** `|funding| ≥ 0.03%/8h` มาจากคอมเมนต์ใน `backtest/strategies.py` (`FUNDING_EXTREME = 0.0003`) ซึ่งระบุเองว่าเป็น "threshold ที่คนพูดถึงกัน" · `25/75` F&G มาจากโค้ด backtest แบบ experimental · `spread > 1.5 เท่า` และ `1 ATR` เป็นข้อเสนอเชิงปฏิบัติของเอกสารนี้ → **ต้อง recalibrate ด้วยข้อมูลจริงของบัญชีตัวเองก่อนใช้เป็นกฎตายตัว**

---

### สรุป 3 ปัจจัยที่สำคัญที่สุด (ตามลำดับ)

1. **ปฏิทิน USD High-impact (±15 นาที)** — ตัวเดียวที่ทำให้ทั้ง 3 สินทรัพย์หยุดเทรดได้ทันที; แต่ระบบปัจจุบัน fail open เมื่อเจอ 429
2. **Real yield 10Y + DXY (ทอง) / Funding + OI (BTC, ETH)** — ตัวกำหนด bias และความแออัด; ใช้ลด size ไม่ใช่หาจังหวะเข้า
3. **Session liquidity (07:00–16:00 UTC) + spread ของตัวเอง** — ตัวคูณคุณภาพของทุกสัญญาณ; ตรวจด้วย tick ของเราเอง ไม่ใช่เชื่อตาราง

**สิ่งที่มักทำให้เข้าใจผิดมากที่สุด:** (ก) คิดว่า "แคชว่า null = ไม่มีข่าว" (จริง ๆ คือไม่รู้), (ข) เอา correlation/ความสัมพันธ์ที่ผันผวนตาม regime มาใช้เป็นกฎตายตัว, (ค) ใช้ข้อมูลที่มาช้า (COT/ETF/WGC) มาจับจังหวะ intraday, (ง) ไล่ราคาตามข่าวที่ตลาด price ไปแล้ว
