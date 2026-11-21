# Improvement Backlog — daytrad (squad all9)

> สร้าง 2026-11-21 โดยรอบวิจัย qualabinance #04 (CEO อนุมัติการข้าม chinese-wall เพื่อช่วย squad)
> หลักฐาน: `qualabinance/projects/04-backtest-engine/reports/squad_validation_2026-11-21.json`
> **กติกา: รายการที่กระทบเงินจริงต้องรอ user เคาะก่อนเสมอ — ห้ามแก้ live config เอง**

## P0 — หลักฐานชัดว่าลบ (รอ user เคาะ)

- [x] **BTC/ETH M5 scalper: negative edge ยืนยัน 2 engine อิสระ** → **จัดการแล้ว 2026-11-21 (demo, user อนุมัติ "ลองได้เลย")**
  - BTC: บังคับ M15 + Strategy D (บวกทุก fold: +0.239R PF 1.42) + **ปิด cadence pacer** (pacer เอง −0.103R/1,398 ไม้)
  - ETH: **pause entry ใหม่** (`config.eth_entries_enabled=False`, ปลดด้วย env ETH_ENTRIES_ENABLED=true) — ทุก variant ลบหรือ fold-unstable; pacer −0.281R/1,361 ไม้ ลบทุก fold
  - เทสต์ 225 ผ่าน, รีสตาร์ท squad แล้ว, ยืนยันจาก log: BTC=MTF_Momentum_Cross_D, ETH=ENTRIES_PAUSED
- [ ] **NEWS_CALENDAR_UNAVAILABLE** — ฟีดข่าวล่ม บล็อกเข้าไม้ทุกสินทรัพย์รวม crypto (ค้างจากรอบ ops ก่อน)

## ผล validate CADENCE PACER (กลไกที่เข้าไม้จริงส่วนใหญ่ใน live) — 2026-11-21

| Asset | ไม้ | Exp(R) | PF | folds | ข้อสรุป |
|---|---|---|---|---|---|
| Gold M5 | 1,040 | **+0.093** | 1.14 | บวกทุก fold | **เก็บไว้** — แหล่งกำไรจริงของ gold (ตรงกับ live journal ที่ SELL ชนะในขาลง) |
| BTC M5 | 1,398 | −0.103 | 0.86 | ลบ 3/4 | ปิดแล้ว |
| ETH M5 | 1,361 | −0.281 | 0.65 | ลบทุก fold | ปิดแล้ว (pause ทั้ง specialist) |

- live closed orders ยืนยัน pattern เดียวกัน: ETH/BTC SELL แพ้ย่อยๆ ซ้ำๆ (−$3 ถึง −$7 ต่อไม้)
- หมายเหตุ: pacer backtest ใช้ EMA200 จาก M5 window (live ใช้ HTF M15 เมื่อ >=200 แท่ง) — approximation

## P1 — ยังไม่มี edge แต่ยังไม่ตาย

- [ ] **Gold M5: กลืนทุนภายใต้ fill เข้มงวด** — 568 ไม้ exp −0.014R PF 0.98 DSR 0.05
  - ผลบวกเดิม (+5.78%) มาจาก bias: TP-before-SL + spread ครั้งเดียว + เข้าราคา close แท่งสัญญาณ
  - ข้อเสนอ: ลดความถี่ไม้/เพิ่มคุณภาพสัญญาณ, ทดสอบผล ML filter (live เปิด threshold 0.70 แต่ backtest ยังไม่จำลอง)
- [ ] **แก้ bias ใน legacy M5BacktestEngine** (`backtest/run_m5_backtest.py`): TP ก่อน SL, spread หักครั้งเดียว, hardcode params ไม่อ่าน config — แก้แล้วผลเก่าจะเทียบกันไม่ได้ (ต้อง push main = กระทบ live → รอเคาะ)

## P2 — sample ไม่พอตัดสิน

- [ ] **6 ตัว M15 (xag/xpt/gbp/eur/ukoil/xng): ไม้น้อยเกินไป** — xag 7, xpt 5, gbp 4, eur 4 ไม้ใน ~60 วัน → ยัง validate ไม่ได้; ต้องขยายประวัติราคา (fetch เพิ่ม) ก่อน
- [ ] **UKOIL M15 (Strategy C): สัญญาณบวกน่าสนใจ** — 36 ไม้ exp +0.57R PF 1.87 DSR 0.75 (WEAK) แต่ contract_size=100 ยัง **unverified** → ยืนยัน spec จาก MT5 ก่อนเชื่อผล lot
- [ ] **XNGUSD M15 (Strategy A): ลบ** — 26 ไม้ exp −0.17R PF 0.77 → เฝ้าระวัง

## ข้อจำกัดของการวิจัยนี้ (อ่านก่อนใช้ผล)

1. ข้อมูล CSV ก.ค.–ก.ย. 2026 (~60 วัน) — ไม่ใช่ regime ปัจจุบัน; timestamp เป็น UTC+7 ตามไฟล์เดิม (คงไว้เพื่อเทียบกับ sweep เก่า)
2. ใช้ signal function จริงจาก daytrad แต่ **ไม่ได้จำลอง ML filter / news gate / cadence pacer** ของ live
3. EMA200 ในกลยุทธ์คำนวณจาก window สั้น (tail 35–50) — fidelity เท่า live แต่ไม่ใช่ EMA200 จริง 200 แท่ง
4. DSR ใช้ variance ของ fold Sharpes เป็น proxy ของ trial variance (จำนวน trial จริงจากการ sweep มากกว่านี้ → DSR จริงอาจต่ำกว่า)
5. ผลเป็น R-multiple ก่อนข้อจำกัด lot จริง (min lot 0.01 clamp ทำให้ risk จริงสูงกว่า config ที่ทุนต่ำ)

## เครื่องมือที่พร้อมใช้แล้ว

- Engine: `qualabinance/projects/04-backtest-engine/` (เทสต์ 11 ผ่าน)
- รันซ้ำ: `.venv\Scripts\python.exe validate_squad.py --assets all --folds 4`
- Adapter อ่าน daytrad อย่างเดียว ไม่แตะไฟล์ live