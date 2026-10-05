"""Made-up images and clips for the media tests: drawn with PIL, clips cut with ffmpeg. Names are neutral on purpose."""
import os
import shutil
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont


def _font(n):
    for f in ("/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.exists(f):
            return ImageFont.truetype(f, n)
    return ImageFont.load_default()


def _img(path, draw_fn, size=(448, 448), bg="white"):
    im = Image.new("RGB", size, bg)
    draw_fn(ImageDraw.Draw(im))
    im.save(path)


def _clip(path, frame_fn, n=48, size=224):
    d = tempfile.mkdtemp()  # frames stay out of the connected folder
    for t in range(n):
        im = Image.new("RGB", (size, size), "white")
        frame_fn(ImageDraw.Draw(im), t, n, size)
        im.save(f"{d}/f{t:04d}.png")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "24", "-i", f"{d}/f%04d.png", "-pix_fmt", "yuv420p", path], check=True)
    shutil.rmtree(d)


def make(dirpath):
    """Returns {role: path}. Roles: red_triangle, blue_circles, stop_sign (images); red_square_moving, blue_screen (clips)."""
    os.makedirs(dirpath, exist_ok=True)
    p = lambda n: os.path.join(dirpath, n)
    _img(p("img_a.png"), lambda d: d.polygon([(224, 60), (60, 380), (388, 380)], fill="red"))
    _img(p("img_b.jpg"), lambda d: [d.ellipse([40 + i * 100, 150, 110 + i * 100, 220], fill="blue") for i in range(4)])
    _img(p("img_c.png"), lambda d: d.text((30, 80), "STOP", fill="black", font=_font(90)), size=(448, 240))
    _clip(p("clip_a.mp4"), lambda d, t, n, s: d.rectangle([10 + int(t * (s - 60) / n), 90, 50 + int(t * (s - 60) / n), 130], fill="red"))
    _clip(p("clip_b.mov"), lambda d, t, n, s: d.rectangle([0, 0, s, s], fill="blue"))
    return {"red_triangle": p("img_a.png"), "blue_circles": p("img_b.jpg"), "stop_sign": p("img_c.png"),
            "red_square_moving": p("clip_a.mp4"), "blue_screen": p("clip_b.mov")}
