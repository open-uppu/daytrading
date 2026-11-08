# 🚀 Daytrad Agentic Squad - 1-Click Redeployment Runbook

เอกสารสรุปขั้นตอนการ Deploy และคำสั่งสำหรับรันระบบอัตโนมัติ 100% บนเครื่อง Windows Laptop (`100.105.249.12`) และ Mac Workstation

---

## 1. วิธีใช้งานแบบ 1-Click (100% Turnkey) บน Windows Laptop

เมื่อมีการแก้ไขโค้ดใหม่ หรือต้องการรีสตาร์ทระบบทั้งหมดให้พร้อมเทรด:

### 👉 ดับเบิ้ลคลิกไฟล์:
`D:\daytrading\deploy_laptop.bat`

หรือเปิด PowerShell / Command Prompt แล้วพิมพ์:
```cmd
cd D:\daytrading
deploy_laptop.bat
```

### สิ่งที่สคริปต์จัดการให้โดยอัตโนมัติ (ไม่ต้องทำอะไรเอง):
1. **[1/4] ปิดคอนเทนเนอร์เดิม:** สั่ง `docker compose down` เคลียร์ process เก่าออกทั้งหมด
2. **[2/4] ดึงโค้ดล่าสุดจาก Git:** ดึงการอัปเดตโมเดล, ตัวเชื่อมต่อ Suffix อัตโนมัติ, และระบบคำนวณความเสี่ยง Cent Account
3. **[3/4] Build & Launch Containers:** รัน `docker compose --profile live up -d --build` เพื่อเริ่มทั้ง:
   - `agentic_mt5_bridge`: สะพานเชื่อมต่อ MT5 (Port `8000`)
   - `agentic_squad_agent`: สมองกล 9 Specialists ทำงานในโหมด Live
4. **[4/4] ตรวจสอบความพร้อม (Health Check):** ยิง curl ทดสอบสถานะ MT5 Bridge และยืนยันความสดของแท่งเทียน

---

## 2. ฟีเจอร์หลักที่ได้รับการติดตั้งในระบบใหม่

### 🎯 1. Universal Broker Suffix Auto-Detection (ตรวจจับนามสกุลโบรกเกอร์อัตโนมัติ)
* ไม่ต้องแก้โค้ดเมื่อเปลี่ยนโบรกเกอร์หรือเปลี่ยนประเภทบัญชี
* ระบบตรวจจับนามสกุลจาก MT5 Telemetry อัตโนมัติ:
  - **Exness Standard:** `BTCUSDm`, `ETHUSDm`, `XAUUSDm` (ตัวพิมพ์เล็ก `m`)
  - **Exness Cent:** `BTCUSDc`, `ETHUSDc`, `XAUUSDc` (ตัวพิมพ์เล็ก `c`)
  - **Raw / Zero / Standard Broker อื่นๆ:** `BTCUSD`, `ETHUSD`, `XAUUSD`
* คำสั่งซื้อขายและแท่งเทียนจะถูกแปลงให้ตรงตามที่โบรกเกอร์ต้องการ 100% ป้องกันข้อผิดพลาด `Unknown or unavailable symbol`

### 💰 2. Cent Account (USC) & Dynamic 3% Daily Target Lock
* สำหรับงบ **2,000 บาท** แนะนำบัญชี **Exness Standard Cent (USC)**:
  - ทุน 2,000 THB ≈ $57 USD = **5,700 USC**
  - ล็อคเป้าหมายกำไรรายวัน +3% ที่ **+171 USC** (ประมาณ 60 บาทต่อวัน)
  - คำนวณ Lot Size ขั้นต่ำ (0.01 Lot Cent = ไม้ละไม่กี่เซนต์) ทำให้ความเสี่ยงต่ำมากและทนความผันผวนได้สูง

### ⏰ 3. NTP Clock Skew Tolerance & Weekend Standby
* รองรับเวลาเหลื่อม (Clock Drift) ระหว่าง Windows และคอนเทนเนอร์/Mac ได้สูงสุด 15 วินาที
* ในวันหยุดสุดสัปดาห์ (เสาร์-อาทิตย์) ตลาดทองคำและ Forex จะ Standby รอเปิดวันจันทร์ ส่วนตลาด Crypto (`BTC`, `ETH`) จะเทรดต่อเนื่อง 24/7

---

## 3. สถาปัตยกรรม Port และโหมด Multi-Account

| Port | บริการ | บัญชีแนะนำ | คำสั่งเปิดใช้งาน |
|---|---|---|---|
| `8000` | MT5 Primary Bridge & Squad | บัญชีจริง / Cent (`USC`) | `docker compose --profile live up -d` |
| `8001` | MT5 Secondary Bridge & Squad | บัญชีทดลอง Demo Standard | `docker compose --profile multi up -d` |
| `3000` | Trader Central Hub Dashboard | ทุกบัญชี (สลับดูได้) | `http://100.105.249.12:3000` |
| `8005` | Hub Backend API | รวมข้อมูลภาพรวมทั้งระบบ | `http://100.105.249.12:8005` |

---

## 4. คำสั่งตรวจสอบการทำงาน (Useful Commands)

* **ดู Log การเทรดของบอทแบบเรียลไทม์:**
  ```cmd
  docker logs -f agentic_squad_agent
  ```
* **ดูสถานะการเชื่อมต่อ MT5:**
  ```cmd
  curl http://localhost:8000/api/mt5/status
  ```
* **ดูออเดอร์ที่เปิดอยู่และยอดเงินคงเหลือ:**
  ```cmd
  curl http://localhost:8000/api/mt5/account
  ```
