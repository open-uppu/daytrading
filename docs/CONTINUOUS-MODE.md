# Continuous Mode ("ไม่จำกัด") — สิ่งที่เปลี่ยน และสิ่งที่จงใจไม่เปลี่ยน

## สรุปสั้น
- **เอาออกแล้ว**: การหยุดเทรดเมื่อถึงเป้ากำไร (+20% hard target) และการลดความเสี่ยงครึ่งหนึ่งเมื่อผ่าน +3% (soft derisk)
- **เอาออกแล้ว (ตามคำสั่ง)**: จุดตัดขาดทุนรายวัน -5% — ใช้ `--no-loss-cutoff` (`daily_max_loss_cutoff_enabled=False`)
- ผลลัพธ์: ระบบสแกนและเปิดไม้ได้ตลอดทั้งวัน ไม่มีเพดานกำไรและไม่หยุดที่ -5% — เบรกที่เหลือคือมาร์จิ้นของโบรกเกอร์

## วิธีเปิด/ปิด

```powershell
# เปิด (CLI)
python main.py run --agent=all --mode=paper --paper-feed=bridge --interval=10 --continuous --no-loss-cutoff

# เปิด (Docker, live) — squad service ตั้ง --continuous ไว้แล้วใน docker-compose.yml
docker compose --profile live up -d squad

# ปิดcontinuous = ไม่ใส่ flag (ค่า default ใน config คือ True = ล็อกกำไรตามเดิม)
```

ตัวคุมจริงคือฟิลด์ `daily_profit_lock_enabled` ใน `config.py`:

| ค่า | พฤติกรรม |
|---|---|
| `True` (default) | ถึง +3% → ลด risk ครึ่ง; ถึง +20% → หยุดทั้ง squad |
| `False` | ไม่ลด risk และไม่หยุดเมื่อได้กำไร; ขาดทุน -5% ยังหยุดเหมือนเดิม |

## ไฟล์ที่แก้
| ไฟล์ | การเปลี่ยนแปลง |
|---|---|
| `config.py` | เพิ่ม `daily_profit_lock_enabled` |
| `risk/manager.py` | `DailySessionTracker.is_hard_target_reached` และ `risk_multiplier` เคารพ flag; รับพารามิเตอร์ `profit_lock_enabled` |
| `agents/squad_manager.py` | `hard_target_reached` เป็น False เมื่อ continuous; ไม่ log soft derisk |
| `main.py` | เพิ่ม flag `--continuous` + แบนเนอร์เตือนโหมด |
| `docker-compose.yml` | squad ใช้ `--continuous`; เพิ่ม service `dev` (idle shell) |

## ทำไมไม่เอาตัวตัดขาดทุนออก
บัญชีทดลองนี้แพ้ -5.06% ในวันเดียวก่อนระบบตัดจบ (จาก $500 → $474.68) ถ้าไม่มีเบรกนี้ การเทรดแบบไม่จำกัดจำนวนไม้จะทำให้ขนาดความเสียหายโตแบบทบต้นจนควบคุมไม่ได้

ถ้าต้องการผ่อนเพิ่ม ให้ขยับ `daily_max_loss_pct` (เช่น 0.07) **ไม่ใช่ลบออก** — และควรทดลองใน paper ก่อนอย่างน้อย 2 สัปดาห์

## การสังเกตผล (observation loop)
- `docker exec agentic_dev tail -f /app/artifacts/dev_continuous.log`
- สถานะกระดาษ: `journal/dev_continuous/paper_live/paper_state.json`
- ทบทวนทุก 3 ชั่วโมงผ่าน scheduled task (09/12/15/18/21/00 เวลาไทย)

## คำเตือน
Continuous mode ไม่ได้ทำให้กลยุทธ์ดีขึ้น มันแค่เอาเพดานกำไรออก ถ้ากลยุทธ์มี expectancy ติดลบ การเทรดนานขึ้น = ขาดทุนมากขึ้น ห้ามสรุปว่า "ไม่จำกัด = กำไรไม่จำกัด"
