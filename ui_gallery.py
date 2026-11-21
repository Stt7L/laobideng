"""Motion for the lighting categories and the color inspiration strip."""

from PySide6.QtCore import QElapsedTimer, QEvent, QEasingCurve, QObject, QPoint, QPointF, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QFrame, QPushButton, QSizePolicy, QWidget
from shiboken6 import isValid

from ui_brand import INDIGO, INK, MUTED, draw_glint
from ui_controls import motion_duration


class RailHint(QWidget):
    """An in-window hint with an antialiased edge."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._text = ""
        self._opacity = 1.0
        self._fade = QVariantAnimation(self)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.setDuration(motion_duration(170))
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.valueChanged.connect(self._set_opacity)
        self._expiry = QTimer(self, singleShot=True, interval=2800)
        self._expiry.timeout.connect(self.hide)

    def _set_opacity(self, value):
        self._opacity = value
        self.update()

    def show_below(self, button, text):
        self._text = text
        font = button.font()
        font.setPixelSize(13)
        font.setStyleStrategy(font.StyleStrategy.PreferAntialias | font.StyleStrategy.NoSubpixelAntialias)
        self.setFont(font)
        shell = self.parentWidget()
        metrics = QFontMetrics(font)
        width = max(80, min(metrics.horizontalAdvance(text) + 52, shell.width() - 24))
        lines = metrics.boundingRect(0, 0, width - 46, 200, Qt.TextFlag.TextWordWrap, text)
        self.resize(width, max(52, lines.height() + 31))
        anchor = button.mapTo(shell, QPoint(button.width() // 2, button.height()))
        x = max(12, min(anchor.x() - self.width() // 2, shell.width() - self.width() - 12))
        y = anchor.y() - button.height() - self.height() + 7
        if y < 8:
            y = anchor.y()
        self.move(x, max(8, min(y, shell.height() - self.height() - 6)))
        self._fade.stop()
        self._fade.start()
        self._expiry.start()
        self.show()
        self.raise_()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        painter.setOpacity(self._opacity)
        panel = QRectF(self.rect()).adjusted(8, 5, -8, -10)
        painter.setPen(Qt.PenStyle.NoPen)
        for spread in range(7, 0, -1):
            painter.setBrush(QColor(30, 32, 45, 3 if spread > 3 else 5))
            painter.drawRoundedRect(panel.translated(0, 3).adjusted(-spread, -spread, spread, spread),
                                    11 + spread, 11 + spread)
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawRoundedRect(panel, 11, 11)
        painter.setPen(QColor(INK))
        painter.drawText(panel.adjusted(12, 0, -12, 0),
                         Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self._text)


class TooltipFilter(QObject):
    """Route widget hints through one painter, including secondary dialogs."""

    def __init__(self, parent):
        super().__init__(parent)
        self._active = None
        self._anchor = None

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QEvent.Type.ToolTip and isinstance(watched, QWidget) and watched.toolTip():
            # QFileDialog's OS chrome and the Windows tray are owned by Windows.
            window = watched.window()
            hint = getattr(window, "_surface_hint", None)
            if hint is None:
                hint = window._surface_hint = RailHint(window)
            self._hide()
            self._active, self._anchor = hint, watched
            hint.show_below(watched, watched.toolTip())
            return True
        if self._active is not None and (
                kind in (QEvent.Type.MouseButtonPress, QEvent.Type.Wheel,
                         QEvent.Type.KeyPress, QEvent.Type.WindowDeactivate) or
                watched is self._anchor and kind in (QEvent.Type.Leave, QEvent.Type.Hide,
                                                      QEvent.Type.Move, QEvent.Type.Resize)):
            self._hide()
        return False

    def _hide(self):
        if self._active is not None and isValid(self._active):
            self._active.hide()
        self._active = self._anchor = None


class CategoryRail(QFrame):
    """One moving selection surface under the existing accessible buttons."""

    def __init__(self, travel_y=False):
        super().__init__()
        self._buttons = []
        self._target = None
        self._origin = None
        self._pressed = None
        self._dragging = False
        self._travel_y = travel_y
        self._indicator = QFrame(self)
        self._indicator.setStyleSheet("background: white; border: none; border-radius: 12px")
        self._indicator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._indicator.hide()
        self._motion = QVariantAnimation(self)
        ease = QEasingCurve(QEasingCurve.Type.OutBack)
        ease.setOvershoot(.65)
        self._motion.setEasingCurve(ease)
        self._motion.valueChanged.connect(self._indicator.setGeometry)
        self._motion.finished.connect(self._settle_indicator)

    def _settle_indicator(self):
        self.select(self._target, animate=False)

    def add_button(self, button):
        self._buttons.append(button)
        button.installEventFilter(self)

    def select(self, button, animate=True):
        if animate and button is self._target and self._motion.state() == QVariantAnimation.State.Running:
            return
        self._target = button
        if self._dragging:
            return
        self._motion.stop()
        if button is None:
            self._indicator.hide()
            return
        end = button.geometry()
        duration = motion_duration(290) if animate and self._indicator.isVisible() else 0
        if duration and self._indicator.geometry() != end:
            self._motion.setDuration(duration)
            self._motion.setStartValue(self._indicator.geometry())
            self._motion.setEndValue(end)
            self._motion.start()
        else:
            self._indicator.setGeometry(end)
        self._indicator.show()
        self._indicator.lower()

    def event(self, event):
        result = super().event(event)
        if event.type() in (QEvent.Type.Resize, QEvent.Type.LayoutRequest, QEvent.Type.Show):
            if self._target and self._motion.state() != QVariantAnimation.State.Running:
                self._settle_indicator()
        return result

    def eventFilter(self, button, event):
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.globalPosition().toPoint()
            self._pressed = button
        elif kind == QEvent.Type.MouseMove and self._pressed is button:
            offset = event.globalPosition().toPoint() - self._origin
            if self._dragging or offset.manhattanLength() >= QApplication.startDragDistance():
                self._dragging = True
                self._motion.stop()
                button.setDown(False)
                rect = (self._target or button).geometry()
                rect.translate(offset.x(), offset.y() if self._travel_y else 0)
                rect.moveLeft(max(4, min(rect.left(), self.width() - rect.width() - 4)))
                rect.moveTop(max(4, min(rect.top(), self.height() - rect.height() - 4)))
                self._indicator.setGeometry(rect)
                self._indicator.show()
                self._indicator.lower()
                return True
        elif kind == QEvent.Type.MouseButtonRelease and self._pressed is button:
            self._pressed = None
            if self._dragging:
                self._dragging = False
                center = self._indicator.geometry().center()
                nearest = min(self._buttons,
                              key=lambda item: (item.geometry().center() - center).manhattanLength())
                if nearest is not self._target:
                    nearest.click()
                else:
                    self.select(nearest)
                return True
        elif kind in (QEvent.Type.UngrabMouse, QEvent.Type.Hide) and self._pressed is button:
            self._pressed = None
            if self._dragging:
                self._dragging = False
                self.select(self._target)
        return super().eventFilter(button, event)


class PaletteCard(QPushButton):
    WIDTH = 150
    HEIGHT = 196

    def __init__(self, name="", base=(255, 255, 255), accent=None, codes=(), parent=None):
        super().__init__(name, parent)
        self._colors = (QColor(*base), QColor(*accent) if accent is not None else None)
        self._codes = codes
        self.entrance_opacity = 1.
        self.setCheckable(True)
        self.setAccessibleName(f"套用{name}配色")
        self.setAccessibleDescription(" / ".join(codes))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setStyleSheet(f"min-height: {self.HEIGHT}px; padding: 0; border: none;")

    def set_sample(self, label, rgb, code):
        self.setText(label)
        self._colors = (QColor(*rgb), None)
        self._codes = (code,)
        self.setAccessibleDescription(code)
        self.update()

    @classmethod
    def swatch_rect(cls):
        return QRectF(8, 8, cls.WIDTH - 16, cls.WIDTH - 16)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        painter.setOpacity(self.entrance_opacity)
        painter.setPen(QPen(QColor("#CECED4" if self.underMouse() else "#E3E3E6"), 1))
        painter.setBrush(QColor("#FFFFFF"))
        panel = QRectF(self.rect()).adjusted(1, 1 + int(self.isDown()), -1, -1)
        painter.drawRoundedRect(panel, 13, 13)
        swatch = self.swatch_rect().translated(0, int(self.isDown()))
        fill = self._colors[0]
        if self._colors[1] is not None:
            fill = QLinearGradient(swatch.topLeft(), swatch.topRight())
            fill.setColorAt(0, self._colors[0])
            fill.setColorAt(.4999, self._colors[0])
            fill.setColorAt(.5, self._colors[1])
            fill.setColorAt(1, self._colors[1])
        painter.setPen(QPen(QColor(30, 30, 30, 23), 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(swatch, 6, 6)
        if self.hasFocus():
            painter.setPen(QPen(QColor("#686868"), 1.4))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(panel.adjusted(1, 1, -1, -1), 12, 12)
        font = self.font()
        font.setPixelSize(15)
        font.setWeight(font.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(INK))
        painter.drawText(12, self.height() - 30, self.text())
        font.setPixelSize(11)
        font.setWeight(font.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor(MUTED))
        painter.drawText(12, self.height() - 13, "  /  ".join(self._codes))
        if self.isChecked():
            draw_glint(painter, self.width() - 18, self.height() - 31, 7, INDIGO)


class PaletteArrow(QPushButton):
    SIZE = 36

    def __init__(self, direction, label, parent):
        super().__init__(parent)
        self._direction = direction
        self.entrance_opacity = 1.
        self.setAccessibleName(label)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("min-height: 0; padding: 0; border: none;")
        self.setFixedSize(self.SIZE, self.SIZE)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self.entrance_opacity)
        painter.setPen(QPen(QColor("#88888F" if self.hasFocus() else "#E4E4E8"), 1))
        painter.setBrush(QColor("#ECECF0" if self.isDown() else
                                "#F4F4F6" if self.underMouse() else "#FFFFFF"))
        painter.drawEllipse(QRectF(self.rect()).adjusted(.75, .75, -.75, -.75))
        center = QRectF(self.rect()).center()
        # Mirror the same vector around the disc center, independent of the font.
        tail_x = center.x() - self._direction * 2
        tip_x = center.x() + self._direction * 2
        path = QPainterPath(QPointF(tail_x, center.y() - 4))
        path.lineTo(tip_x, center.y())
        path.lineTo(tail_x, center.y() + 4)
        painter.setPen(QPen(QColor(INK), 1.6, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(path)


class PaletteMarquee(QWidget):
    """Loop real buttons so clicking, tab focus and accessibility stay native."""

    CARD_GAP = 20
    ARROW_GUTTER = PaletteArrow.SIZE + 16

    def __init__(self, parent, direction=1):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(PaletteCard.HEIGHT)
        self.track = QWidget(self)
        self.cards = []
        self._offset = 0.0
        self._direction = direction
        self._stride = PaletteCard.WIDTH + self.CARD_GAP
        self._keyboard_card = None
        self._clock = QElapsedTimer()
        self._hold = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._advance)
        self._manual = QVariantAnimation(self)
        self._manual.setDuration(motion_duration(280))
        self._manual.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._manual.valueChanged.connect(self._set_offset)
        self._entrance = QVariantAnimation(self)
        self._entrance.setDuration(motion_duration(290))
        self._entrance.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._entrance.setStartValue(0.)
        self._entrance.setEndValue(1.)
        self._entrance.valueChanged.connect(self._fade_in)
        self.previous = PaletteArrow(-1, "上一张配色", self)
        self.following = PaletteArrow(1, "下一张配色", self)
        self.previous.clicked.connect(lambda: self._step(-1))
        self.following.clicked.connect(lambda: self._step(1))

    def add_card(self, card):
        self.cards.append(card)
        card.installEventFilter(self)

    def _step(self, direction):
        self._manual.stop()
        self._manual.setStartValue(self._offset)
        self._manual.setEndValue(self._offset + direction * self._stride)
        self._manual.start()

    def _set_offset(self, offset):
        self._offset = offset % (len(self.cards) * self._stride)
        self._arrange()

    def _advance(self):
        elapsed = self._clock.nsecsElapsed() / 1_000_000_000
        self._clock.restart()
        if (self.parentWidget().underMouse() or self._keyboard_card is not None or self.visibleRegion().isEmpty()
                or self._hold.isValid() and not self._hold.hasExpired(1400)
                or self._manual.state() == QVariantAnimation.State.Running):
            return
        self._set_offset(self._offset + min(.05, elapsed) * 66 * self._direction)

    def reveal_card(self, card):
        self._manual.stop()
        self._hold.start()
        self._set_offset(self.cards.index(card) * self._stride - 40)

    def _arrange(self):
        width = PaletteCard.WIDTH
        period = len(self.cards) * self._stride
        for index, card in enumerate(self.cards):
            x = (index * self._stride - self._offset + width) % period - width
            card.move(round(x), 0)

    def reveal(self):
        if self._entrance.duration():
            self._entrance.stop()
            self._fade_in(0.)
            self._entrance.start()

    def _fade_in(self, progress):
        opacity = .2 + progress * .8
        for button in (*self.cards, self.previous, self.following):
            button.entrance_opacity = opacity
            button.update()
        offset = round(10 * (1 - progress))
        self.track.move(self.ARROW_GUTTER, offset)
        self._position_arrows()

    def _position_arrows(self):
        # Lock both controls to the swatch center during the entry animation too.
        center_y = self.track.y() + PaletteCard.swatch_rect().center().y()
        arrow_y = round(center_y - PaletteArrow.SIZE / 2)
        self.previous.move(1, arrow_y)
        self.following.move(self.width() - self.following.width() - 1, arrow_y)

    def resizeEvent(self, event):
        self.track.setGeometry(self.ARROW_GUTTER, self.track.y(),
                               max(1, self.width() - 2 * self.ARROW_GUTTER), self.height())
        self._position_arrows()
        super().resizeEvent(event)

    def showEvent(self, event):
        self._arrange()
        if motion_duration(16):
            self._clock.start()
            self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self._timer.stop()
        self._manual.stop()
        self._entrance.stop()
        self._fade_in(1.)
        super().hideEvent(event)

    def eventFilter(self, card, event):
        if event.type() == QEvent.Type.FocusIn and event.reason() not in (
                Qt.FocusReason.MouseFocusReason, Qt.FocusReason.ActiveWindowFocusReason):
            self._keyboard_card = card
            self._manual.stop()
            if card.x() < 0 or card.geometry().right() > self.track.width():
                self._offset = self.cards.index(card) * self._stride - 41
                self._arrange()
        elif event.type() == QEvent.Type.FocusOut and self._keyboard_card is card:
            self._keyboard_card = None
        return super().eventFilter(card, event)
