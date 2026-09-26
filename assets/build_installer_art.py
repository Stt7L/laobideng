"""Create a quiet graphite and lime banner for the Inno Setup wizard."""

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication


app = QApplication(sys.argv)
canvas = QPixmap(420, 840)
canvas.fill(QColor("#141915"))
painter = QPainter(canvas)
painter.setRenderHint(QPainter.RenderHint.Antialiasing)
painter.setPen(QPen(QColor("#33412F"), 1))
for offset in (0, 52, 104):
    painter.drawLine(0, 522 + offset, 420, 522 + offset)
painter.setPen(QPen(QColor("#C4EF70"), 13))
for diameter in (80, 132, 184):
    painter.drawEllipse(QRectF((420 - diameter) / 2, 210 - diameter / 2,
                               diameter, diameter))
painter.setBrush(QColor("#C4EF70"))
painter.setPen(Qt.PenStyle.NoPen)
painter.drawEllipse(QRectF(201, 201, 18, 18))
painter.setPen(QPen(QColor("#C4EF70"), 5))
painter.drawLine(48, 739, 136, 739)
painter.end()
canvas.save(str(Path(__file__).with_name("installer-banner.png")))
