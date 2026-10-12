"""Neutral, rounded combo boxes with a custom popup and the Qt item API.

SurfaceComboBox is a drop-in QComboBox for the non-editable selectors in the
workbench. Items, roles, models and public selection signals remain Qt's own;
only the closed surface and the popup are drawn here.
"""

from PySide6.QtCore import QEasingCurve, QPoint, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QComboBox, QListView, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget

from ui_controls import motion_duration


class _ChoiceDelegate(QStyledItemDelegate):
    ROW_HEIGHT = 36

    def __init__(self, combo, parent):
        super().__init__(parent)
        self.combo = combo

    def sizeHint(self, option, index):
        return QSize(140, self.ROW_HEIGHT)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        row = QRectF(option.rect).adjusted(2, 1, -2, -1)
        enabled = bool(index.flags() & Qt.ItemFlag.ItemIsEnabled)
        hovered = bool(option.state & (QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver))
        chosen = index.row() == self.combo.currentIndex()
        painter.setPen(Qt.PenStyle.NoPen)
        if hovered and enabled:
            painter.setBrush(QColor("#ECECEE"))
            painter.drawRoundedRect(row, 11, 11)
        elif chosen:
            painter.setBrush(QColor("#F3F3F4"))
            painter.drawRoundedRect(row, 11, 11)

        painter.setFont(option.font)
        painter.setPen(QColor("#1D1D1F" if enabled else "#A0A0A4"))
        text_rect = row.adjusted(11, 0, -32, 0)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if icon is not None and hasattr(icon, "isNull") and not icon.isNull():
            icon.paint(painter, int(text_rect.left()), int(row.center().y() - 8), 16, 16)
            text_rect.setLeft(text_rect.left() + 25)
        text = option.fontMetrics.elidedText(str(index.data(Qt.ItemDataRole.DisplayRole) or ""),
                                            Qt.TextElideMode.ElideRight, int(text_rect.width()))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        if chosen:
            check = QPainterPath()
            x, y = row.right() - 17, row.center().y()
            check.moveTo(x - 4, y)
            check.lineTo(x - 1, y + 3)
            check.lineTo(x + 5, y - 4)
            painter.setPen(QPen(QColor("#333336" if enabled else "#A0A0A4"), 1.7,
                                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawPath(check)
        painter.restore()


class _ChoiceList(QListView):
    def __init__(self, popup):
        super().__init__(popup)
        self.popup = popup
        self.setMouseTracking(True)
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setFrameShape(QListView.Shape.NoFrame)
        self.setUniformItemSizes(True)
        self.setSpacing(0)
        self.setStyleSheet("""
            QListView { background: transparent; border: none; outline: none; padding: 0; }
            QScrollBar:vertical { background: transparent; width: 7px; margin: 5px 1px; }
            QScrollBar::handle:vertical { background: #C9C9CC; border-radius: 3px; min-height: 24px; }
            QScrollBar::handle:vertical:hover { background: #A8A8AC; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
        """)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.popup.commit(self.currentIndex())
            event.accept()
        elif event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_F4):
            self.popup.combo.hidePopup()
            event.accept()
        elif event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            combo = self.popup.combo
            combo.hidePopup()
            combo.focusNextPrevChild(event.key() == Qt.Key.Key_Tab)
            event.accept()
        else:
            super().keyPressEvent(event)


class _ChoicePopup(QWidget):
    SHADOW_LEFT = 16
    SHADOW_TOP = 12
    SHADOW_RIGHT = 16
    SHADOW_BOTTOM = 20
    PANEL_PADDING = 6

    def __init__(self, combo):
        super().__init__(combo, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.NoDropShadowWindowHint)
        self.combo = combo
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay)
        self.setObjectName("surfaceChoicePopup")
        self._restore_focus = False
        self._selection_model = None
        self.list = _ChoiceList(self)
        self.list.setItemDelegate(_ChoiceDelegate(combo, self.list))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(self.SHADOW_LEFT + self.PANEL_PADDING,
                                  self.SHADOW_TOP + self.PANEL_PADDING,
                                  self.SHADOW_RIGHT + self.PANEL_PADDING,
                                  self.SHADOW_BOTTOM + self.PANEL_PADDING)
        layout.setSpacing(0)
        layout.addWidget(self.list)
        self.list.clicked.connect(self.commit)

    def panel_rect(self):
        return QRectF(self.rect()).adjusted(self.SHADOW_LEFT, self.SHADOW_TOP,
                                           -self.SHADOW_RIGHT, -self.SHADOW_BOTTOM)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        panel = self.panel_rect()
        # Layered, low-alpha contours keep the popup shadow independent of the
        # opaque main window and of expensive nested graphics effects.
        shadow = panel.translated(0, 4)
        for spread in range(12, 0, -1):
            painter.setBrush(QColor(20, 20, 24, 2 if spread > 5 else 3))
            painter.drawRoundedRect(shadow.adjusted(-spread, -spread, spread, spread),
                                    16 + spread, 16 + spread)
        painter.setBrush(QColor("#FCFCFC"))
        painter.drawRoundedRect(panel, 16, 16)

    def prepare(self):
        combo = self.combo
        self._restore_focus = False
        self.list.setFont(combo.font())
        self.list.setModel(combo.model())
        self.list.setModelColumn(combo.modelColumn())
        self.list.setRootIndex(combo.rootModelIndex())
        index = combo.model().index(combo.currentIndex(), combo.modelColumn(), combo.rootModelIndex())
        self.list.setCurrentIndex(index)
        selection_model = self.list.selectionModel()
        if selection_model is not self._selection_model:
            if self._selection_model is not None:
                self._selection_model.currentChanged.disconnect(self._highlighted)
            selection_model.currentChanged.connect(self._highlighted)
            self._selection_model = selection_model
        anchor = combo.mapToGlobal(QPoint(0, 0))
        screen = QGuiApplication.screenAt(anchor) or combo.screen()
        bounds = screen.availableGeometry()
        below = bounds.bottom() - (anchor.y() + combo.height()) - 4
        above = anchor.y() - bounds.top() - 4
        use_below = below >= min(304, combo.count() * _ChoiceDelegate.ROW_HEIGHT + 12) or below >= above
        room = below if use_below else above
        available_panel_height = max(36, room - self.SHADOW_TOP - self.SHADOW_BOTTOM)
        panel_height = min(max(_ChoiceDelegate.ROW_HEIGHT, combo.count() * _ChoiceDelegate.ROW_HEIGHT) +
                           self.PANEL_PADDING * 2, 300, available_panel_height)
        width = min(max(combo.width(), 160) + self.SHADOW_LEFT + self.SHADOW_RIGHT, bounds.width())
        height = panel_height + self.SHADOW_TOP + self.SHADOW_BOTTOM
        x = anchor.x() - self.SHADOW_LEFT
        y = anchor.y() + combo.height() + 4 - self.SHADOW_TOP if use_below else anchor.y() - 4 - height + self.SHADOW_BOTTOM
        x = min(max(x, bounds.left()), bounds.right() - width + 1)
        y = min(max(y, bounds.top()), bounds.bottom() - height + 1)
        self.setGeometry(x, y, width, height)
        self.list.scrollTo(index, QListView.ScrollHint.EnsureVisible)

    def _highlighted(self, current, previous):
        if self.isVisible() and current.isValid():
            self.combo.highlighted.emit(current.row())
            self.combo.textHighlighted.emit(str(current.data() or ""))

    def commit(self, index):
        if not index.isValid() or not (index.flags() & Qt.ItemFlag.ItemIsEnabled):
            return
        self.combo.setCurrentIndex(index.row())
        self.combo.activated.emit(index.row())
        self.combo.textActivated.emit(self.combo.currentText())
        self.combo.hidePopup()

    def mousePressEvent(self, event):
        if not self.panel_rect().contains(event.position()):
            self.combo.hidePopup()
            event.accept()
        else:
            super().mousePressEvent(event)

    def hideEvent(self, event):
        super().hideEvent(event)
        self.combo._popup_finished(self._restore_focus)


class SurfaceComboBox(QComboBox):
    """Drop-in QComboBox with a rounded popup, including keyboard selection.

    Use ``SurfaceComboBox(parent)`` in place of ``QComboBox(parent)``. The normal
    addItem/currentData/findData/currentIndexChanged API is unchanged. Supported
    here are standard, non-editable single-column choices; editable controls
    deliberately retain QComboBox's original painting and keyboard contract.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._popup = None
        self._hover = 0.0
        self._open = 0.0
        self._keyboard_focus = False
        self._animations = {}
        for name in ("_hover", "_open"):
            animation = QVariantAnimation(self)
            animation.setDuration(motion_duration(150))
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            animation.valueChanged.connect(lambda value, attr=name: self._motion_value(attr, value))
            self._animations[name] = animation

    def _motion_value(self, name, value):
        setattr(self, name, float(value))
        self.update()

    def _animate(self, name, target):
        animation = self._animations[name]
        animation.stop()
        duration = motion_duration(150)
        if not duration or not self.isVisible():
            self._motion_value(name, target)
            return
        animation.setDuration(duration)
        animation.setStartValue(getattr(self, name))
        animation.setEndValue(float(target))
        animation.start()

    def sizeHint(self):
        hint = super().sizeHint()
        return QSize(max(160, hint.width()), max(42, hint.height()))

    def minimumSizeHint(self):
        return QSize(120, max(42, super().minimumSizeHint().height()))

    def showPopup(self):
        if self.isEditable():
            return super().showPopup()
        if not self.isEnabled() or not self.count():
            return
        if self._popup is not None and self._popup.isVisible():
            return
        if self._popup is None:
            self._popup = _ChoicePopup(self)
        self._popup.prepare()
        self._popup.show()
        self._popup.raise_()
        self._popup.list.setFocus(Qt.FocusReason.PopupFocusReason)
        self._animate("_open", 1.0)

    def hidePopup(self):
        if self._popup is not None and self._popup.isVisible():
            self._popup._restore_focus = True
            self._popup.hide()
        super().hidePopup()

    def _popup_finished(self, restore_focus):
        self._animate("_open", 0.0)
        if restore_focus:
            self.setFocus(Qt.FocusReason.PopupFocusReason)

    def enterEvent(self, event):
        super().enterEvent(event)
        self._animate("_hover", 1.0)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._animate("_hover", 0.0)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._keyboard_focus = event.reason() not in (Qt.FocusReason.MouseFocusReason, Qt.FocusReason.PopupFocusReason)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()

    def mousePressEvent(self, event):
        if not self.isEditable() and event.button() == Qt.MouseButton.LeftButton:
            self._keyboard_focus = False
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            if self._popup is not None and self._popup.isVisible():
                self.hidePopup()
            else:
                self.showPopup()
            event.accept()
        else:
            super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if not self.isEditable() and (event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_F4) or
                                    (event.key() == Qt.Key.Key_Down and event.modifiers() & Qt.KeyboardModifier.AltModifier)):
            self.showPopup()
            event.accept()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        if self.isEditable():
            return super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75)
        enabled = self.isEnabled()
        focus = self.hasFocus() and self._keyboard_focus
        background = QColor("#F7F7F7" if enabled else "#F3F3F3")
        if self._open > 0.01 or focus:
            background = QColor("#FFFFFF")
        painter.setBrush(background)
        shade = round(230 - self._hover * 29)
        border = QColor(shade, shade, shade) if enabled else QColor("#EAEAEA")
        if focus or self._open > 0.01:
            border = QColor("#555558")
        painter.setPen(QPen(border, 1.25 if focus else 1.0))
        painter.drawRoundedRect(rect, 12, 12)
        painter.setFont(self.font())
        painter.setPen(QColor("#1D1D1F" if enabled else "#A0A0A4"))
        text_rect = rect.adjusted(12, 0, -36, 0)
        icon = self.itemIcon(self.currentIndex())
        if not icon.isNull():
            icon.paint(painter, int(text_rect.left()), int(rect.center().y() - 8), 16, 16)
            text_rect.setLeft(text_rect.left() + 25)
        text = self.fontMetrics().elidedText(self.currentText(), Qt.TextElideMode.ElideRight, int(text_rect.width()))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        painter.save()
        painter.translate(rect.right() - 17, rect.center().y())
        painter.rotate(180 * self._open)
        chevron = QPainterPath()
        chevron.moveTo(-4, -2)
        chevron.lineTo(0, 2)
        chevron.lineTo(4, -2)
        painter.setPen(QPen(QColor("#757579" if enabled else "#ABABB0"), 1.5,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(chevron)
        painter.restore()
