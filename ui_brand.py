"""Ceramic key surfaces and the four-point glint from the application icon."""

from functools import lru_cache

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainterPath


INDIGO = "#4C54CD"
INK = "#242424"
MUTED = "#666666"


@lru_cache(maxsize=1)
def _glint():
    path = QPainterPath()
    path.moveTo(0, -1)
    path.cubicTo(.17, -.34, .34, -.17, 1, 0)
    path.cubicTo(.34, .17, .17, .34, 0, 1)
    path.cubicTo(-.17, .34, -.34, .17, -1, 0)
    path.cubicTo(-.34, -.17, -.17, -.34, 0, -1)
    path.closeSubpath()
    return path


def draw_glint(painter, x, y, radius, color):
    painter.save()
    painter.translate(x, y)
    painter.scale(radius, radius)
    painter.fillPath(_glint(), QColor(color))
    painter.restore()


def draw_lit_key(painter, rect):
    painter.save()
    glaze = QLinearGradient(rect.topLeft(), rect.bottomRight())
    glaze.setColorAt(0, QColor("#838AFF"))
    glaze.setColorAt(1, QColor(INDIGO))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(glaze)
    radius = rect.width() * .29
    painter.drawRoundedRect(rect, radius, radius)
    draw_glint(painter, rect.center().x(), rect.center().y(),
               rect.width() * .32, "#FFFFFF")
    painter.restore()
