"""Create installer artwork using the same graphite and lime identity."""

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication


app = QApplication(sys.argv)
asset_dir = Path(__file__).resolve().parent
canvas = QPixmap(420, 840)
canvas.fill(QColor("#141915"))
painter = QPainter(canvas)
painter.setRenderHint(QPainter.RenderHint.Antialiasing)
painter.setPen(Qt.PenStyle.NoPen)
painter.setBrush(QColor("#1D241E"))
painter.drawRoundedRect(QRectF(30, 158, 360, 360), 36, 36)
painter.setPen(QPen(QColor("#303B31"), 1))
painter.setBrush(Qt.BrushStyle.NoBrush)
painter.drawRoundedRect(QRectF(30.5, 158.5, 359, 359), 36, 36)
icon = QPixmap(str(asset_dir / "ripple.png"))
painter.drawPixmap(QRectF(105, 233, 210, 210), icon, QRectF(icon.rect()))
pen = QPen(QColor("#C4EF70"), 5)
pen.setCapStyle(Qt.PenCapStyle.RoundCap)
painter.setPen(pen)
painter.drawLine(44, 744, 116, 744)
painter.end()
canvas.save(str(asset_dir / "installer-banner.png"))
