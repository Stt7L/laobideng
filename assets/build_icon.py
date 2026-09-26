"""Generate Windows and Tk icon assets from the simple ripple geometry."""

from pathlib import Path
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent
SCALE = 4
SIZE = 512
image = Image.new("RGBA", (SIZE * SCALE, SIZE * SCALE), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)


def box(rect):
    return tuple(round(value * SCALE) for value in rect)


draw.rounded_rectangle(box((8, 8, 504, 504)), radius=116 * SCALE,
                       fill="#202720")
for radius, width, color in ((190, 22, "#657D4B"),
                             (137, 24, "#9BC85F"),
                             (84, 24, "#D9F7A9")):
    draw.ellipse(box((256 - radius, 256 - radius,
                      256 + radius, 256 + radius)),
                 outline=color, width=width * SCALE)
draw.rounded_rectangle(box((218, 218, 294, 294)), radius=19 * SCALE,
                       fill="#C4EF70")

image = image.resize((SIZE, SIZE), Image.Resampling.LANCZOS)
image.save(ROOT / "ripple.png")
image.save(ROOT / "ripple.ico", sizes=[(16, 16), (24, 24), (32, 32),
                                      (48, 48), (64, 64), (128, 128),
                                      (256, 256)])
