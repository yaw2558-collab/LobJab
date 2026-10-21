"""ลบจ๊าบ LobJab — ลบวัตถุออกจากรูปด้วย AI บนเครื่อง (sd.cpp inpaint + SD-Turbo)."""
import json
import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageTk
from send2trash import send2trash

from inpaint import inpaint

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

OUT_DIR = "out"
SETTINGS_FILE = "settings.json"
ACCENT = "#D97A2B"
ACCENT_HOVER = "#E8933F"
TITLE_FONT = ("Segoe UI", 26, "bold")
HEAD_FONT = ("Segoe UI", 12, "bold")
BODY_FONT = ("Segoe UI", 12)
MODEL_IDS = {"SD-Turbo (เร็ว)": "sd-turbo", "SDXL-Turbo (1024px)": "sdxl-turbo"}
OVERLAY_RGBA = (217, 122, 43, 140)
FEATHER = 8


def next_path(out_dir):
    """คืน path ไฟล์รูปถัดไป (fixNNN.png) ในโฟลเดอร์ที่เลือก — ไม่ชนชื่อเดิม."""
    return next_paths(out_dir, 1)[0]


def next_paths(out_dir, n, prefix="fix"):
    """จองชื่อไฟล์ทีเดียว n ชื่อ — กันนับซ้ำตอนโฟลเดอร์เน็ตเวิร์กเห็นไฟล์ช้า."""
    try:
        taken = {f for f in os.listdir(out_dir) if f.endswith(".png")}
    except OSError:
        taken = set()
    paths, i = [], 1
    while len(paths) < n:
        name = f"{prefix}{i:03d}.png"
        if name not in taken:
            paths.append(os.path.join(out_dir, name))
            taken.add(name)
        i += 1
    return paths


def load_out_dir():
    """อ่านที่เก็บรูปที่จำไว้ — ไฟล์หาย/พัง หรือโฟลเดอร์ไม่อยู่แล้ว กลับไปใช้ out."""
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            d = json.load(f).get("out_dir", "")
        if d and os.path.isdir(d):
            return os.path.normpath(d)
    except (OSError, ValueError):
        pass
    return OUT_DIR


def save_out_dir(out_dir):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump({"out_dir": out_dir}, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


GALLERY_LIMIT = 40


def load_gallery_thumbs(paths, size=84):
    """เปิด+ย่อรูปทีละไฟล์ คืน [(path, PIL.Image)] — ไม่แตะ Tk รันใน worker thread ได้."""
    thumbs = []
    for path in paths:
        try:
            with Image.open(path) as im:
                thumb = im.convert("RGB")
                thumb.thumbnail((size, size))
                thumbs.append((path, thumb))
        except Exception:  # noqa: BLE001
            continue
    return thumbs


def canvas_fit(img_w, img_h, box_w, box_h):
    """กรอบรูป (x0, y0, w, h) กลาง canvas แบบ contain — ใช้วางรูปและแมปพิกัดพู่กัน."""
    scale = min(box_w / img_w, box_h / img_h)
    w, h = max(1, int(img_w * scale)), max(1, int(img_h * scale))
    return ((box_w - w) // 2, (box_h - h) // 2, w, h)


def event_to_image(ex, ey, rect, img_w, img_h):
    """แมปพิกัดเมาส์บน canvas กลับเป็นพิกัดรูป — นอกกรอบคืน None."""
    x0, y0, w, h = rect
    if not (x0 <= ex < x0 + w and y0 <= ey < y0 + h):
        return None
    ix = min(img_w - 1, int((ex - x0) / w * img_w))
    iy = min(img_h - 1, int((ey - y0) / h * img_h))
    return (ix, iy)


def apply_overlay(disp, mask_disp, color=OVERLAY_RGBA):
    """ทาสีโปร่งใสทับบริเวณ mask (ขาว) บนรูปที่โชว์ — คืน RGBA."""
    solid = Image.new("RGBA", disp.size, color)
    clear = Image.new("RGBA", disp.size, (0, 0, 0, 0))
    tint = Image.composite(solid, clear, mask_disp.convert("L"))
    return Image.alpha_composite(disp.convert("RGBA"), tint)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("ลบจ๊าบ LobJab")
        self.geometry("1100x720")
        self.minsize(960, 640)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.orig = None
        self.mask = None
        self.result = None
        self.current_path = None
        self.out_dir = load_out_dir()
        self._photo = None
        self._rect = (0, 0, 1, 1)
        self._paint_job = None
        self._resize_job = None
        self.thumb_refs = []

        # ---- ซ้าย: แผงควบคุม ----
        side = ctk.CTkScrollableFrame(self, width=300, corner_radius=0)
        side.grid(row=0, column=0, sticky="ns")

        ctk.CTkLabel(side, text="ลบจ๊าบ", font=TITLE_FONT, text_color=ACCENT).pack(anchor="w", padx=16, pady=(14, 0))
        ctk.CTkLabel(side, text="LobJab — ลบวัตถุด้วย AI บนเครื่อง", font=BODY_FONT).pack(anchor="w", padx=16, pady=(0, 10))

        ctk.CTkButton(side, text="เปิดรูป...", font=("Segoe UI", 13, "bold"), height=36,
                      command=self.on_open).pack(fill="x", padx=16, pady=(0, 8))

        brush_row = ctk.CTkFrame(side, fg_color="transparent")
        brush_row.pack(fill="x", padx=16)
        ctk.CTkLabel(brush_row, text="ขนาดพู่กัน", font=HEAD_FONT).pack(side="left")
        self.brush_val = ctk.CTkLabel(brush_row, text="32", font=BODY_FONT, width=30)
        self.brush_val.pack(side="right")
        self.brush = ctk.CTkSlider(side, from_=4, to=120, number_of_steps=116, command=self.on_brush)
        self.brush.set(32)
        self.brush.pack(fill="x", padx=16, pady=(0, 6))

        self.mode = ctk.CTkSegmentedButton(side, values=["ระบาย", "ยางลบ"], font=BODY_FONT)
        self.mode.set("ระบาย")
        self.mode.pack(fill="x", padx=16, pady=(0, 6))
        ctk.CTkButton(side, text="ล้าง mask", font=BODY_FONT, fg_color="transparent",
                      border_width=1, command=self.on_clear_mask).pack(fill="x", padx=16, pady=(0, 8))

        ctk.CTkLabel(side, text="พื้นหลังที่อยากให้เติม (English)", font=HEAD_FONT).pack(anchor="w", padx=16)
        self.prompt = ctk.CTkTextbox(side, height=60, font=BODY_FONT)
        self.prompt.pack(fill="x", padx=16, pady=(0, 8))
        self.prompt.insert("1.0", "clean background, no objects, empty")

        ctk.CTkLabel(side, text="Negative", font=HEAD_FONT).pack(anchor="w", padx=16)
        self.negative = ctk.CTkTextbox(side, height=44, font=BODY_FONT)
        self.negative.pack(fill="x", padx=16, pady=(0, 8))

        ctk.CTkLabel(side, text="โมเดล", font=HEAD_FONT).pack(anchor="w", padx=16)
        self.model = ctk.CTkOptionMenu(side, values=list(MODEL_IDS), font=BODY_FONT, width=268)
        self.model.pack(padx=16, pady=(0, 8))

        ctk.CTkLabel(side, text="ขนาดทำงาน (ด้านยาว)", font=HEAD_FONT).pack(anchor="w", padx=16)
        self.size = ctk.CTkSegmentedButton(side, values=["512", "768", "1024"], font=BODY_FONT)
        self.size.set("512")
        self.size.pack(fill="x", padx=16, pady=(0, 8))

        steps_row = ctk.CTkFrame(side, fg_color="transparent")
        steps_row.pack(fill="x", padx=16)
        ctk.CTkLabel(steps_row, text="Steps", font=HEAD_FONT).pack(side="left")
        self.steps_val = ctk.CTkLabel(steps_row, text="4", font=BODY_FONT, width=30)
        self.steps_val.pack(side="right")
        self.steps = ctk.CTkSlider(side, from_=1, to=12, number_of_steps=11, command=self.on_steps)
        self.steps.set(4)
        self.steps.pack(fill="x", padx=16, pady=(0, 6))

        strength_row = ctk.CTkFrame(side, fg_color="transparent")
        strength_row.pack(fill="x", padx=16)
        ctk.CTkLabel(strength_row, text="Strength", font=HEAD_FONT).pack(side="left")
        self.strength_val = ctk.CTkLabel(strength_row, text="1.00", font=BODY_FONT, width=30)
        self.strength_val.pack(side="right")
        self.strength = ctk.CTkSlider(side, from_=0.1, to=1.0, number_of_steps=18,
                                      command=self.on_strength)
        self.strength.set(1.0)
        self.strength.pack(fill="x", padx=16, pady=(0, 6))

        ctk.CTkLabel(side, text="Seed (ว่าง = สุ่มใหม่ทุกครั้ง)", font=HEAD_FONT).pack(anchor="w", padx=16)
        seed_row = ctk.CTkFrame(side, fg_color="transparent")
        seed_row.pack(fill="x", padx=16, pady=(0, 10))
        self.seed = ctk.CTkEntry(seed_row, font=BODY_FONT, placeholder_text="ว่าง = สุ่ม")
        self.seed.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(seed_row, text="สุ่ม", width=60, command=lambda: self.seed.delete(0, tk.END)).pack(side="right")

        ctk.CTkLabel(side, text="ที่เก็บรูป", font=HEAD_FONT).pack(anchor="w", padx=16)
        save_row = ctk.CTkFrame(side, fg_color="transparent")
        save_row.pack(fill="x", padx=16, pady=(0, 10))
        self.out_label = ctk.CTkLabel(save_row, text=self.out_dir, font=BODY_FONT, anchor="w",
                                      wraplength=180, justify="left")
        self.out_label.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(save_row, text="เลือก...", width=70, command=self.on_pick_dir).pack(side="right")

        type_row = ctk.CTkFrame(side, fg_color="transparent")
        type_row.pack(fill="x", padx=16, pady=(0, 10))
        self.out_entry = ctk.CTkEntry(type_row, font=BODY_FONT,
                                      placeholder_text="วาง path โฟลเดอร์ตรง ๆ ได้")
        self.out_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(type_row, text="ใช้", width=70, command=self.on_use_typed_dir).pack(side="right")

        self.btn = ctk.CTkButton(side, text="ลบวัตถุ", font=("Segoe UI", 15, "bold"), height=42,
                                 fg_color=ACCENT, hover_color=ACCENT_HOVER, command=self.on_run)
        self.btn.pack(fill="x", padx=16, pady=(0, 8))

        self.progress = ctk.CTkProgressBar(side, mode="indeterminate")
        self.progress.pack(fill="x", padx=16, pady=(0, 6))
        self.progress.stop()
        self.status = ctk.CTkLabel(side, text="พร้อม — เปิดรูปแล้วระบายจุดที่ลบ", font=BODY_FONT,
                                   wraplength=268, justify="left")
        self.status.pack(anchor="w", padx=16, pady=(0, 10))

        # ---- ขวา: กระดานระบาย + แกลเลอรี ----
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=12, pady=12)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)

        topbar = ctk.CTkFrame(main, fg_color="transparent")
        topbar.grid(row=0, column=0, sticky="ew")
        self.img_name = ctk.CTkLabel(topbar, text="—", font=HEAD_FONT)
        self.img_name.pack(side="left")
        ctk.CTkButton(topbar, text="ลบไฟล์นี้", font=BODY_FONT, width=90,
                      fg_color="#8A2E2E", hover_color="#A63A3A", command=self.on_delete).pack(side="right", padx=(6, 0))
        ctk.CTkButton(topbar, text="→ ใช้เป็นต้นฉบับ", font=BODY_FONT, width=130,
                      fg_color="transparent", border_width=1, command=self.on_use_result).pack(side="right", padx=(6, 0))
        self.view = ctk.CTkSegmentedButton(topbar, values=["ต้นฉบับ", "ผลลัพธ์"], font=BODY_FONT,
                                           command=self.on_view)
        self.view.set("ต้นฉบับ")
        self.view.pack(side="right")

        self.canvas = tk.Canvas(main, bg="#2b2b2b", highlightthickness=0, cursor="crosshair")
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", self.on_canvas_resize)
        self.canvas.bind("<ButtonPress-1>", self.on_paint)
        self.canvas.bind("<B1-Motion>", self.on_paint)

        ctk.CTkLabel(main, text="รูปที่เคยทำ (กดเพื่อเปิดเป็นต้นฉบับ)", font=HEAD_FONT).grid(
            row=2, column=0, sticky="w", pady=(8, 4))
        self.gallery = ctk.CTkScrollableFrame(main, orientation="horizontal", height=110)
        self.gallery.grid(row=3, column=0, sticky="ew")
        self._gallery_pending = None
        self.after(100, self._gallery_poll)
        self.refresh_gallery()

    def on_brush(self, v):
        self.brush_val.configure(text=str(int(round(float(v)))))

    def on_steps(self, v):
        self.steps_val.configure(text=str(int(round(float(v)))))

    def on_strength(self, v):
        self.strength_val.configure(text=f"{float(v):.2f}")

    def on_view(self, choice):
        self.refresh_canvas()

    def on_open(self):
        p = filedialog.askopenfilename(parent=self, title="เปิดรูป", filetypes=[
            ("รูปภาพ", "*.png *.jpg *.jpeg *.webp *.bmp"), ("ทั้งหมด", "*.*")])
        if p:
            self.load_input(p)

    def load_input(self, path):
        try:
            img = Image.open(path).convert("RGB")
        except Exception as e:  # noqa: BLE001
            self.status.configure(text=f"เปิดรูปไม่ได้: {e}")
            return
        self.orig = img
        self.mask = Image.new("L", img.size, 0)
        self.result = None
        self.current_path = path
        self.view.set("ต้นฉบับ")
        self.img_name.configure(text=os.path.basename(path))
        self.refresh_canvas()
        self.status.configure(text="ระบายจุดที่ลบ แล้วกด ลบวัตถุ")

    def refresh_canvas(self):
        if self.orig is None:
            return
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if cw < 50 or ch < 50:  # ยังจัด layout ไม่เสร็จ ใช้ค่าเดิม
            cw, ch = 640, 520
        show_result = self.view.get() == "ผลลัพธ์" and self.result is not None
        src = self.result if show_result else self.orig
        rect = canvas_fit(src.size[0], src.size[1], cw, ch)
        self._rect = rect
        x0, y0, w, h = rect
        disp = src.resize((w, h), Image.BILINEAR)
        if not show_result and self.mask is not None:
            disp = apply_overlay(disp, self.mask.resize((w, h), Image.NEAREST))
        self._photo = ImageTk.PhotoImage(disp)
        self.canvas.delete("all")
        self.canvas.create_image(x0, y0, anchor="nw", image=self._photo)

    def on_canvas_resize(self, event):
        if self.orig is None:
            return
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(200, self._refit)

    def _refit(self):
        self._resize_job = None
        self.refresh_canvas()

    def on_paint(self, event):
        if self.orig is None or self.mask is None:
            return
        if self.view.get() != "ต้นฉบับ":
            return
        pos = event_to_image(event.x, event.y, self._rect,
                             self.orig.size[0], self.orig.size[1])
        if pos is None:
            return
        scale = self.orig.size[0] / self._rect[2]
        r = max(1, int(self.brush.get() / 2 * scale))
        fill = 0 if self.mode.get() == "ยางลบ" else 255
        ImageDraw.Draw(self.mask).ellipse([pos[0] - r, pos[1] - r, pos[0] + r, pos[1] + r],
                                          fill=fill)
        if self._paint_job is not None:
            self.after_cancel(self._paint_job)
        self._paint_job = self.after(30, self._paint_refresh)

    def _paint_refresh(self):
        self._paint_job = None
        self.refresh_canvas()

    def on_clear_mask(self):
        if self.orig is None:
            return
        self.mask = Image.new("L", self.orig.size, 0)
        self.refresh_canvas()

    def apply_out_dir(self, d):
        """ตรวจแล้วใช้โฟลเดอร์เก็บรูป คืน True ถ้าสำเร็จ — ปุ่มเลือก/พิมพ์เองใช้ร่วมกัน."""
        d = os.path.normpath(d)
        if not os.path.isdir(d):
            self.status.configure(text="โฟลเดอร์นี้ไม่มี — ตรวจ path อีกครั้ง")
            return False
        self.out_dir = d
        save_out_dir(self.out_dir)
        self.out_label.configure(text=self.out_dir)
        self.status.configure(text=f"ที่เก็บรูป: {self.out_dir}")
        self.refresh_gallery()
        return True

    def on_pick_dir(self):
        start = self.out_dir if os.path.isdir(self.out_dir) else None
        d = filedialog.askdirectory(parent=self, initialdir=start,
                                    title="เลือกที่เก็บรูป", mustexist=True)
        if not d:
            return
        self.apply_out_dir(d)

    def on_use_typed_dir(self):
        d = self.out_entry.get().strip().strip('"')
        if not d:
            self.status.configure(text="วาง path โฟลเดอร์ก่อนแล้วกด ใช้")
            return
        if self.apply_out_dir(d):
            self.out_entry.delete(0, tk.END)

    def on_run(self):
        if self.orig is None:
            messagebox.showwarning("เตือน", "เปิดรูปก่อน")
            return
        if self.mask is None or self.mask.getbbox() is None:
            messagebox.showwarning("เตือน", "ระบายจุดที่ลบก่อน")
            return
        prompt = self.prompt.get("1.0", "end").strip()
        if not prompt:
            messagebox.showwarning("เตือน", "พิมพ์พื้นหลังที่อยากให้เติมก่อน")
            return
        steps = int(round(self.steps.get()))
        strength = round(float(self.strength.get()), 2)
        try:
            long_side = int(self.size.get())
        except ValueError:
            long_side = 512
        seed_txt = self.seed.get().strip()
        seed = int(seed_txt) if seed_txt.lstrip("-").isdigit() else None
        negative = self.negative.get("1.0", "end").strip()
        model = MODEL_IDS.get(self.model.get(), "sd-turbo")
        self.btn.configure(state="disabled")
        self.status.configure(text="กำลังลบวัตถุ...")
        self.progress.start()
        threading.Thread(target=self.work,
                         args=(prompt, steps, strength, seed, long_side, negative, model),
                         daemon=True).start()

    def work(self, prompt, steps, strength, seed, long_side, negative, model):
        try:
            os.makedirs(self.out_dir, exist_ok=True)
            img, used_seed = inpaint(self.orig, self.mask, prompt, steps=steps,
                                     strength=strength, seed=seed, negative=negative,
                                     model=model, long_side=long_side, feather=FEATHER)
            path = next_path(self.out_dir)
            img.save(path)
            self.after(0, self.show_result, img, path, used_seed)
        except Exception as e:  # noqa: BLE001
            self.after(0, self.show_error, str(e))

    def show_result(self, img, path, used_seed):
        self.result = img
        self.current_path = path
        self.view.set("ผลลัพธ์")
        self.refresh_canvas()
        self.img_name.configure(text=os.path.basename(path))
        self.status.configure(text=f"เสร็จ! {os.path.basename(path)} {img.size[0]}x{img.size[1]} (seed {used_seed})")
        self.seed.delete(0, tk.END)
        self.seed.insert(0, str(used_seed))
        self.btn.configure(state="normal")
        self.progress.stop()
        self.refresh_gallery()

    def show_error(self, msg):
        self.status.configure(text="เกิดข้อผิดพลาด")
        self.btn.configure(state="normal")
        self.progress.stop()
        messagebox.showerror("ผิดพลาด", msg[:500])

    def on_use_result(self):
        if self.result is None:
            self.status.configure(text="ยังไม่มีผลลัพธ์ให้ใช้")
            return
        self.orig = self.result.convert("RGB")
        self.mask = Image.new("L", self.orig.size, 0)
        self.result = None
        self.view.set("ต้นฉบับ")
        self.refresh_canvas()
        self.status.configure(text="ใช้ผลลัพธ์เป็นต้นฉบับแล้ว — ระบายต่อได้เลย")

    def view_image(self, path):
        self.load_input(path)

    def on_delete(self):
        if not self.current_path or not os.path.isfile(self.current_path):
            self.status.configure(text="ไม่มีไฟล์ให้ลบ")
            return
        name = os.path.basename(self.current_path)
        if not messagebox.askyesno("ยืนยัน", f"ลบ {name} ไปถังขยะ?"):
            return
        try:
            send2trash(self.current_path)
        except Exception as e:  # noqa: BLE001
            self.status.configure(text=f"ลบไม่ได้: {e}")
            return
        self.current_path = None
        self.status.configure(text=f"ลบ {name} แล้ว (กู้ได้จากถังขยะ)")
        self.refresh_gallery()

    def recent_files(self):
        try:
            return sorted((os.path.join(self.out_dir, f) for f in os.listdir(self.out_dir) if f.endswith(".png")),
                          key=os.path.getmtime, reverse=True)
        except FileNotFoundError:
            return []

    def refresh_gallery(self):
        self._gallery_token = getattr(self, "_gallery_token", 0) + 1
        threading.Thread(target=self._gallery_work,
                         args=(self.out_dir, self._gallery_token), daemon=True).start()

    def _gallery_work(self, out_dir, token):
        try:
            files = sorted((os.path.join(out_dir, f) for f in os.listdir(out_dir)
                            if f.endswith(".png")),
                           key=os.path.getmtime, reverse=True)[:GALLERY_LIMIT]
        except OSError:
            files = []
        thumbs = load_gallery_thumbs(files)
        self._gallery_pending = (thumbs, token)

    def _gallery_poll(self):
        pending = self._gallery_pending
        if pending is not None:
            self._gallery_pending = None
            self._gallery_done(*pending)
        self.after(100, self._gallery_poll)

    def _gallery_done(self, thumbs, token):
        if token != getattr(self, "_gallery_token", 0):
            return  # ผลจากรอบเก่า ทิ้งไป
        for w in self.gallery.winfo_children():
            w.destroy()
        self.thumb_refs = []
        if not thumbs:
            ctk.CTkLabel(self.gallery, text="ยังไม่มีรูป — เปิดรูปแล้วกดลบวัตถุ", font=BODY_FONT).pack(padx=8, pady=30)
            return
        for path, thumb in thumbs:
            cimg = ctk.CTkImage(light_image=thumb, dark_image=thumb, size=(thumb.size[0], thumb.size[1]))
            self.thumb_refs.append(cimg)
            ctk.CTkButton(self.gallery, image=cimg, text="", width=88, height=88,
                          fg_color="transparent", command=lambda p=path: self.view_image(p)).pack(
                              side="left", padx=4, pady=4)


if __name__ == "__main__":
    app = App()
    if "--smoke" in sys.argv:
        app.after(2500, app.destroy)
    app.mainloop()
