"""Small, self-painted desktop controls with the native Qt button contract.

The widget keeps QPushButton's sizing, signals, shortcuts and accessibility.
Only its own pixels animate; no graphics effect or window opacity is involved.
"""

import ctypes
from functools import lru_cache
import sys

from PySide6.QtCore import QEvent, QEasingCurve, QPointF, QRect, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QPushButton, QStyle, QStyleOptionButton


@lru_cache(maxsize=1)
def _client_area_animation_enabled():
    """Read the Windows accessibility preference lazily, without needing Qt."""
    if sys.platform != "win32":
        return True
    try:
        enabled = ctypes.c_int(1)
        succeeded = ctypes.windll.user32.SystemParametersInfoW(
            0x1042, 0, ctypes.byref(enabled), 0)  # SPI_GETCLIENTAREAANIMATION
        return bool(enabled.value) if succeeded else True
    except (AttributeError, OSError):
        return True


def motion_duration(milliseconds):
    """Honor the system's reduced-motion preference for shared UI motions."""
    return max(0, int(milliseconds)) if _client_area_animation_enabled() else 0


def _mix(first, second, amount):
    first, second = QColor(first), QColor(second)
    amount = min(1.0, max(0.0, float(amount)))
    return QColor(*(round(getattr(first, channel)() * (1.0 - amount) +
                          getattr(second, channel)() * amount)
                    for channel in ("red", "green", "blue", "alpha")))


def _clear_surface(color="#F2F2F3"):
    result = QColor(color)
    result.setAlpha(0)
    return result


class SurfaceButton(QPushButton):
    """A consistent neutral button, styled by the existing semantic names.

    QPushButton still owns geometry and interaction. The painter uses the
    stylesheet's content rectangle and the widget's actual font, which keeps
    inherited padding, size hints, font loading and HiDPI behavior intact.
    """

    _LEFT_ALIGNED = frozenset((
        "sideNav", "settingsMenuChoice", "categoryChoice", "colorTile",
        "palettePair", "startupToggle", "inspirationToggle",
    ))
    _WINDOW_CONTROLS = frozenset(("windowControl", "windowClose"))
    _ICON_TEXT_GAP = 9.0
    _MENU_WIDTH = 16.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._hover_level = 0.0
        self._checked_level = 1.0 if self.isChecked() else 0.0
        self._press_level = 0.0
        self._keyboard_focus = False
        self._motions = {}
        self._motion_targets = {}
        for attribute in ("_hover_level", "_checked_level", "_press_level"):
            animation = QVariantAnimation(self)
            animation.setDuration(motion_duration(170))
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            animation.valueChanged.connect(
                lambda value, which=attribute: self._set_level(which, value))
            self._motions[attribute] = animation
            self._motion_targets[attribute] = getattr(self, attribute)
        self.toggled.connect(
            lambda checked: self._animate_to("_checked_level", float(checked)))
        self.pressed.connect(lambda: self._animate_to("_press_level", 1.0))
        self.released.connect(lambda: self._animate_to("_press_level", 0.0))
        self.objectNameChanged.connect(lambda _name: self.update())

    def _fit_content_hint(self, native_hint):
        """Budget the same icon gap and menu width that the painter uses.

        The platform size hint reserves a four-pixel icon gap. Our nine-pixel
        gap otherwise stole five pixels from short, intrinsically sized actions.
        Keep the stylesheet's dimensions and add only the missing content room.
        """
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.rect = QRect(0, 0, native_hint.width(), native_hint.height())
        contents = self.style().subElementRect(
            QStyle.SubElement.SE_PushButtonContents, option, self)
        flags = int(Qt.TextFlag.TextShowMnemonic | Qt.TextFlag.TextSingleLine)
        text_width = self.fontMetrics().size(flags, self.text()).width()
        has_icon = not self.icon().isNull()
        icon_width = self.iconSize().width() if has_icon else 0
        gap = self._ICON_TEXT_GAP if has_icon and self.text() else 0.0
        menu_width = self._MENU_WIDTH if self.menu() is not None else 0.0
        required = text_width + icon_width + gap + menu_width
        # One extra pixel protects the final glyph from fractional HiDPI bounds.
        deficit = max(0, int(required + (1 if text_width else 0) - contents.width()))
        return QSize(native_hint.width() + deficit, native_hint.height())

    def sizeHint(self):
        return self._fit_content_hint(super().sizeHint())

    def minimumSizeHint(self):
        return self._fit_content_hint(super().minimumSizeHint())

    def _set_level(self, attribute, value):
        setattr(self, attribute, float(value))
        self.update()

    def _animate_to(self, attribute, target):
        target = float(target)
        if self._motion_targets[attribute] == target:
            return
        self._motion_targets[attribute] = target
        animation = self._motions[attribute]
        animation.stop()
        duration = motion_duration(170)
        animation.setDuration(duration)
        if not duration or not self.isVisible():
            self._set_level(attribute, target)
            return
        animation.setStartValue(getattr(self, attribute))
        animation.setEndValue(target)
        animation.start()

    def enterEvent(self, event):
        super().enterEvent(event)
        self._animate_to("_hover_level", 1.0 if self.isEnabled() else 0.0)
        self._animate_to("_press_level", float(self.isDown()))

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._animate_to("_hover_level", 0.0)
        self._animate_to("_press_level", float(self.isDown()))

    def mousePressEvent(self, event):
        self._keyboard_focus = False
        super().mousePressEvent(event)
        self.update()

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        self._animate_to("_press_level", float(self.isDown()))

    def setDown(self, down):
        super().setDown(down)
        if hasattr(self, "_motions"):
            self._animate_to("_press_level", float(down))

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._keyboard_focus = event.reason() in (
            Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason,
            Qt.FocusReason.ShortcutFocusReason)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self._keyboard_focus = False
        self.update()

    def changeEvent(self, event):
        super().changeEvent(event)
        if not hasattr(self, "_motions"):
            return
        if event.type() == QEvent.Type.EnabledChange and not self.isEnabled():
            for attribute in ("_hover_level", "_press_level"):
                self._motions[attribute].stop()
                self._motion_targets[attribute] = 0.0
                setattr(self, attribute, 0.0)
        if event.type() in (
                QEvent.Type.EnabledChange, QEvent.Type.PaletteChange,
                QEvent.Type.StyleChange, QEvent.Type.FontChange,
                QEvent.Type.LayoutDirectionChange):
            self.update()

    def _colors(self):
        name = self.objectName()
        border = _clear_surface()
        if name in ("primary", "actionPrimary"):
            base, hover, selected, pressed = (
                "#1D1D1F", "#303033", "#18181A", "#080809")
            text, selected_text = "#FFFFFF", "#FFFFFF"
        elif name in ("quiet", "inspirationToggle") or self.isFlat():
            base, hover, selected, pressed = (
                _clear_surface(), "#F0F0F2", "#E9E9EB", "#E4E4E7")
            text = "#626266" if name == "quiet" else "#252527"
            selected_text = "#1D1D1F"
        elif name in ("sideNav", "settingsMenuChoice"):
            base, hover, selected, pressed = (
                _clear_surface(), "#F1F1F3", "#EDEDEF", "#E3E3E6")
            text, selected_text = "#3B3B3D", "#1D1D1F"
        elif name in ("categoryChoice", "transportChoice", "pairingMood"):
            base, hover, selected, pressed = (
                "#F3F3F4", "#E9E9EB", "#E5E5E7", "#DCDCDF")
            text, selected_text = "#444447", "#1D1D1F"
        elif name in ("colorTile", "palettePair", "startupToggle"):
            base, hover, selected, pressed = (
                "#F7F7F8", "#EFEFF1", "#E9E9EC", "#E4E4E7")
            text, selected_text = "#252527", "#1D1D1F"
            if name == "palettePair":
                border = _mix(border, "#BDBDC2", self._checked_level)
        elif name in self._WINDOW_CONTROLS:
            base, selected = _clear_surface(), "#E6E6E8"
            hover = "#F3E4E4" if name == "windowClose" else "#E6E6E8"
            pressed = "#EAD4D4" if name == "windowClose" else "#DADADD"
            text, selected_text = "#555558", "#1D1D1F"
        else:
            base, hover, selected, pressed = (
                "#F2F2F3", "#E8E8EA", "#E5E5E8", "#DBDBDE")
            text, selected_text = "#1D1D1F", "#1D1D1F"
            if name == "actionSecondary":
                selected, selected_text = "#222224", "#FFFFFF"

        background = _mix(base, selected, self._checked_level)
        hover_amount = self._hover_level * (1.0 - self._checked_level * 0.45)
        if name == "actionSecondary":
            hover = _mix(hover, "#343437", self._checked_level)
        background = _mix(background, hover, hover_amount)
        if name == "actionSecondary":
            pressed = _mix(pressed, "#111113", self._checked_level)
        background = _mix(background, pressed, self._press_level)
        foreground = _mix(text, selected_text, self._checked_level)
        if name in ("quiet", "inspirationToggle", "sideNav", "settingsMenuChoice"):
            foreground = _mix(foreground, "#1D1D1F", self._hover_level)
        if not self.isEnabled():
            background, foreground, border = (
                QColor("#F3F3F4"), QColor("#747478"), _clear_surface())
        elif self.hasFocus() and self._keyboard_focus:
            # The only focus perimeter is the button's existing outer contour.
            border = QColor("#747478" if name in ("primary", "actionPrimary")
                            else "#5E5E63")
        return background, foreground, border

    def paintEvent(self, _event):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing |
                               QPainter.RenderHint.TextAntialiasing)
        painter.setFont(self.font())
        background, foreground, border = self._colors()
        press_inset = 0.6 * self._press_level
        shape = QRectF(self.rect()).adjusted(
            0.75 + press_inset, 0.75 + press_inset,
            -0.75 - press_inset, -0.75 - press_inset)
        if shape.width() <= 0 or shape.height() <= 0:
            return
        if background.alpha() and self._press_level > 0.001:
            highlight = QLinearGradient(shape.topLeft(), shape.bottomLeft())
            highlight.setColorAt(0, _mix(background, "#FFFFFF",
                                         self._press_level * 0.055))
            highlight.setColorAt(1, background)
            painter.setBrush(highlight)
        else:
            painter.setBrush(background)
        focused = self.hasFocus() and self._keyboard_focus and self.isEnabled()
        painter.setPen(QPen(border, 1.4 if focused else 1.0))
        painter.drawRoundedRect(shape, 12, 12)

        content = QRectF(self.style().subElementRect(
            QStyle.SubElement.SE_PushButtonContents, option, self))
        content.translate(0, 0.35 * self._press_level)
        self._draw_content(painter, option, content, foreground)

    def _draw_content(self, painter, option, content, foreground):
        if content.width() <= 0 or content.height() <= 0:
            return
        has_icon = not self.icon().isNull()
        icon_width = min(self.iconSize().width(), content.width()) if has_icon else 0
        icon_height = min(self.iconSize().height(), content.height()) if has_icon else 0
        gap = self._ICON_TEXT_GAP if has_icon and self.text() else 0.0
        menu_width = self._MENU_WIDTH if self.menu() is not None else 0.0
        available_text = max(0, int(content.width() - icon_width - gap - menu_width))
        metrics = painter.fontMetrics()
        mnemonic_flags = Qt.TextFlag.TextShowMnemonic | Qt.TextFlag.TextSingleLine
        full_width = metrics.size(int(mnemonic_flags), self.text()).width()
        text = self.text()
        if full_width > available_text:
            text = metrics.elidedText(text, Qt.TextElideMode.ElideRight,
                                      available_text, int(mnemonic_flags))
        text_width = min(available_text,
                         metrics.size(int(mnemonic_flags), text).width())
        if text_width == 0:
            gap = 0.0
        group_width = icon_width + gap + text_width + menu_width
        left_aligned = self.objectName() in self._LEFT_ALIGNED
        if self.objectName() in self._WINDOW_CONTROLS:
            left_aligned = False
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        group_x = (content.right() - group_width if rtl else content.left()) \
            if left_aligned else content.center().x() - group_width / 2.0
        if rtl:
            icon_x = group_x + group_width - icon_width
            text_x = group_x + menu_width
        else:
            icon_x = group_x
            text_x = group_x + icon_width + gap

        painter.save()
        painter.setClipRect(content)
        if has_icon:
            icon_rect = QRectF(icon_x, content.center().y() - icon_height / 2.0,
                               icon_width, icon_height)
            mode = (self.icon().Mode.Normal if self.isEnabled()
                    else self.icon().Mode.Disabled)
            state = self.icon().State.On if self.isChecked() else self.icon().State.Off
            # Retain full-color swatches and the icon system's authored cutouts.
            self.icon().paint(painter, icon_rect.toAlignedRect(),
                              Qt.AlignmentFlag.AlignCenter, mode, state)
        painter.setPen(foreground)
        text_flags = Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine
        text_flags |= (Qt.TextFlag.TextShowMnemonic if self.style().styleHint(
            QStyle.StyleHint.SH_UnderlineShortcut, option, self)
                       else Qt.TextFlag.TextHideMnemonic)
        text_flags |= Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft
        painter.drawText(QRectF(text_x, content.top(), text_width, content.height()),
                         int(text_flags), text)
        if self.menu() is not None:
            menu_x = (group_x + 5.0 if rtl else group_x + group_width - 5.0)
            center_y = content.center().y()
            pen = QPen(foreground, 1.3)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawLine(QPointF(menu_x - 3, center_y - 1.5),
                             QPointF(menu_x, center_y + 1.5))
            painter.drawLine(QPointF(menu_x, center_y + 1.5),
                             QPointF(menu_x + 3, center_y - 1.5))
        painter.restore()
