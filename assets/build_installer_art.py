"""Create installer artwork using the light workspace identity."""

import sys
from pathlib import Path

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QApplication


app = QApplication(sys.argv)
asset_dir = Path(__file__).resolve().parent
canvas = QPixmap(420, 840)
painter = QPainter(canvas)
painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
glaze = QLinearGradient(0, 0, 420, 840)
glaze.setColorAt(0, QColor("#FBFAFF"))
glaze.setColorAt(1, QColor("#D6D6FB"))
painter.fillRect(canvas.rect(), glaze)
icon = QPixmap(str(asset_dir / "app-icon.png"))
if icon.isNull():
    raise FileNotFoundError("Run build_icon.py before generating installer artwork")
painter.drawPixmap(QRectF(55, 255, 310, 310), icon, QRectF(icon.rect()))
painter.end()
canvas.save(str(asset_dir / "installer-banner.png"))
