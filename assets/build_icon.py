"""Build the compact key-and-light identity for window, tray and installer."""

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication


app = QApplication(sys.argv)
root = Path(__file__).resolve().parent
canvas = QPixmap(512, 512)
canvas.fill(Qt.GlobalColor.transparent)
painter = QPainter(canvas)
painter.setRenderHint(QPainter.RenderHint.Antialiasing)
painter.setPen(Qt.PenStyle.NoPen)
painter.setBrush(QColor("#202720"))
painter.drawRoundedRect(QRectF(8, 8, 496, 496), 116, 116)
for color, width, points in (
    ("#6A8B51", 17, ((287, 94), (431, 147), (431, 365), (287, 418))),
    ("#AAD77A", 20, ((259, 160), (343, 190), (343, 322), (259, 352))),
):
    path = QPainterPath()
    path.moveTo(*points[0])
    path.cubicTo(*points[1], *points[2], *points[3])
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(path)
painter.setPen(Qt.PenStyle.NoPen)
painter.setBrush(QColor("#C4EF70"))
painter.drawRoundedRect(QRectF(147, 193, 126, 126), 33, 33)
painter.setBrush(QColor("#E8F9CD"))
painter.drawRoundedRect(QRectF(165, 208, 90, 18), 9, 9)
painter.end()
canvas.save(str(root / "ripple.png"))
canvas.scaled(256, 256, Qt.AspectRatioMode.IgnoreAspectRatio,
              Qt.TransformationMode.SmoothTransformation).save(str(root / "ripple.ico"))
