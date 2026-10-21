"""เทส logic ฝั่ง inpaint ที่ไม่ต้องใช้ GPU (รัน: python test_inpaint.py)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inpaint


def test_working_size_square():
    assert inpaint.working_size(800, 800, 512) == (512, 512)


def test_working_size_keeps_ratio_and_64():
    assert inpaint.working_size(1600, 900, 512) == (512, 256)


def test_working_size_rejects_bad():
    for bad in [(0, 100), (100, -5)]:
        try:
            inpaint.working_size(*bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"ควรโยน ValueError: {bad}")


def test_inpaint_rejects_size_mismatch():
    from PIL import Image
    try:
        inpaint.inpaint(Image.new("RGB", (64, 64)), Image.new("L", (32, 32)), "sky")
    except ValueError as e:
        assert "ขนาดเท่ากัน" in str(e)
    else:
        raise AssertionError("mask คนละขนาดต้องโยน ValueError")


def test_inpaint_missing_sd_cli():
    from PIL import Image
    old = inpaint.SD_CLI
    inpaint.SD_CLI = r"C:\nope\sd-cli.exe"
    try:
        inpaint.inpaint(Image.new("RGB", (64, 64)), Image.new("L", (64, 64)), "sky")
    except FileNotFoundError as e:
        assert "sd-cli" in str(e)
    else:
        raise AssertionError("ต้องโยน FileNotFoundError")
    finally:
        inpaint.SD_CLI = old


def main():
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
            n += 1
    print(f"{n} passed")


if __name__ == "__main__":
    main()
