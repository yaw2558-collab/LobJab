# ลบจ๊าบ LobJab

โปรแกรม Windows ลบวัตถุออกจากรูปด้วย AI บนเครื่อง — เปิดรูป ระบายจุดที่ลบ
พิมพ์บอกพื้นหลัง กดปุ่มเดียว AI เติมให้ ผ่าน **sd-cli.exe**
(stable-diffusion.cpp + Vulkan — ตัวเดียวกับที่แอป Amuse/GenJab ใช้) รันบนการ์ดจอ AMD ได้เลย

## วิธีรัน (ครั้งแรก)

```
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

แล้วดับเบิลคลิก `run.bat`

## ใช้ผ่าน command line

```
.venv\Scripts\python inpaint.py photo.jpg mask.png "clean background, no objects" -o out/fixed.png
```

mask: รูปขาว/ดำขนาดเท่าต้นฉบับ (ขาว = ลบแล้วเติมใหม่, ดำ = เก็บเดิม)

## ไฟล์

- `app.py` — หน้าต่างโปรแกรม (ระบาย mask + แกลเลอรี)
- `inpaint.py` — ตัวลบวัตถุ (CLI ได้ด้วย)
- `test_inpaint.py` / `test_app.py` — เทส (`python test_inpaint.py`)
- `requirements.txt` — pillow + customtkinter + send2trash

## สิ่งที่ต้องมีในเครื่อง

- แอป **Amuse** (ยืม `sd-cli.exe` จาก `%LOCALAPPDATA%\Amuse\RuntimeStableDiffusionCpp\vulkan\`)
- โมเดล **SD-Turbo** (`sd_turbo.safetensors` ใน HF cache หรือโฟลเดอร์ `models/`)
