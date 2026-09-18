# Agentic Gold (XAUUSD) Day Trading System

ระบบเทรดทองคำ (XAUUSD) รายวันแบบ Agentic AI ทำงานวน Loop อัตโนมัติ ผสานการวิเคราะห์ข้อมูลเชิงปริมาณ (Quantitative Indicators) เข้ากับการวิเคราะห์ภาพกราฟแท่งเทียน (Multimodal Chart Vision) มีเป้าหมายทำกำไรอย่างน้อย **3% ต่อวัน** พร้อมระบบ **Self-Learning จดบันทึกและเรียนรู้ข้อผิดพลาดลงไฟล์ Markdown (.md)** และเชื่อมต่อกับ **MetaTrader 4 (MT4)**

---

## สถาปัตยกรรมระบบ (Architecture)

1. **Skill-Based Architecture (`SKILL.md`)**:
   - Master Skill: [SKILL.md](file:///Users/up-mac/wokrspace/mind/trader/daytrad/SKILL.md)
   - Sub-Skills:
     - [skills/market_analyzer/SKILL.md](file:///Users/up-mac/wokrspace/mind/trader/daytrad/skills/market_analyzer/SKILL.md): คำนวณ EMA 20/50/200, ATR(14), RSI(14), Support/Resistance
     - [skills/chart_vision/SKILL.md](file:///Users/up-mac/wokrspace/mind/trader/daytrad/skills/chart_vision/SKILL.md): เรนเดอร์กราฟแท่งเทียน Dark Mode และวิเคราะห์รูปแบบ Price Action (Pin Bar, Engulfing, Rejection)
     - [skills/risk_manager/SKILL.md](file:///Users/up-mac/wokrspace/mind/trader/daytrad/skills/risk_manager/SKILL.md): คุมเป้าหมายกำไร 3% รายวัน, Daily Target Lock, Cutoff ขาดทุนสูงสุด 2%, คำนวณ Lot Size อัตโนมัติ
     - [skills/mt4_bridge/SKILL.md](file:///Users/up-mac/wokrspace/mind/trader/daytrad/skills/mt4_bridge/SKILL.md): โปรโตคอลเชื่อมต่อกับ MetaTrader 4
     - [skills/trade_reflector/SKILL.md](file:///Users/up-mac/wokrspace/mind/trader/daytrad/skills/trade_reflector/SKILL.md): ตรวจสอบผลการเทรด (Autopsy), บันทึกข้อผิดพลาด, อัปเดตกฎการเทรด

2. **Multimodal Chart Vision**:
   - เรนเดอร์กราฟแท่งเทียน M15/H1 แบบความละเอียดสูงบันทึกลง `artifacts/charts/`
   - วิเคราะห์ภาพด้วย Vision Engine ในตัว (Heuristic Vision) หรือเชื่อมต่อกับ Gemini Vision (`gemini-1.5-flash`) / OpenAI Vision (`gpt-4o-mini`) เมื่อใส่ API Key

3. **เป้าหมายกำไร 3% ต่อวัน (Daily Target Lock)**:
   - ทุน 10,000 USD -> เป้าหมายกำไร 300 USD ต่อวัน
   - เมื่อกำไรสะสมในวันนั้นถึงหรือเกิน 3.0% ระบบจะเข้าสู่สถานะ `DAILY_TARGET_REACHED` และ **หยุดเปิดออเดอร์ใหม่ทันที** เพื่อปกป้องกำไร
   - ควบคุมการขาดทุนสูงสุดรายวัน (Max Daily Loss) ไม่เกิน 2.0% (-200 USD บนทุน 10,000)

4. **Self-Learning & Mistake Reflection (.md)**:
   - ทุกครั้งที่ปิดออเดอร์ (ทั้ง Win และ Loss) ระบบจะทำ Post-Trade Autopsy
   - บันทึกการวิเคราะห์ลง `journal/trades/YYYY-MM-DD_trade_<ticket>.md`
   - รวบรวมสถิติข้อผิดพลาดลง [journal/mistakes_database.md](file:///Users/up-mac/wokrspace/mind/trader/daytrad/journal/mistakes_database.md)
   - สรุปเป็นกฎข้อห้ามและอัปเดตลง [journal/learned_rules.md](file:///Users/up-mac/wokrspace/mind/trader/daytrad/journal/learned_rules.md) อัตโนมัติ
   - **Pre-Trade Filter**: ก่อนส่งคำสั่งซื้อขายใหม่ ระบบจะนำ Setup มาตรวจกับ `learned_rules.md` เสมอ หากเคยผิดพลาดในลักษณะนี้ ระบบจะปฏิเสธการเทรดทันที

5. **MetaTrader 4 Integration & Paper Trading**:
   - `mt4/AgenticMT4Bridge.mq4`: Expert Advisor (MQL4) สำหรับเปิดบนกราฟ MT4 ส่งราคาและรับคำสั่งซื้อขาย
   - `mt4/bridge_server.py`: FastAPI REST API Server สำหรับสื่อสารกับ MT4
   - `mt4/paper_broker.py`: โหมดจำลองการเทรดความสมจริงสูงพร้อมราคาทองคำสำหรับทดสอบได้ทันที

---

## วิธีใช้งานคำสั่ง CLI

### 1. วิเคราะห์ตลาดแบบรอบเดียว (Single-Pass Analysis)
เรนเดอร์กราฟ วิเคราะห์แท่งเทียน แสดง Confluence Score และผลการตัดสินใจในตาราง:
```bash
python3 main.py analyze
```

### 2. รัน Loop ตรวจจับโอกาสเข้าซื้อ/ขายอัตโนมัติ (Autonomous Loop)
- **โหมด Paper Trading (จำลองการเทรดสมจริง):**
  ```bash
  python3 main.py loop --mode=paper --interval=15
  ```
- **โหมดเชื่อมต่อ MetaTrader 4:**
  ```bash
  # เทอร์มินัล 1: เปิด Bridge Server
  python3 main.py bridge
  
  # เทอร์มินัล 2: เริ่ม Agent Loop
  python3 main.py loop --mode=mt4 --interval=10
  ```

### 3. ตรวจสอบสมุดบันทึกและกฎที่ระบบเรียนรู้ (Journal & Rules)
```bash
python3 main.py journal
```

### 4. รันชุดทดสอบความถูกต้อง (Test Suite)
```bash
python3 -m pytest tests/ -v
```

---

## การติดตั้งบน MetaTrader 4 (MT4)

1. คัดลอกไฟล์ `mt4/AgenticMT4Bridge.mq4` ไปวางในโฟลเดอร์ `MQL4/Experts/` ของ MetaTrader 4
2. เปิดโปรแกรม MetaEditor กด **Compile** (F7)
3. ใน MT4 ไปที่เมนู **Tools -> Options -> Expert Advisors**:
   - ติ๊กถูกที่ `Allow automated trading`
   - ติ๊กถูกที่ `Allow WebRequest for listed URL` แล้วเพิ่ม URL: `http://127.0.0.1:8000`
4. ลาก Expert Advisor `AgenticMT4Bridge` ไปใส่บนกราฟทองคำ `XAUUSD` Timeframe `M15`
