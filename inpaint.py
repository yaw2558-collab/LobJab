"""Core image inpainting: เรียก sd-cli.exe (stable-diffusion.cpp + Vulkan, ตัวเดียวกับที่ Amuse/GenJab ใช้)
   รับรูปต้นฉบับ + mask (ขาว = ลบแล้วให้ AI เติมใหม่, ดำ = เก็บของเดิม) — ลบวัตถุออกจากรูปบนการ์ดจอ AMD"""
import argparse
import glob
import os
import random
import subprocess
import sys
import tempfile


def app_dir():
    """โฟลเดอร์ที่แอปรันอยู่ — exe ที่บิลด์แล้วใช้ข้างตัว exe, รันจากซอร์สใช้ข้างไฟล์นี้."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


AMUSE_SD_CLI = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Amuse",
                            "RuntimeStableDiffusionCpp", "vulkan", "sd-cli.exe")
LOCAL_MODELS = os.path.join(app_dir(), "models")


def resolve_sd_cli():
    """หา sd-cli.exe — env LOBJAB_SDCLI (หรือ TEXT2IMAGE_SDCLI เดิม) ก่อน, ตามด้วย runtime/ ที่ห่อมากับแอป, สุดท้ายของ Amuse."""
    for key in ("LOBJAB_SDCLI", "TEXT2IMAGE_SDCLI"):
        env = os.environ.get(key, "")
        if env:
            return env
    bundled = os.path.join(app_dir(), "runtime", "sd-cli.exe")
    if os.path.isfile(bundled):
        return bundled
    return AMUSE_SD_CLI


SD_CLI = resolve_sd_cli()

MODEL_DEFAULTS = {"sd-turbo": {"steps": 4, "guidance": 1.0, "strength": 1.0},
                  "sdxl-turbo": {"steps": 4, "guidance": 1.0, "strength": 1.0},
                  "sd15-inpaint": {"steps": 25, "guidance": 7.0, "strength": 1.0}}


def resolve_model(name="sd-turbo"):
    """คืน path ไฟล์โมเดล — รองรับ sd-turbo, sdxl-turbo (ค้น HF cache / models/ / env แบบเดียวกับ GenJab)."""
    if name == "sd-turbo":
        env = os.environ.get("LOBJAB_MODEL", "") or os.environ.get("TEXT2IMAGE_MODEL", "")
        if env and os.path.isfile(env):
            return env
        hits = glob.glob(os.path.expanduser(
            "~/.cache/huggingface/hub/models--stabilityai--sd-turbo/snapshots/*/sd_turbo.safetensors"))
        hits += glob.glob(os.path.join(LOCAL_MODELS, "sd_turbo.safetensors"))
        hits += glob.glob(os.path.join(LOCAL_MODELS, "sd-turbo*.safetensors"))
        if hits:
            return hits[0]
        raise FileNotFoundError(
            "ไม่พบโมเดล sd_turbo.safetensors — วางไฟล์ไว้ในโฟลเดอร์ models/ "
            "(ข้างโปรแกรม) หรือตั้ง path เองผ่าน env LOBJAB_MODEL")
    if name == "sdxl-turbo":
        env = os.environ.get("LOBJAB_SDXL_TURBO", "") or os.environ.get("TEXT2IMAGE_SDXL_TURBO", "")
        if env and os.path.isfile(env):
            return env
        hits = glob.glob(os.path.expanduser(
            "~/.cache/huggingface/hub/models--stabilityai--sdxl-turbo/snapshots/*/sd_xl_turbo_*.safetensors"))
        hits += glob.glob(os.path.join(LOCAL_MODELS, "sdxl-turbo*.safetensors"))
        hits += glob.glob(os.path.join(LOCAL_MODELS, "sd_xl_turbo_*.safetensors"))
        if hits:
            return hits[0]
        raise FileNotFoundError(
            "ไม่พบโมเดล SDXL-Turbo — โหลดไฟล์ sd_xl_turbo_1.0_fp16.safetensors "
            "จาก https://huggingface.co/stabilityai/sdxl-turbo มาไว้ในโฟลเดอร์ models/ "
            "หรือตั้ง path เองผ่าน env LOBJAB_SDXL_TURBO")
    if name == "sd15-inpaint":
        env = os.environ.get("LOBJAB_SD15_INPAINT", "")
        if env and os.path.isfile(env):
            return env
        hits = glob.glob(os.path.join(LOCAL_MODELS, "sd-v1-5-inpainting.safetensors"))
        hits += glob.glob(os.path.join(LOCAL_MODELS, "*inpaint*.safetensors"))
        if hits:
            return hits[0]
        raise FileNotFoundError(
            "ไม่พบโมเดล sd-v1-5-inpainting.safetensors — โหลดจาก "
            "https://huggingface.co/webui/stable-diffusion-inpainting มาไว้ในโฟลเดอร์ models/ "
            "หรือตั้ง path เองผ่าน env LOBJAB_SD15_INPAINT")
    raise ValueError(f"โมเดลไม่รู้จัก: {name} (มี: sd-turbo, sdxl-turbo, sd15-inpaint)")


def working_size(w, h, long_side=512):
    """ย่อให้ด้านยาว = long_side คงสัดส่วน แล้วปัดแต่ละด้านให้ลงตัวกับ 64 (ที่ sd-cli ต้องการ)."""
    if w <= 0 or h <= 0:
        raise ValueError(f"ขนาดรูปต้อง > 0 (ได้ {w}x{h})")
    if long_side <= 0:
        raise ValueError(f"long_side ต้อง > 0 (ได้ {long_side})")
    scale = long_side / max(w, h)
    nw = max(64, int(round(w * scale / 64)) * 64)
    nh = max(64, int(round(h * scale / 64)) * 64)
    return (nw, nh)


def dilate_mask(mask, px):
    """ขยายบริเวณขาวของ mask ออกไป px พิกเซล (MaxFilter) — 0 = คืนเดิม."""
    if px <= 0:
        return mask
    from PIL import ImageFilter
    return mask.filter(ImageFilter.MaxFilter(2 * int(px) + 1))


def inpaint(image, mask, prompt, steps=4, guidance=1.0, strength=1.0, seed=None,
            negative="", model="sd-turbo", long_side=512, feather=8, dilate=5):
    """ลบส่วนขาวใน mask แล้วให้ AI เติมใหม่ คืน (PIL Image, seed ที่ใช้จริง).

    image/mask ต้องขนาดเท่ากัน (mask โหมดอะไรก็ได้ — แปลงเป็นขาว/ดำเอง);
    ทำงานที่ขนาดย่อ (ด้านยาว long_side) แล้วคืนรูปขนาดนั้น;
    feather = เบลอขอบ mask (พิกเซลที่ขนาดทำงาน) ให้รอยต่อเนียนขึ้น (0 = ไม่เบลอ);
    dilate = ขยาย mask ออกไปก่อน (พิกเซลที่ขนาดทำงาน) ให้คลุมขอบวัตถุ (0 = ไม่ขยาย)."""
    from PIL import Image, ImageFilter
    if image.size != mask.size:
        raise ValueError(f"รูปกับ mask ต้องขนาดเท่ากัน (ได้ {image.size} กับ {mask.size})")
    if not os.path.isfile(SD_CLI):
        raise FileNotFoundError(f"ไม่พบ sd-cli.exe ที่ {SD_CLI} (ต้องลงแอป Amuse ก่อน)")
    if seed is None:
        seed = random.randint(0, 2**31 - 1)
    mfile = resolve_model(model)
    w, h = working_size(*image.size, long_side)
    img_r = image.convert("RGB").resize((w, h), Image.BILINEAR)
    mask_r = mask.convert("L").resize((w, h), Image.NEAREST)
    mask_r = dilate_mask(mask_r, dilate)
    if feather > 0:
        mask_r = mask_r.filter(ImageFilter.GaussianBlur(feather))
    with tempfile.TemporaryDirectory() as td:
        init_p = os.path.join(td, "init.png")
        mask_p = os.path.join(td, "mask.png")
        out = os.path.join(td, "out.png")
        img_r.save(init_p)
        mask_r.save(mask_p)
        cmd = [SD_CLI, "-m", mfile, "--init-img", init_p, "--mask", mask_p,
               "-p", prompt, "-o", out, "-W", str(w), "-H", str(h),
               "--steps", str(steps), "--cfg-scale", str(guidance),
               "--strength", str(strength), "--seed", str(seed)]
        if negative:
            cmd += ["-n", negative]
        p = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
        if p.returncode != 0 or not os.path.isfile(out):
            raise RuntimeError(f"sd-cli ล้มเหลว:\n{(p.stderr or p.stdout)[-800:]}")
        return Image.open(out).convert("RGB"), seed


def main():
    ap = argparse.ArgumentParser(description="ลบวัตถุออกจากรูป (sd.cpp inpaint + SD-Turbo)")
    ap.add_argument("image", help="รูปต้นฉบับ")
    ap.add_argument("mask", help="รูป mask ขนาดเท่ากัน (ขาว = ลบแล้วเติมใหม่, ดำ = เก็บเดิม)")
    ap.add_argument("prompt", help="บอกพื้นหลังที่อยากให้เติม (ภาษาอังกฤษ)")
    ap.add_argument("-o", "--output", default="out/fixed.png")
    ap.add_argument("--steps", type=int, default=4)
    ap.add_argument("--strength", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--size", type=int, default=512, help="ด้านยาวตอนประมวลผล")
    ap.add_argument("--cfg", type=float, default=1.0)
    ap.add_argument("--feather", type=float, default=8, help="เบลอขอบ mask (0 = ไม่เบลอ)")
    ap.add_argument("--dilate", type=int, default=5, help="ขยาย mask ก่อนเติม (0 = ไม่ขยาย)")
    ap.add_argument("-n", "--negative", default="")
    ap.add_argument("--model", default="sd-turbo", choices=["sd-turbo", "sdxl-turbo", "sd15-inpaint"])
    args = ap.parse_args()
    from PIL import Image
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    img, seed = inpaint(Image.open(args.image), Image.open(args.mask), args.prompt,
                        steps=args.steps, strength=args.strength, seed=args.seed,
                        guidance=args.cfg, negative=args.negative,
                        model=args.model, long_side=args.size, feather=args.feather,
                        dilate=args.dilate)
    img.save(args.output)
    print("saved:", args.output, "seed:", seed)


if __name__ == "__main__":
    main()
