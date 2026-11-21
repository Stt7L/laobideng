"""Export the app icon for Windows from the full-bleed artwork."""

from pathlib import Path
import struct
import sys

from PySide6.QtCore import QBuffer, QIODevice, QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QPainterPath


def build_icon():
    root = Path(__file__).resolve().parent
    artwork = QImage(str(root / "laobideng-app-icon.png"))
    if artwork.isNull() or artwork.width() != artwork.height():
        raise ValueError("App icon artwork must be a readable square image")

    canvas = QImage(512, 512, QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(Qt.GlobalColor.transparent)
    bounds = QRectF(8, 8, 496, 496)
    mask = QPainterPath()
    mask.addRoundedRect(bounds, 110, 110)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.setClipPath(mask)
    painter.drawImage(bounds, artwork)
    painter.end()
    if not canvas.save(str(root / "app-icon.png")):
        raise OSError("Could not save app-icon.png")

    # Store a pre-scaled image for each common Windows shell and tray size.
    sizes = (16, 20, 24, 32, 40, 48, 64, 128, 256)
    directory = bytearray(struct.pack("<HHH", 0, 1, len(sizes)))
    offset = len(directory) + 16 * len(sizes)
    frames = []
    for size in sizes:
        frame = canvas.scaled(size, size, mode=Qt.TransformationMode.SmoothTransformation)
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not frame.save(buffer, "PNG"):
            raise OSError(f"Could not encode the {size}px icon frame")
        encoded = bytes(buffer.data())
        buffer.close()
        extent = size % 256  # ICO uses zero for 256 pixels.
        directory.extend(struct.pack("<BBBBHHII", extent, extent, 0, 0, 1, 32,
                                     len(encoded), offset))
        frames.append(encoded)
        offset += len(encoded)
    (root / "app-icon.ico").write_bytes(directory + b"".join(frames))


if __name__ == "__main__":
    try:
        build_icon()
    except (OSError, ValueError) as error:
        sys.exit(str(error))
