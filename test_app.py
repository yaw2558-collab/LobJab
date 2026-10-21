"""เทส logic ฝั่งแอปที่ไม่ต้องเปิดหน้าต่าง (รัน: python test_app.py)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import apply_overlay, canvas_fit, event_to_image, next_paths


def test_canvas_fit_centers():
    assert canvas_fit(800, 600, 400, 400) == (0, 50, 400, 300)


def test_event_to_image_inside():
    assert event_to_image(200, 200, (0, 50, 400, 300), 800, 600) == (400, 300)


def test_event_to_image_outside():
    assert event_to_image(10, 10, (0, 50, 400, 300), 800, 600) is None


def test_apply_overlay_only_tints_mask():
    from PIL import Image
    disp = Image.new("RGB", (10, 10), (100, 100, 100))
    m = Image.new("L", (10, 10), 0)
    m.putpixel((3, 3), 255)
    out = apply_overlay(disp, m)
    assert out.getpixel((0, 0))[:3] == (100, 100, 100)
    assert out.getpixel((3, 3))[:3] != (100, 100, 100)


def test_next_paths_prefix():
    with tempfile.TemporaryDirectory() as td:
        open(os.path.join(td, "fix001.png"), "w").close()
        paths = next_paths(td, 2)
        assert [os.path.basename(p) for p in paths] == ["fix002.png", "fix003.png"]


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
