"""Desktop UI and lifecycle for 老必灯."""

import ctypes
from functools import lru_cache
import json
import logging
import os
import re
import shutil
import sys
import time
import winreg
import zipfile
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QSize, QRectF, QPointF, QStandardPaths, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QFont, QFontDatabase, QIcon, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QShortcut
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QDoubleSpinBox, QFrame,
    QComboBox, QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMenu, QPushButton, QScrollArea, QSlider, QSpinBox, QStackedWidget,
    QSystemTrayIcon, QVBoxLayout, QWidget,
)

from backend import LightingController, bluetooth_keyboard_present
from device_setup import DeviceSetupDialog, is_supported_v98, keycaps_from_profile
from device_detection import detect_keyboards, preferred_known_keyboard
from effects import CATEGORIES, EFFECTS, EFFECT_CATEGORY, EFFECT_IDS, MUSIC, REACTIVE, WIDTH_EFFECTS
from layout import KEYCAPS, LED_CENTERS, restore_v98_layout, set_keycaps


ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "老必灯"
DATA_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS = DATA_DIR / "settings.json"
LEGACY_SETTINGS = ROOT / "settings.json"
ICON = ROOT / "assets" / "ripple.ico"
SERVER_NAME = "vgn-ripple-v98pro-320f-5055"
PROJECT_URL = "https://github.com/Stt7L/laobideng"
LOG = logging.getLogger("vgn-ripple")
STARTUP_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_VALUE = "LaoBiDeng"


def load_ui_font():
    font_dir = ROOT / "assets" / "fonts"
    for family in ("HarmonyOS_Sans", "HarmonyOS_Sans_SC"):
        for weight in ("Regular", "Medium", "Bold"):
            bundled = font_dir / f"{family}_{weight}.ttf"
            if bundled.is_file():
                QFontDatabase.addApplicationFont(str(bundled))


@lru_cache(maxsize=1)
def ui_font():
    """Use the bundled Chinese HarmonyOS Sans family throughout the UI."""
    families = set(QFontDatabase.families())
    if "HarmonyOS Sans SC" in families:
        return "HarmonyOS Sans SC"
    return "Microsoft YaHei UI"

PAIRING_MOODS = ("清新", "暖调", "霓虹", "柔和", "撞色", "复古", "自然")
COLOR_PAIRINGS = (
    ("清新", "青柠珊瑚", (196, 239, 112), (255, 130, 112)),
    ("清新", "海盐晚霞", (96, 201, 211), (245, 151, 142)),
    ("清新", "薄荷樱云", (141, 224, 193), (244, 159, 191)),
    ("清新", "雾蓝杏光", (131, 189, 227), (255, 196, 139)),
    ("清新", "柚子苏打", (255, 205, 97), (106, 213, 189)),
    ("清新", "冰川桃粉", (111, 216, 238), (250, 148, 185)),
    ("暖调", "赤陶奶油", (227, 125, 103), (255, 220, 158)),
    ("暖调", "日落金橘", (255, 114, 107), (255, 195, 91)),
    ("暖调", "琥珀孔雀", (255, 177, 75), (86, 190, 179)),
    ("暖调", "樱桃奶昔", (223, 90, 137), (255, 191, 173)),
    ("暖调", "金麦紫霞", (250, 195, 99), (168, 138, 220)),
    ("暖调", "烟粉香槟", (221, 151, 163), (246, 213, 158)),
    ("霓虹", "电光莓紫", (190, 77, 247), (255, 100, 177)),
    ("霓虹", "霓虹海浪", (49, 218, 227), (119, 111, 255)),
    ("霓虹", "激光日落", (255, 88, 150), (255, 180, 66)),
    ("霓虹", "电音酸橙", (176, 255, 62), (90, 126, 255)),
    ("霓虹", "蓝焰玫红", (71, 159, 255), (255, 72, 145)),
    ("霓虹", "紫电冰蓝", (155, 102, 255), (73, 227, 255)),
    ("柔和", "月光薰衣草", (193, 211, 245), (193, 161, 229)),
    ("柔和", "岩盐浅海", (229, 202, 194), (116, 198, 204)),
    ("柔和", "杏仁蓝莓", (242, 207, 160), (152, 162, 226)),
    ("柔和", "雾松蜜桃", (137, 191, 165), (245, 178, 150)),
    ("柔和", "晨雾玫瑰", (202, 215, 226), (233, 148, 174)),
    ("柔和", "甜橙牛奶", (250, 189, 127), (244, 220, 190)),
    ("撞色", "海水番茄", (78, 219, 219), (255, 97, 87)),
    ("撞色", "金橘蓝调", (252, 181, 75), (91, 119, 236)),
    ("撞色", "青柠葡萄", (214, 248, 86), (177, 83, 222)),
    ("撞色", "莓粉薄荷", (241, 115, 202), (95, 219, 176)),
    ("撞色", "晴空柠檬", (108, 154, 245), (255, 214, 105)),
    ("撞色", "珊瑚冰河", (255, 121, 101), (85, 218, 222)),
    ("撞色", "紫藤麦芽", (168, 96, 240), (255, 200, 93)),
    ("撞色", "孔雀玫瑰", (72, 200, 151), (244, 109, 167)),
    ("复古", "老电影", (179, 155, 112), (209, 123, 112)),
    ("复古", "铜绿夕照", (91, 170, 151), (240, 169, 94)),
    ("复古", "唱片封套", (188, 123, 170), (235, 194, 126)),
    ("复古", "咖啡蓝釉", (207, 155, 113), (104, 170, 200)),
    ("复古", "胶片海风", (105, 167, 177), (232, 145, 117)),
    ("复古", "旧梦玫瑰", (208, 142, 157), (163, 182, 123)),
    ("复古", "麦田暮紫", (218, 180, 103), (151, 126, 189)),
    ("复古", "汽水瓶盖", (122, 183, 159), (232, 168, 147)),
    ("自然", "山谷清晨", (124, 188, 145), (248, 207, 124)),
    ("自然", "浅海贝壳", (100, 192, 207), (239, 183, 160)),
    ("自然", "花园露水", (163, 209, 130), (175, 152, 218)),
    ("自然", "湖畔霞光", (115, 184, 217), (255, 174, 123)),
    ("自然", "雨后栀子", (222, 226, 174), (133, 196, 175)),
    ("自然", "初雪红梅", (205, 224, 237), (225, 104, 136)),
    ("自然", "火山海盐", (235, 127, 106), (112, 197, 193)),
    ("自然", "森林星夜", (106, 181, 141), (139, 170, 230)),
)


def read_settings():
    try:
        source = SETTINGS if SETTINGS.exists() else LEGACY_SETTINGS
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def color_from_setting(value, default):
    if not isinstance(value, str) or len(value) != 7 or value[0] != "#":
        return default
    try:
        return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
    except ValueError:
        return default


def color_hex(value):
    return "#%02X%02X%02X" % value


def startup_command():
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable)
    else:
        executable = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "老必灯" / "老必灯.exe"
    return f'"{executable}" --autostart' if executable.is_file() else None


def startup_enabled():
    command = startup_command()
    if not command:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY) as key:
            saved, _ = winreg.QueryValueEx(key, STARTUP_VALUE)
        return saved.casefold() == command.casefold()
    except (OSError, AttributeError):
        return False


def set_startup_enabled(enabled):
    command = startup_command()
    if enabled and not command:
        raise OSError("请先安装老必灯，再开启开机自启")
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, STARTUP_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, STARTUP_VALUE, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, STARTUP_VALUE)
            except FileNotFoundError:
                pass


def swatch_icon(rgb):
    pixmap = QPixmap(28, 28)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#8D9988"), 1))
    painter.setBrush(QColor(*rgb))
    painter.drawEllipse(2, 2, 24, 24)
    painter.end()
    return QIcon(pixmap)


def pair_swatch_icon(base, accent):
    pixmap = QPixmap(48, 28)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#172019"), 1))
    painter.setBrush(QColor(*base))
    painter.drawEllipse(QRectF(1, 2, 24, 24))
    painter.setBrush(QColor(*accent))
    painter.drawEllipse(QRectF(22, 2, 24, 24))
    painter.end()
    return QIcon(pixmap)


def chevron_icon(up=False):
    pixmap = QPixmap(18, 18)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor("#C4EF70"), 2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    middle_y = 6 if up else 12
    outer_y = 12 if up else 6
    painter.drawLine(QPointF(4, outer_y), QPointF(9, middle_y))
    painter.drawLine(QPointF(9, middle_y), QPointF(14, outer_y))
    painter.end()
    return QIcon(pixmap)


def control_icon(kind, color="#D8E4D2"):
    """Small, consistent line icons for actions and category controls."""
    pixmap = QPixmap(20, 20)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), 1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if kind == "settings":
        painter.drawEllipse(QRectF(5, 5, 10, 10))
        painter.drawEllipse(QRectF(8, 8, 4, 4))
        for a, b, c, d in ((10, 1.5, 10, 4), (10, 16, 10, 18.5),
                            (1.5, 10, 4, 10), (16, 10, 18.5, 10),
                            (4, 4, 5.8, 5.8), (14.2, 14.2, 16, 16),
                            (4, 16, 5.8, 14.2), (14.2, 5.8, 16, 4)):
            painter.drawLine(QPointF(a, b), QPointF(c, d))
    elif kind == "back":
        painter.drawLine(QPointF(11, 4), QPointF(5, 10))
        painter.drawLine(QPointF(5, 10), QPointF(11, 16))
        painter.drawLine(QPointF(5, 10), QPointF(17, 10))
    elif kind == "music":
        for x, top, bottom in ((4, 7, 13), (8, 3, 17),
                               (12, 6, 14), (16, 4, 16)):
            painter.drawLine(QPointF(x, top), QPointF(x, bottom))
    elif kind == "reactive":
        painter.drawEllipse(QRectF(7, 7, 6, 6))
        painter.drawArc(QRectF(3, 3, 14, 14), 20 * 16, 130 * 16)
        painter.drawArc(QRectF(3, 3, 14, 14), 200 * 16, 130 * 16)
    elif kind == "custom":
        painter.drawLine(QPointF(4, 15), QPointF(14.5, 4.5))
        painter.drawLine(QPointF(13.5, 3.5), QPointF(16.5, 6.5))
        painter.drawLine(QPointF(3, 17), QPointF(7, 16))
    elif kind == "regular":
        painter.drawEllipse(QRectF(6.5, 6.5, 7, 7))
        for a, b, c, d in ((10, 1.5, 10, 4), (10, 16, 10, 18.5),
                            (1.5, 10, 4, 10), (16, 10, 18.5, 10)):
            painter.drawLine(QPointF(a, b), QPointF(c, d))
    elif kind == "refresh":
        painter.drawArc(QRectF(3, 3, 14, 14), 40 * 16, 290 * 16)
        painter.drawLine(QPointF(15.8, 3.8), QPointF(16.5, 8.1))
        painter.drawLine(QPointF(16.5, 8.1), QPointF(12.4, 7.5))
    elif kind == "save":
        painter.drawLine(QPointF(10, 3), QPointF(10, 12))
        painter.drawLine(QPointF(6.5, 9), QPointF(10, 12.5))
        painter.drawLine(QPointF(13.5, 9), QPointF(10, 12.5))
        painter.drawLine(QPointF(4, 14), QPointF(4, 17))
        painter.drawLine(QPointF(4, 17), QPointF(16, 17))
        painter.drawLine(QPointF(16, 17), QPointF(16, 14))
    elif kind == "power":
        painter.drawLine(QPointF(10, 2), QPointF(10, 9))
        painter.drawArc(QRectF(3, 4, 14, 14), 135 * 16, 270 * 16)
    elif kind == "pause":
        painter.drawLine(QPointF(7, 4), QPointF(7, 16))
        painter.drawLine(QPointF(13, 4), QPointF(13, 16))
    elif kind == "play":
        painter.drawLine(QPointF(6, 3.5), QPointF(16, 10))
        painter.drawLine(QPointF(16, 10), QPointF(6, 16.5))
        painter.drawLine(QPointF(6, 16.5), QPointF(6, 3.5))
    elif kind == "add":
        painter.drawLine(QPointF(10, 3), QPointF(10, 17))
        painter.drawLine(QPointF(3, 10), QPointF(17, 10))
    elif kind == "clear":
        painter.drawLine(QPointF(4, 4), QPointF(16, 16))
        painter.drawLine(QPointF(16, 4), QPointF(4, 16))
    elif kind == "external":
        painter.drawLine(QPointF(4, 16), QPointF(15, 5))
        painter.drawLine(QPointF(9, 5), QPointF(15, 5))
        painter.drawLine(QPointF(15, 5), QPointF(15, 11))
    elif kind == "palette":
        painter.drawEllipse(QRectF(2.5, 2.5, 15, 15))
        painter.drawEllipse(QRectF(5, 6, 1.8, 1.8))
        painter.drawEllipse(QRectF(8.5, 4.5, 1.8, 1.8))
        painter.drawEllipse(QRectF(12.5, 7, 1.8, 1.8))
        painter.drawEllipse(QRectF(6.5, 11.5, 1.8, 1.8))
    elif kind == "sliders":
        for y, x in ((4.5, 7), (10, 13), (15.5, 9)):
            painter.drawLine(QPointF(3, y), QPointF(17, y))
            painter.drawEllipse(QRectF(x - 1.5, y - 1.5, 3, 3))
    elif kind == "device":
        painter.drawRoundedRect(QRectF(2.5, 5, 15, 10), 2, 2)
        painter.drawLine(QPointF(6, 9), QPointF(14, 9))
        painter.drawLine(QPointF(7, 12), QPointF(13, 12))
    painter.end()
    return QIcon(pixmap)


class EffectChoiceButton(QPushButton):
    """An effect option with distinct title, description and selection states."""

    def __init__(self, title, description, parent=None):
        super().__init__(parent)
        self.title = title
        self.description = description
        self.setCheckable(True)
        self.setMinimumHeight(68)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        checked = self.isChecked()
        hovered = self.underMouse()
        pressed = self.isDown()
        if not self.isEnabled():
            background, border, title_color, detail_color = (
                "#202822", "#354136", "#778575", "#657461")
        elif pressed:
            background, border, title_color, detail_color = (
                "#263528", "#C4EF70", "#F1F9E6", "#B9CEAA")
        elif checked:
            background, border, title_color, detail_color = (
                "#34462E", "#C4EF70", "#ECF9D8", "#C6DAB6")
        elif hovered:
            background, border, title_color, detail_color = (
                "#303D32", "#7B9073", "#F2F6EE", "#C9D5C3")
        else:
            background, border, title_color, detail_color = (
                "#252E27", "#3C493E", "#E7EEE2", "#AEBDA9")
        rect = QRectF(1, 1 + (1 if pressed else 0),
                      self.width() - 2, self.height() - 3)
        painter.setBrush(QColor(background))
        painter.setPen(QPen(QColor(border), 1.5 if checked else 1))
        painter.drawRoundedRect(rect, 13, 13)
        if self.hasFocus():
            painter.setPen(QPen(QColor("#E2FBAF"), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(3, 3, -3, -3), 10, 10)
        title_font = QFont(ui_font(), 10, QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.setPen(QColor(title_color))
        title_width = max(20, self.width() - (48 if checked else 28))
        painter.drawText(QRectF(14, 11, title_width, 23),
                         Qt.AlignmentFlag.AlignVCenter,
                         painter.fontMetrics().elidedText(
                             self.title, Qt.TextElideMode.ElideRight,
                             int(title_width)))
        detail_font = QFont(ui_font(), 9)
        painter.setFont(detail_font)
        painter.setPen(QColor(detail_color))
        detail_width = max(20, self.width() - 28)
        painter.drawText(QRectF(14, 35, detail_width, 22),
                         Qt.AlignmentFlag.AlignVCenter,
                         painter.fontMetrics().elidedText(
                             self.description, Qt.TextElideMode.ElideRight,
                             int(detail_width)))
        if checked:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#C4EF70"))
            painter.drawEllipse(QPointF(self.width() - 19, 23), 3.5, 3.5)
        painter.end()


class SwitchButton(QPushButton):
    """A wide setting row with a native-looking, accessible on/off switch."""

    def __init__(self, title, parent=None):
        super().__init__(title, parent)
        self.setCheckable(True)
        self.setMinimumHeight(48)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        enabled = self.isEnabled()
        checked = self.isChecked()
        hovered = self.underMouse() and enabled
        pressed = self.isDown() and enabled
        background = "#202B23" if pressed else "#303C32" if hovered else "#263128"
        border = "#C4EF70" if self.hasFocus() else (
            "#78916F" if hovered else "#405043")
        painter.setBrush(QColor(background if enabled else "#202822"))
        painter.setPen(QPen(QColor(border), 1))
        painter.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1,
                                        self.height() - 1), 12, 12)
        painter.setFont(QFont(ui_font(), 10, QFont.Weight.DemiBold))
        painter.setPen(QColor("#EAF2E4" if enabled else "#778575"))
        painter.drawText(QRectF(16, 0, self.width() - 90, self.height()),
                         Qt.AlignmentFlag.AlignVCenter, self.text())
        track = QRectF(self.width() - 65, (self.height() - 26) / 2, 48, 26)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#C4EF70" if checked and enabled else "#566459"))
        painter.drawRoundedRect(track, 13, 13)
        thumb_x = track.right() - 13 if checked else track.left() + 13
        painter.setBrush(QColor("#F8FBF5" if enabled else "#B3BEB1"))
        painter.drawEllipse(QPointF(thumb_x, track.center().y() + (1 if pressed else 0)),
                            9 if pressed else 10, 9 if pressed else 10)
        painter.end()


class NoWheelSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event):
        event.ignore()


class FineSlider(QSlider):
    """Inset circular slider with subtle motion and optional magnetic stops."""

    EDGE = 19

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setFixedHeight(42)
        self.setSingleStep(1)
        self.setPageStep(10)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self._hovered = False
        self._visual_fraction = 0.0
        self._snap_values = []
        self._active_snap = None
        self._motion_timer = QTimer(self)
        self._motion_timer.setInterval(16)
        self._motion_timer.timeout.connect(self._advance_visual)
        self.valueChanged.connect(self._animate_to_value)

    def setSnapValues(self, values):
        self._snap_values = sorted({max(self.minimum(), min(self.maximum(),
                                            int(value))) for value in values})
        self.update()

    def _fraction(self):
        return (self.value() - self.minimum()) / max(1, self.maximum() - self.minimum())

    def _position(self, fraction):
        return self.EDGE + fraction * max(1, self.width() - self.EDGE * 2)

    def _animate_to_value(self, _value):
        self._motion_timer.start()
        self.update()

    def _advance_visual(self):
        target = self._fraction()
        self._visual_fraction += (target - self._visual_fraction) * (0.34 if self.isSliderDown() else 0.48)
        if abs(target - self._visual_fraction) < 0.0005:
            self._visual_fraction = target
            self._motion_timer.stop()
        self.update()

    def showEvent(self, event):
        self._visual_fraction = self._fraction()
        super().showEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center_y = self.height() / 2
        x = self._position(self._visual_fraction)
        track = QRectF(2, center_y - 15, max(1, self.width() - 4), 30)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#303B32"))
        painter.drawRoundedRect(track, 15, 15)
        fill = QRectF(4, center_y - 13, max(0, x - 4), 26)
        painter.setBrush(QColor("#A8D66A" if self.isSliderDown() else "#8FBB5E"))
        painter.drawRoundedRect(fill, 13, 13)
        show_marks = self._hovered or self.isSliderDown() or self.hasFocus()
        if show_marks:
            for mark in self._snap_values:
                fraction = (mark - self.minimum()) / max(1, self.maximum() - self.minimum())
                dot_x = self._position(fraction)
                active = mark == self._active_snap and self.isSliderDown()
                painter.setBrush(QColor("#F0FFCF" if active else "#B9C7B5"))
                diameter = 4.5 if active else 2.8
                painter.drawEllipse(QPointF(dot_x, center_y), diameter, diameter)
        if self.isSliderDown() or self._hovered:
            painter.setBrush(QColor(196, 239, 112, 43 if self.isSliderDown() else 23))
            painter.drawEllipse(QPointF(x, center_y), 17, 17)
        thumb_radius = 11 if self.isSliderDown() else 12
        painter.setBrush(QColor(9, 15, 10, 88))
        painter.drawEllipse(QPointF(x, center_y + 2), thumb_radius + 1, thumb_radius + 1)
        painter.setPen(QPen(QColor("#EEF8E4" if self.isSliderDown() else "#FFFFFF"), 1))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QPointF(x, center_y), thumb_radius, thumb_radius)
        if self.isSliderDown():
            painter.setPen(QPen(QColor("#D9FBA2"), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(x, center_y), thumb_radius + 3, thumb_radius + 3)
        painter.end()

    def _set_from_pointer(self, x):
        width = max(1, self.width() - self.EDGE * 2)
        fraction = min(1.0, max(0.0, (x - self.EDGE) / width))
        raw = self.minimum() + fraction * (self.maximum() - self.minimum())
        self._active_snap = None
        if self._snap_values:
            nearest = min(self._snap_values, key=lambda mark: abs(mark - raw))
            distance = abs(self._position((nearest - self.minimum()) /
                                          max(1, self.maximum() - self.minimum())) - x)
            if distance <= 8:
                raw = nearest
                self._active_snap = nearest
        self.setValue(round(raw))
        self.update()

    def wheelEvent(self, event):
        event.ignore()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self.setSliderDown(True)
            self._set_from_pointer(event.position().x())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.isSliderDown():
            self._set_from_pointer(event.position().x())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isSliderDown():
            self._set_from_pointer(event.position().x())
            self.setSliderDown(False)
            self._active_snap = None
            self._motion_timer.start()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()


class ColorField(QWidget):
    """A direct saturation/value surface with keyboard and pointer control."""

    colorChanged = Signal(QColor)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hue = 150
        self.saturation = 180
        self.value = 255
        self.setMinimumHeight(190)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("颜色区域：左右调整鲜艳度，上下调整明暗")
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._hovered = False

    def setColor(self, color):
        if color.hue() >= 0:
            self.hue = color.hue()
        self.saturation = color.saturation()
        self.value = color.value()
        self.update()

    def setHue(self, hue):
        self.hue = max(0, min(359, int(hue)))
        self.update()
        self.colorChanged.emit(QColor.fromHsv(self.hue, self.saturation, self.value))

    def _pick(self, point):
        width = max(1, self.width() - 1)
        height = max(1, self.height() - 1)
        self.saturation = round(max(0.0, min(1.0, point.x() / width)) * 255)
        self.value = round((1 - max(0.0, min(1.0, point.y() / height))) * 255)
        self.update()
        self.colorChanged.emit(QColor.fromHsv(self.hue, self.saturation, self.value))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self._pick(event.position())
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._pick(event.position())
            event.accept()

    def keyPressEvent(self, event):
        move = {
            Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0),
            Qt.Key.Key_Up: (0, 1), Qt.Key.Key_Down: (0, -1),
        }.get(event.key())
        if move is None:
            super().keyPressEvent(event)
            return
        step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 2
        self.saturation = max(0, min(255, self.saturation + move[0] * step))
        self.value = max(0, min(255, self.value + move[1] * step))
        self.update()
        self.colorChanged.emit(QColor.fromHsv(self.hue, self.saturation, self.value))
        event.accept()

    def paintEvent(self, _event):
        area = QRectF(0, 0, self.width(), self.height())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(area.adjusted(1, 1, -1, -1), 12, 12)
        painter.setClipPath(path)
        painter.fillRect(area, QColor.fromHsv(self.hue, 255, 255))
        white = QLinearGradient(0, 0, self.width(), 0)
        white.setColorAt(0, QColor(255, 255, 255))
        white.setColorAt(1, QColor(255, 255, 255, 0))
        painter.fillRect(area, QBrush(white))
        shade = QLinearGradient(0, 0, 0, self.height())
        shade.setColorAt(0, QColor(0, 0, 0, 0))
        shade.setColorAt(1, QColor(0, 0, 0))
        painter.fillRect(area, QBrush(shade))
        painter.setClipping(False)
        painter.setPen(QPen(QColor("#A5B89B" if self._hovered else "#758473"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(area.adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        x = max(10, min(self.width() - 11,
                        self.saturation / 255 * (self.width() - 1)))
        y = max(10, min(self.height() - 11,
                        (1 - self.value / 255) * (self.height() - 1)))
        painter.setPen(QPen(QColor("#162019"), 4))
        painter.drawEllipse(QPointF(x, y), 8, 8)
        painter.setPen(QPen(QColor("#F3F8ED"), 2.5))
        painter.drawEllipse(QPointF(x, y), 8, 8)
        if self.hasFocus():
            painter.setPen(QPen(QColor("#C4EF70"), 2))
            painter.drawRoundedRect(area.adjusted(3, 3, -3, -3), 10, 10)
        painter.end()

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)


class HueStrip(QWidget):
    hueChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hue = 150
        self.setFixedHeight(26)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("色相：左右选择颜色")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hovered = False

    def setHue(self, hue):
        self.hue = max(0, min(359, int(hue)))
        self.update()

    def _pick(self, x):
        self.setHue(round(max(0.0, min(1.0, x / max(1, self.width() - 1))) * 359))
        self.hueChanged.emit(self.hue)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self._pick(event.position().x())
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._pick(event.position().x())
            event.accept()

    def keyPressEvent(self, event):
        if event.key() not in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            super().keyPressEvent(event)
            return
        step = 12 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 2
        self.setHue((self.hue + (step if event.key() == Qt.Key.Key_Right else -step)) % 360)
        self.hueChanged.emit(self.hue)
        event.accept()

    def paintEvent(self, _event):
        area = QRectF(0, 3, self.width(), self.height() - 6)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(area.adjusted(1, 1, -1, -1), 8, 8)
        painter.setClipPath(path)
        gradient = QLinearGradient(0, 0, self.width(), 0)
        for index in range(7):
            gradient.setColorAt(index / 6, QColor.fromHsv(round(index * 359 / 6), 255, 255))
        painter.fillRect(area, QBrush(gradient))
        painter.setClipping(False)
        x = max(10, min(self.width() - 11,
                        self.hue / 359 * max(1, self.width() - 1)))
        painter.setPen(QPen(QColor("#172019"), 3))
        painter.setBrush(QColor.fromHsv(self.hue, 255, 255))
        painter.drawEllipse(QPointF(x, self.height() / 2), 9, 9)
        painter.setPen(QPen(QColor("#F3F8ED"), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(x, self.height() / 2), 9, 9)
        if self.hasFocus():
            painter.setPen(QPen(QColor("#C4EF70"), 2))
            painter.drawRoundedRect(area.adjusted(1, 1, -1, -1), 8, 8)
        elif self._hovered:
            painter.setPen(QPen(QColor("#D6E8C7"), 1.5))
            painter.drawRoundedRect(area.adjusted(1, 1, -1, -1), 8, 8)
        painter.end()

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)


class KeyboardPreview(QWidget):
    keyEdited = Signal(str, bool)
    editFinished = Signal()

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setMinimumHeight(275)
        self.setAccessibleName("键盘灯效预览")
        self.setMouseTracking(True)
        self._brush = None
        self._hover_key = None

    def _editable(self):
        return self.engine.effect in ("custom_ecg", "custom_canvas", "custom_sparkle")

    def _selected_keys(self):
        if self.engine.effect == "custom_ecg":
            return self.engine.custom_heart_keys
        return self.engine.custom_canvas_keys

    def _transform(self):
        scale = min((self.width() - 28) / 790, (self.height() - 62) / 270)
        x0 = (self.width() - 790 * scale) / 2
        y0 = 42 + (self.height() - 52 - 270 * scale) / 2
        return scale, x0, y0

    def _key_at(self, position):
        scale, x0, y0 = self._transform()
        if scale <= 0:
            return None
        point = QPointF((position.x() - x0) / scale,
                        (position.y() - y0) / scale)
        for cap in KEYCAPS:
            if QRectF(cap.x - 48, cap.y - 43, cap.w, cap.h).contains(point):
                return cap.name if cap.leds else None
        return None

    def _paint_key_at(self, position):
        name = self._key_at(position)
        if name is not None:
            self.keyEdited.emit(name, self._brush)

    def mousePressEvent(self, event):
        if self._editable() and event.button() in (Qt.MouseButton.LeftButton,
                                                     Qt.MouseButton.RightButton):
            name = self._key_at(event.position())
            if name is not None:
                self._brush = (name not in self._selected_keys()
                               if event.button() == Qt.MouseButton.LeftButton else False)
                self._paint_key_at(event.position())
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._editable():
            if self._brush is not None and not event.buttons():
                self._brush = None
                self.editFinished.emit()
            hovered = self._key_at(event.position())
            if hovered != self._hover_key:
                self._hover_key = hovered
                self.setCursor(Qt.CursorShape.CrossCursor if hovered else
                               Qt.CursorShape.ArrowCursor)
                self.update()
            if self._brush is not None:
                self._paint_key_at(event.position())
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._brush is not None and event.button() in (Qt.MouseButton.LeftButton,
                                                           Qt.MouseButton.RightButton):
            self._brush = None
            self.editFinished.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        if self._brush is not None:
            self._brush = None
            self.editFinished.emit()
        self._hover_key = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#303B31"), 1))
        painter.setBrush(QColor("#1D241E"))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 19, 19)
        painter.setPen(QColor("#EAF3DE"))
        painter.setFont(QFont(ui_font(), 10, QFont.Weight.DemiBold))
        painter.drawText(20, 30, f"{getattr(self, 'model', 'V98 Pro')}  /  键位预览")
        painter.setPen(QColor("#A9B5A7"))
        painter.setFont(QFont(ui_font(), 9))
        painter.drawText(self.width() - 166, 30,
                         "点按切换 · 拖动连画" if self._editable() else
                         f"实时灯效 · {len(KEYCAPS)} 键")

        scale, x0, y0 = self._transform()
        painter.save()
        painter.translate(x0, y0)
        painter.scale(scale, scale)
        painter.setPen(QPen(QColor("#39453B"), 1.5))
        painter.setBrush(QColor("#161D18"))
        painter.drawRoundedRect(QRectF(0, 0, 790, 270), 18, 18)
        frame = self.engine.preview_frame()
        label_font = QFont(ui_font())
        label_font.setPixelSize(12)
        label_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(label_font)
        for cap in KEYCAPS:
            cx, cy, cw, ch = cap.x - 48, cap.y - 43, cap.w, cap.h
            colors = [frame[led] for led in cap.leds if led < len(frame)]
            rgb = tuple(round(sum(color[i] for color in colors) / len(colors))
                        for i in range(3)) if colors else (36, 43, 37)
            lit = QColor(*rgb)
            light_share = 0.86 if self.engine.effect in ("audio_ecg", "custom_ecg",
                                                         "custom_canvas",
                                                         "custom_sparkle") else 0.62
            surface = QColor(*(round(28 * (1 - light_share) + c * light_share)
                               for c in rgb))
            painter.setPen(QPen(QColor("#C4EF70") if self._editable() and
                                cap.name == self._hover_key else lit.lighter(125),
                                2 if self._editable() and cap.name == self._hover_key
                                else 1.2))
            key_rect = QRectF(cx, cy, cw, ch)
            led_segments = sorted((LED_CENTERS[led][0], frame[led])
                                  for led in cap.leds
                                  if led in LED_CENTERS and led < len(frame))
            if (cap.name not in ("Space", "Enter", "Num Enter") and
                    len(led_segments) > 1 and
                    led_segments[-1][0] - led_segments[0][0] > 5):
                clip = QPainterPath()
                clip.addRoundedRect(key_rect, 5, 5)
                painter.save()
                painter.setClipPath(clip)
                edges = ([cx] +
                         [(led_segments[i][0] + led_segments[i + 1][0]) / 2 - 48
                          for i in range(len(led_segments) - 1)] +
                         [cx + cw])
                for index, (_, segment_rgb) in enumerate(led_segments):
                    segment_color = QColor(*(
                        round(28 * (1 - light_share) + c * light_share)
                        for c in segment_rgb))
                    painter.fillRect(QRectF(edges[index], cy,
                                            edges[index + 1] - edges[index], ch),
                                     segment_color)
                painter.restore()
                painter.setBrush(Qt.BrushStyle.NoBrush)
            else:
                painter.setBrush(surface)
            painter.drawRoundedRect(key_rect, 5, 5)
            light = sum(rgb) / 3
            painter.setPen(QColor("#172018") if light > 118 else QColor("#E5F0DC"))
            painter.drawText(QRectF(cx + 2, cy + 1, cw - 4, ch - 2),
                             Qt.AlignmentFlag.AlignCenter, cap.label)
        painter.restore()
        painter.end()


class MainWindow(QMainWindow):
    def __init__(self, preview=False):
        super().__init__()
        self.preview_mode = preview
        self.exiting = False
        self.last_connection_error = None
        self.engine = LightingController()
        self.editing_color = None
        self.editing_original = None
        self.settings = read_settings()
        saved_mood = self.settings.get("pairing_mood")
        self.pairing_mood = saved_mood if saved_mood in PAIRING_MOODS else PAIRING_MOODS[0]
        self.inspiration_expanded = bool(self.settings.get("pairings_expanded", False))
        self.profile = self.settings.get("device_profile")
        if not isinstance(self.profile, dict) or not all(
                self.profile.get(field) for field in ("model", "vid", "pid")):
            self.profile = None
        elif self.profile.get("layout"):
            set_keycaps(keycaps_from_profile(self.profile))
        else:
            restore_v98_layout()
        self.engine.base = color_from_setting(self.settings.get("base"), (255, 255, 255))
        self.engine.accent = color_from_setting(self.settings.get("accent"), (0, 0, 0))
        self.engine.global_color = color_from_setting(
            self.settings.get("global_color"), self.engine.base)
        self.engine.ecg_background = color_from_setting(
            self.settings.get("ecg_background"), (255, 255, 255))
        self.engine.brightness = self._clamp(self.settings.get("brightness"), 0.0, 1.0, 0.65)
        self.engine.base_brightness = self._clamp(
            self.settings.get("base_brightness"), 0.0, 1.0, 1.0)
        self.engine.accent_brightness = self._clamp(
            self.settings.get("accent_brightness"), 0.0, 1.0, 1.0)
        self.engine.speed = self._clamp(self.settings.get("speed"), 0.2, 3.0, 1.0)
        self.engine.ripple_width = self._clamp(
            self.settings.get("ripple_width"), 0.5, 2.0, 1.0)
        self.engine.ripples_enabled = bool(self.settings.get("active", True))
        self.engine.effect = self.settings.get("effect") if self.settings.get("effect") in EFFECT_IDS else "ripple"
        available_keys = {cap.name for cap in KEYCAPS if cap.leds}
        for setting, attribute in (("custom_heart_keys", "custom_heart_keys"),
                                   ("custom_canvas_keys", "custom_canvas_keys")):
            saved_keys = self.settings.get(setting, [])
            setattr(self.engine, attribute,
                    set(saved_keys) & available_keys
                    if isinstance(saved_keys, list) else set())
        self._custom_stroke_open = False
        self.effect_palettes = {}
        saved_palettes = self.settings.get("effect_palettes", {})
        if isinstance(saved_palettes, dict):
            for effect_id, palette in saved_palettes.items():
                if effect_id in EFFECT_IDS and isinstance(palette, dict):
                    self.effect_palettes[effect_id] = (
                        color_from_setting(palette.get("base"), self.engine.base),
                        color_from_setting(palette.get("accent"), self.engine.accent))
        if self.engine.effect in self.effect_palettes:
            self.engine.base, self.engine.accent = self.effect_palettes[self.engine.effect]
        self.effect_palettes[self.engine.effect] = (self.engine.base, self.engine.accent)
        self.saved_presets = {}
        raw_presets = self.settings.get("saved_presets", [])
        if isinstance(raw_presets, list):
            for item in raw_presets:
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    name = item["name"].strip()[:24]
                    if name:
                        self.saved_presets[name] = self._normalize_preset(item)
        active = self.settings.get("active_preset")
        self.active_preset = active if active in self.saved_presets else None
        self._updating_controls = False
        self._picker_sync = False
        if self.active_preset:
            self._set_preset_values(self.saved_presets[self.active_preset])
        saved_category = self.settings.get("gallery_category")
        self.gallery_category = (
            saved_category if saved_category in {item[0] for item in CATEGORIES}
            or (saved_category is None and "gallery_category" in self.settings)
            else EFFECT_CATEGORY[self.engine.effect])
        self.engine.preference = self.settings.get("transport") if self.settings.get("transport") in ("auto", "wired", "wireless") else "auto"
        self.engine.last_frame = self.engine.frame(0)

        self.setWindowTitle(f"老必灯 · {self.profile['model'] if self.profile else '键盘灯效工作室'}")
        self.setWindowIcon(QIcon(str(ICON)))
        self.setMinimumSize(900, 620)
        available = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1120, available.width() - 60),
                    min(800, max(620, available.height() - 80)))
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(350)
        self.save_timer.timeout.connect(self._save_settings)
        self._build_ui()
        QApplication.instance().applicationStateChanged.connect(self._application_state_changed)
        self.cancel_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self.cancel_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.cancel_shortcut.activated.connect(self._cancel_color_editor)
        self._build_tray()
        self._build_single_instance_server()
        self._set_dark_title_bar()

        self.frame_timer = QTimer(self)
        self.frame_timer.setInterval(33)
        self.frame_timer.timeout.connect(self._frame_tick)
        self._last_tick_wall = time.time()
        self._last_health_log = self._last_tick_wall
        self.retry_timer = QTimer(self)
        self.retry_timer.setInterval(1200)
        self.retry_timer.timeout.connect(self._connect_device)
        self.mode_timer = QTimer(self)
        self.mode_timer.setInterval(3000)
        self.mode_timer.timeout.connect(self._check_connection_mode)
        if not preview:
            self.frame_timer.start()
            self.mode_timer.start()
            QTimer.singleShot(0, self._connect_device)
            if self.profile is None:
                QTimer.singleShot(0, self._require_setup)
        else:
            self._set_status("界面预览", "paused")

    @staticmethod
    def _clamp(value, low, high, default):
        try:
            return max(low, min(high, float(value)))
        except (TypeError, ValueError):
            return default

    def _normalize_preset(self, item):
        """Keep named presets portable and discard malformed saved fields."""
        return {
            "base": color_hex(color_from_setting(item.get("base"), self.engine.base)),
            "accent": color_hex(color_from_setting(item.get("accent"), self.engine.accent)),
            "global_color": color_hex(color_from_setting(
                item.get("global_color"), self.engine.global_color)),
            "ecg_background": color_hex(color_from_setting(
                item.get("ecg_background"), self.engine.ecg_background)),
            "brightness": self._clamp(item.get("brightness"), 0.0, 1.0,
                                      self.engine.brightness),
            "base_brightness": self._clamp(item.get("base_brightness"), 0.0, 1.0,
                                           self.engine.base_brightness),
            "accent_brightness": self._clamp(item.get("accent_brightness"), 0.0, 1.0,
                                             self.engine.accent_brightness),
            "speed": self._clamp(item.get("speed"), 0.2, 3.0, self.engine.speed),
            "ripple_width": self._clamp(item.get("ripple_width"), 0.5, 2.0,
                                        self.engine.ripple_width),
        }

    def _preset_snapshot(self):
        return self._normalize_preset({
            "base": color_hex(self.engine.base),
            "accent": color_hex(self.engine.accent),
            "global_color": color_hex(self.engine.global_color),
            "ecg_background": color_hex(self.engine.ecg_background),
            "brightness": self.engine.brightness,
            "base_brightness": self.engine.base_brightness,
            "accent_brightness": self.engine.accent_brightness,
            "speed": self.engine.speed,
            "ripple_width": self.engine.ripple_width,
        })

    def _set_preset_values(self, preset):
        for field in ("base", "accent", "global_color", "ecg_background"):
            setattr(self.engine, field, color_from_setting(
                preset[field], getattr(self.engine, field)))
        for field in ("brightness", "base_brightness", "accent_brightness",
                      "speed", "ripple_width"):
            setattr(self.engine, field, preset[field])

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(208)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 24, 18, 20)
        side.setSpacing(8)
        brand = QHBoxLayout()
        brand.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(QIcon(str(ICON)).pixmap(QSize(42, 42)))
        logo.setFixedSize(42, 42)
        brand.addWidget(logo)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        title = QLabel("老必灯")
        title.setObjectName("brandTitle")
        brand_text.addWidget(title)
        subtitle = QLabel("键盘灯效工作室")
        subtitle.setObjectName("brandSub")
        brand_text.addWidget(subtitle)
        brand.addLayout(brand_text)
        side.addLayout(brand)
        side.addSpacing(26)
        side_caption = QLabel("工作区")
        side_caption.setObjectName("sideCaption")
        side.addWidget(side_caption)
        side.addSpacing(5)
        self.nav_buttons = []
        sections = (
            ("灯效画廊", "regular"),
            ("颜色搭配", "palette"),
            ("灯效参数", "sliders"),
            ("我的预设", "save"),
            ("设备与设置", "device"),
        )
        for index, (label, icon_name) in enumerate(sections):
            button = QPushButton(label)
            button.setObjectName("sideNav")
            button.setCheckable(True)
            button.setIcon(control_icon(icon_name))
            button.setIconSize(QSize(19, 19))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, page=index:
                                   self._show_section(page))
            side.addWidget(button)
            self.nav_buttons.append(button)
        side.addStretch()
        side_footer = QLabel("Stt7L  ·  本地运行")
        side_footer.setObjectName("hint")
        side.addWidget(side_footer)
        outer.addWidget(sidebar)

        workspace = QWidget()
        workspace.setObjectName("root")
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        topbar = QFrame()
        topbar.setObjectName("workspaceTopbar")
        topbar_layout = QHBoxLayout(topbar)
        topbar_layout.setContentsMargins(30, 21, 30, 20)
        topbar_layout.setSpacing(16)
        page_heading = QVBoxLayout()
        page_heading.setSpacing(2)
        self.workspace_title = QLabel("灯效画廊")
        self.workspace_title.setObjectName("workspaceTitle")
        page_heading.addWidget(self.workspace_title)
        self.workspace_subtitle = QLabel("预览、选择并调整键盘灯效")
        self.workspace_subtitle.setObjectName("brandSub")
        page_heading.addWidget(self.workspace_subtitle)
        topbar_layout.addLayout(page_heading)
        topbar_layout.addStretch()
        self.status = QLabel("正在连接")
        self.status.setObjectName("statusPaused")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        topbar_layout.addWidget(self.status)
        workspace_layout.addWidget(topbar)

        self.page_stack = QStackedWidget()
        workspace_layout.addWidget(self.page_stack, 1)
        outer.addWidget(workspace, 1)

        def make_page():
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.page_stack.addWidget(scroll)
            body = QWidget()
            body.setObjectName("root")
            scroll.setWidget(body)
            content = QVBoxLayout(body)
            content.setContentsMargins(30, 25, 30, 30)
            content.setSpacing(18)
            return scroll, content

        self.scroll, layout = make_page()
        self.color_scroll, palette_page = make_page()
        self.tuning_scroll, tuning_page = make_page()
        self.presets_scroll, presets_page = make_page()
        self.settings_scroll, settings_page = make_page()

        self.preview = KeyboardPreview(self.engine)
        self.preview.model = self.profile.get("model", "V98 Pro") if self.profile else "V98 Pro"
        self.preview.keyEdited.connect(self._edit_custom_key)
        self.preview.editFinished.connect(self._custom_stroke_finished)
        layout.addWidget(self.preview)

        self.custom_editor_card, custom_layout = self._card("逐键绘制")
        self.custom_editor_hint = QLabel()
        self.custom_editor_hint.setObjectName("hint")
        self.custom_editor_hint.setWordWrap(True)
        custom_layout.addWidget(self.custom_editor_hint)
        custom_actions = QHBoxLayout()
        custom_actions.setSpacing(9)
        for text, handler, style in (("清空画布", self._clear_custom_keys, "secondary"),
                                     ("全部点亮", self._fill_custom_keys, "secondary"),
                                     ("保存图案", self._save_custom_keys, "primary")):
            button = QPushButton(text)
            button.setObjectName(style)
            button.setIcon(control_icon(
                "clear" if text == "清空画布" else
                "regular" if text == "全部点亮" else "save",
                "#1B2615" if style == "primary" else "#D8E4D2"))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(handler)
            custom_actions.addWidget(button, 1)
        custom_layout.addLayout(custom_actions)
        self.custom_editor_status = QLabel()
        self.custom_editor_status.setObjectName("muted")
        custom_layout.addWidget(self.custom_editor_status)
        layout.addWidget(self.custom_editor_card)
        self._refresh_custom_editor()

        effects_card, effects_layout = self._card("灯效画廊")
        effects_hint = QLabel("选择分类与灯效；常用配色和参数可保存为预设")
        effects_hint.setObjectName("muted")
        effects_layout.addWidget(effects_hint)
        gallery_controls = QHBoxLayout()
        self.gallery_selection = QLabel()
        self.gallery_selection.setObjectName("muted")
        gallery_controls.addWidget(self.gallery_selection)
        gallery_controls.addStretch()
        effects_layout.addLayout(gallery_controls)
        category_row = QGridLayout()
        category_row.setHorizontalSpacing(9)
        category_row.setVerticalSpacing(9)
        self.category_buttons = {}
        self.category_panels = {}
        category_grids = {}
        for index, (category, title, subtitle) in enumerate(CATEGORIES):
            count = sum(EFFECT_CATEGORY[item[0]] == category for item in EFFECTS)
            button = QPushButton(f"{title} · {count}")
            button.setObjectName("categoryChoice")
            button.setCheckable(True)
            button.setAccessibleName(f"{title}，{count} 种，点击展开或收起")
            button.setToolTip(subtitle)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setIcon(control_icon(category))
            button.setIconSize(QSize(16, 16))
            button.clicked.connect(lambda _checked=False, chosen=category:
                                   self._toggle_category(chosen))
            category_row.addWidget(button, 0, index)
            self.category_buttons[category] = button
        for column in range(len(CATEGORIES)):
            category_row.setColumnStretch(column, 1)
        effects_layout.addLayout(category_row)
        for category, title, subtitle in CATEGORIES:
            panel = QWidget()
            grid = QGridLayout(panel)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(9)
            grid.setVerticalSpacing(9)
            self.category_panels[category] = panel
            category_grids[category] = grid
            effects_layout.addWidget(panel)
        self.effect_buttons = {}
        category_positions = {category: 0 for category, _, _ in CATEGORIES}
        for effect_id, title, description in EFFECTS:
            button = EffectChoiceButton(title, description)
            button.setObjectName("effectChoice")
            button.setChecked(effect_id == self.engine.effect)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, chosen=effect_id:
                                   self._select_effect(chosen))
            category = EFFECT_CATEGORY[effect_id]
            position = category_positions[category]
            category_positions[category] += 1
            category_grids[category].addWidget(button, position // 3, position % 3)
            self.effect_buttons[effect_id] = button
        self.music_status = QLabel("分析电脑默认播放设备的节奏和频段；不会保存声音")
        self.music_status.setObjectName("hint")
        self.music_status.setWordWrap(True)
        music_status_row = QHBoxLayout()
        music_status_row.addWidget(self.music_status, 1)
        self.audio_refresh = QPushButton("刷新音频设备")
        self.audio_refresh.setObjectName("quiet")
        self.audio_refresh.setIcon(control_icon("refresh"))
        self.audio_refresh.setIconSize(QSize(17, 17))
        self.audio_refresh.clicked.connect(self._refresh_audio_device)
        music_status_row.addWidget(self.audio_refresh)
        effects_layout.addLayout(music_status_row)
        self._refresh_gallery()

        layout.addWidget(effects_card)
        colors_card, colors_layout = self._card("颜色搭配")
        self.palette_hint = QLabel()
        self.palette_hint.setObjectName("muted")
        colors_layout.addWidget(self.palette_hint)
        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self.base_button = QPushButton()
        self.accent_button = QPushButton()
        self.ecg_background_button = QPushButton()
        for button, target in ((self.base_button, "base"),
                               (self.accent_button, "accent"),
                               (self.ecg_background_button, "ecg_background")):
            button.setObjectName("colorTile")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setIconSize(QSize(28, 28))
            button.setAccessibleName(
                "选择心电背景色" if target == "ecg_background" else
                "选择当前灯效的底色" if target == "base" else
                "选择当前灯效的点缀色")
            button.clicked.connect(lambda _checked=False, which=target:
                                   self._open_color_editor(which))
            tiles.addWidget(button, 1)
        colors_layout.addLayout(tiles)
        global_row = QHBoxLayout()
        global_row.setSpacing(12)
        self.global_button = QPushButton()
        self.global_button.setObjectName("colorTile")
        self.global_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.global_button.setIconSize(QSize(28, 28))
        self.global_button.setAccessibleName("选择全局颜色")
        self.global_button.clicked.connect(
            lambda: self._open_color_editor("global_color"))
        global_row.addWidget(self.global_button, 1)
        self.global_apply_button = QPushButton("同步全部底色与点缀色")
        self.global_apply_button.setObjectName("secondary")
        self.global_apply_button.setIcon(control_icon("refresh"))
        self.global_apply_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.global_apply_button.setToolTip("把全局颜色同时同步为全部灯效的底色和点缀色")
        self.global_apply_button.clicked.connect(self._sync_global_color)
        global_row.addWidget(self.global_apply_button)
        colors_layout.addLayout(global_row)
        inspiration_header = QHBoxLayout()
        self.inspiration_toggle = QPushButton()
        self.inspiration_toggle.setObjectName("inspirationToggle")
        self.inspiration_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.inspiration_toggle.clicked.connect(self._toggle_inspiration)
        inspiration_header.addWidget(self.inspiration_toggle)
        inspiration_header.addStretch()
        self.inspiration_note = QLabel("点一下，直接套用")
        self.inspiration_note.setObjectName("muted")
        inspiration_header.addWidget(self.inspiration_note)
        colors_layout.addLayout(inspiration_header)
        self.inspiration_panel = QWidget()
        inspiration_layout = QVBoxLayout(self.inspiration_panel)
        inspiration_layout.setContentsMargins(0, 0, 0, 0)
        inspiration_layout.setSpacing(8)
        inspiration_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        mood_row = QHBoxLayout()
        mood_row.setSpacing(8)
        self.pairing_mood_buttons = {}
        self.pairing_panels = {}
        for mood in PAIRING_MOODS:
            mood_button = QPushButton(mood)
            mood_button.setObjectName("pairingMood")
            mood_button.setCheckable(True)
            mood_button.setCursor(Qt.CursorShape.PointingHandCursor)
            mood_button.clicked.connect(lambda _checked=False, chosen=mood:
                                        self._show_pairing_mood(chosen))
            mood_row.addWidget(mood_button, 1)
            self.pairing_mood_buttons[mood] = mood_button
        inspiration_layout.addLayout(mood_row)
        self.pairing_buttons = []
        for mood in PAIRING_MOODS:
            panel = QWidget()
            pairing_grid = QGridLayout(panel)
            pairing_grid.setContentsMargins(0, 0, 0, 0)
            pairing_grid.setSpacing(8)
            position = 0
            for index, (group, name, base, accent) in enumerate(COLOR_PAIRINGS):
                if group != mood:
                    continue
                button = QPushButton(name)
                button.setObjectName("palettePair")
                button.setCheckable(True)
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.setIcon(pair_swatch_icon(base, accent))
                button.setIconSize(QSize(48, 28))
                button.setToolTip(f"{name} · {color_hex(base)} + {color_hex(accent)}")
                button.setAccessibleName(f"套用{name}配色")
                button.clicked.connect(lambda _checked=False, choice=index:
                                       self._apply_color_pairing(choice))
                pairing_grid.addWidget(button, position // 3, position % 3)
                self.pairing_buttons.append((index, button))
                position += 1
            inspiration_layout.addWidget(panel)
            self.pairing_panels[mood] = panel
        self._show_pairing_mood(self.pairing_mood)
        colors_layout.addWidget(self.inspiration_panel)
        self._set_inspiration_expanded(self.inspiration_expanded)
        self._update_color_buttons()

        self.color_editor = QFrame()
        self.color_editor.setObjectName("inlineEditor")
        editor_layout = QVBoxLayout(self.color_editor)
        editor_layout.setContentsMargins(15, 14, 15, 14)
        editor_layout.setSpacing(10)
        self.editor_title = QLabel("选择颜色")
        self.editor_title.setObjectName("sectionTitle")
        editor_layout.addWidget(self.editor_title)
        color_hint = QLabel("拖动色盘自由选色，也可以输入 HEX 或 RGB 数值")
        color_hint.setObjectName("muted")
        editor_layout.addWidget(color_hint)
        self.color_field = ColorField()
        self.color_field.colorChanged.connect(self._picker_color_changed)
        editor_layout.addWidget(self.color_field)
        self.hue_strip = HueStrip()
        self.hue_strip.hueChanged.connect(self.color_field.setHue)
        editor_layout.addWidget(self.hue_strip)
        preview_row = QHBoxLayout()
        preview_row.setSpacing(12)
        self.color_preview_chip = QFrame()
        self.color_preview_chip.setObjectName("pickerPreview")
        self.color_preview_chip.setFixedSize(50, 50)
        preview_row.addWidget(self.color_preview_chip)
        preview_text = QVBoxLayout()
        preview_text.setSpacing(1)
        preview_caption = QLabel("当前预览")
        preview_caption.setObjectName("muted")
        preview_text.addWidget(preview_caption)
        self.color_preview_label = QLabel("#FFFFFF")
        self.color_preview_label.setObjectName("pickerValue")
        preview_text.addWidget(self.color_preview_label)
        preview_row.addLayout(preview_text)
        preview_row.addStretch()
        editor_layout.addLayout(preview_row)
        precision_row = QHBoxLayout()
        precision_row.setSpacing(9)
        hex_label = QLabel("HEX")
        hex_label.setObjectName("muted")
        precision_row.addWidget(hex_label)
        self.hex_input = QLineEdit()
        self.hex_input.setMaxLength(7)
        self.hex_input.setPlaceholderText("#RRGGBB")
        self.hex_input.setFixedWidth(116)
        self.hex_input.returnPressed.connect(self._apply_color)
        self.hex_input.textEdited.connect(self._hex_changed)
        precision_row.addWidget(self.hex_input)
        self.rgb_inputs = []
        for label in ("R", "G", "B"):
            channel_label = QLabel(label)
            channel_label.setObjectName("muted")
            precision_row.addWidget(channel_label)
            channel = QSpinBox()
            channel.setObjectName("colorChannel")
            channel.setRange(0, 255)
            channel.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            channel.setKeyboardTracking(False)
            channel.setFixedWidth(65)
            channel.setAccessibleName(f"{label} 通道")
            channel.valueChanged.connect(self._rgb_inputs_changed)
            precision_row.addWidget(channel)
            self.rgb_inputs.append(channel)
        precision_row.addStretch()
        editor_layout.addLayout(precision_row)
        self.color_error = QLabel("")
        self.color_error.setStyleSheet("color: #F2B9A9;")
        self.color_error.setMinimumHeight(18)
        editor_layout.addWidget(self.color_error)
        editor_actions = QHBoxLayout()
        editor_actions.setSpacing(8)
        editor_actions.addStretch()
        cancel = QPushButton("取消")
        cancel.setObjectName("quiet")
        cancel.clicked.connect(self._cancel_color_editor)
        editor_actions.addWidget(cancel)
        apply = QPushButton("应用颜色")
        apply.setObjectName("primary")
        apply.clicked.connect(self._apply_color)
        editor_actions.addWidget(apply)
        editor_layout.addLayout(editor_actions)
        colors_layout.addWidget(self.color_editor)
        self.color_editor.hide()
        self._update_palette_hint()
        palette_page.addWidget(colors_card)
        palette_page.addStretch()

        settings_card, settings_layout = self._card("灯效设置")
        self.brightness_slider, self.brightness_value, _ = self._slider_row(
            settings_layout, "整体亮度", 0, 1000,
            round(self.engine.brightness * 1000), "%")
        self.base_brightness_slider, self.base_brightness_value, self.base_brightness_row = self._slider_row(
            settings_layout, "底色亮度", 0, 1000,
            round(self.engine.base_brightness * 1000), "%")
        self.accent_brightness_slider, self.accent_brightness_value, self.accent_brightness_row = self._slider_row(
            settings_layout, "点缀色亮度", 0, 1000,
            round(self.engine.accent_brightness * 1000), "%")
        self.speed_slider, self.speed_value, _ = self._slider_row(
            settings_layout, "动画速度", 200, 3000,
            round(self.engine.speed * 1000), "×")
        self.ripple_width_slider, self.ripple_width_value, self.width_row = self._slider_row(
            settings_layout, "光带宽度", 500, 2000,
            round(self.engine.ripple_width * 1000), "%")
        self.brightness_slider.valueChanged.connect(self._settings_changed)
        self.base_brightness_slider.valueChanged.connect(self._settings_changed)
        self.accent_brightness_slider.valueChanged.connect(self._settings_changed)
        self.speed_slider.valueChanged.connect(self._settings_changed)
        self.ripple_width_slider.valueChanged.connect(self._settings_changed)
        self.width_row.setVisible(self.engine.effect in WIDTH_EFFECTS)
        self._refresh_brightness_labels()
        brightness_hint = QLabel("整体亮度控制全部灯光；底色和点缀色亮度可单独微调")
        brightness_hint.setObjectName("hint")
        settings_layout.insertWidget(1, brightness_hint)
        settings_hint = QLabel("拖动可细调；靠近圆点时轻轻吸附。也可在右侧直接输入数值")
        settings_hint.setObjectName("hint")
        settings_layout.addWidget(settings_hint)
        tuning_page.addWidget(settings_card)
        tuning_page.addStretch()

        presets_card, presets_layout = self._card("我的灯光预设")
        presets_hint = QLabel("保存当前配色与亮度、速度、宽度；应用后切换灯效继续使用")
        presets_hint.setObjectName("muted")
        presets_hint.setWordWrap(True)
        presets_layout.addWidget(presets_hint)
        save_row = QHBoxLayout()
        save_row.setSpacing(9)
        self.preset_name_input = QLineEdit()
        self.preset_name_input.setPlaceholderText("给这套设置起个名字")
        self.preset_name_input.setMaxLength(24)
        self.preset_name_input.setAccessibleName("预设名称")
        self.preset_name_input.returnPressed.connect(self._save_preset)
        save_row.addWidget(self.preset_name_input, 1)
        self.preset_save_button = QPushButton("保存当前设置")
        self.preset_save_button.setObjectName("primary")
        self.preset_save_button.setIcon(control_icon("save", "#1B2615"))
        self.preset_save_button.clicked.connect(self._save_preset)
        save_row.addWidget(self.preset_save_button)
        presets_layout.addLayout(save_row)
        use_row = QHBoxLayout()
        use_row.setSpacing(9)
        self.preset_combo = QComboBox()
        self.preset_combo.setAccessibleName("已保存的灯光预设")
        self.preset_combo.currentIndexChanged.connect(self._preset_selection_changed)
        use_row.addWidget(self.preset_combo, 1)
        self.preset_apply_button = QPushButton("应用预设")
        self.preset_apply_button.setObjectName("secondary")
        self.preset_apply_button.setIcon(control_icon("refresh"))
        self.preset_apply_button.clicked.connect(self._apply_selected_preset)
        use_row.addWidget(self.preset_apply_button)
        self.preset_delete_button = QPushButton("删除")
        self.preset_delete_button.setObjectName("quiet")
        self.preset_delete_button.clicked.connect(self._delete_selected_preset)
        use_row.addWidget(self.preset_delete_button)
        presets_layout.addLayout(use_row)
        self.preset_status = QLabel()
        self.preset_status.setObjectName("hint")
        self.preset_status.setWordWrap(True)
        presets_layout.addWidget(self.preset_status)
        self._refresh_preset_controls(self.active_preset)
        presets_page.addWidget(presets_card)
        presets_page.addStretch()

        connection_card, connection_layout = self._card("连接方式")
        transport_grid = QGridLayout()
        transport_grid.setHorizontalSpacing(9)
        self.transport_buttons = {}
        for column, (mode, name) in enumerate((("auto", "自动选择"),
                                               ("wired", "USB 有线"),
                                               ("wireless", "2.4G 无线"))):
            button = QPushButton(name)
            button.setObjectName("transportChoice")
            button.setCheckable(True)
            button.setChecked(mode == self.engine.preference)
            button.setFixedHeight(46)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, selected=mode:
                                   self._transport_changed(selected))
            transport_grid.addWidget(button, 0, column)
            transport_grid.setColumnStretch(column, 1)
            self.transport_buttons[mode] = button
        connection_layout.addLayout(transport_grid)
        self.connection_detail = QLabel("正在查找灯控接口")
        self.connection_detail.setObjectName("muted")
        connection_layout.addWidget(self.connection_detail)
        bluetooth_note = QLabel("蓝牙模式可使用键盘自带灯效；当前连接未提供可用的逐键 RGB 灯控接口。自定义动画可选 USB 或 2.4G。")
        bluetooth_note.setObjectName("hint")
        bluetooth_note.setWordWrap(True)
        connection_layout.addWidget(bluetooth_note)
        self.wireless_note = QLabel(
            "2.4G 逐键动画受接收器刷新速度限制，涟漪会顿帧。"
            "常亮与缓变效果更适合无线；需要顺滑涟漪可选 USB 有线。")
        self.wireless_note.setObjectName("hint")
        self.wireless_note.setWordWrap(True)
        self.wireless_note.hide()
        connection_layout.addWidget(self.wireless_note)

        self.adapter_toggle = QPushButton("提供其他键盘的适配资料")
        self.adapter_toggle.setObjectName("actionSecondary")
        self.adapter_toggle.setIcon(control_icon("add"))
        self.adapter_toggle.setFixedHeight(46)
        self.adapter_toggle.setCheckable(True)
        self.adapter_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.adapter_toggle.toggled.connect(self._toggle_adapter_panel)
        connection_layout.addWidget(self.adapter_toggle)

        self.adapter_panel = QFrame()
        self.adapter_panel.setObjectName("inlineEditor")
        adapter_layout = QVBoxLayout(self.adapter_panel)
        adapter_layout.setContentsMargins(15, 15, 15, 15)
        adapter_layout.setSpacing(11)
        adapter_intro = QLabel(
            "照片可用于绘制实物键位。逐键灯效还需要设备的灯控协议和 LED 对应关系；"
            "导出资料后可据此制作新型号适配。")
        adapter_intro.setObjectName("hint")
        adapter_intro.setWordWrap(True)
        adapter_layout.addWidget(adapter_intro)
        self.adapter_model = QLineEdit()
        self.adapter_model.setPlaceholderText("键盘品牌与型号，例如：品牌 / 型号 / 版本")
        self.adapter_model.setMaxLength(120)
        self.adapter_model.setAccessibleName("键盘品牌与型号")
        adapter_layout.addWidget(self.adapter_model)
        id_row = QHBoxLayout()
        id_row.setSpacing(9)
        self.adapter_vid = QLineEdit()
        self.adapter_vid.setPlaceholderText("USB VID，4 位十六进制，可选")
        self.adapter_vid.setMaxLength(4)
        self.adapter_vid.setAccessibleName("USB 厂商编号 VID")
        self.adapter_pid = QLineEdit()
        self.adapter_pid.setPlaceholderText("USB PID，4 位十六进制，可选")
        self.adapter_pid.setMaxLength(4)
        self.adapter_pid.setAccessibleName("USB 产品编号 PID")
        id_row.addWidget(self.adapter_vid, 1)
        id_row.addWidget(self.adapter_pid, 1)
        adapter_layout.addLayout(id_row)
        photo_row = QHBoxLayout()
        photo_row.setSpacing(9)
        photo_button = QPushButton("选择键盘照片")
        photo_button.setObjectName("secondary")
        photo_button.setCursor(Qt.CursorShape.PointingHandCursor)
        photo_button.clicked.connect(self._choose_adapter_photo)
        photo_row.addWidget(photo_button)
        self.adapter_photo_label = QLabel("尚未选择照片")
        self.adapter_photo_label.setObjectName("muted")
        photo_row.addWidget(self.adapter_photo_label, 1)
        adapter_layout.addLayout(photo_row)
        self.adapter_photo_path = None
        export_button = QPushButton("导出适配资料")
        export_button.setObjectName("primary")
        export_button.setIcon(control_icon("save", "#1B2615"))
        export_button.setCursor(Qt.CursorShape.PointingHandCursor)
        export_button.clicked.connect(self._export_adapter_request)
        adapter_layout.addWidget(export_button)
        self.adapter_status = QLabel("")
        self.adapter_status.setObjectName("hint")
        self.adapter_status.setWordWrap(True)
        adapter_layout.addWidget(self.adapter_status)
        connection_layout.addWidget(self.adapter_panel)
        self.adapter_panel.hide()

        action_grid = QGridLayout()
        action_grid.setHorizontalSpacing(9)
        for column in range(3):
            action_grid.setColumnStretch(column, 1)
        self.toggle_button = QPushButton()
        self.toggle_button.setObjectName("actionPrimary")
        self.toggle_button.setIcon(control_icon("pause", "#1B2615"))
        self.toggle_button.setFixedHeight(46)
        self.toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_button.clicked.connect(self._toggle_effect)
        action_grid.addWidget(self.toggle_button, 0, 0, 1, 2)
        exit_button = QPushButton("退出程序")
        exit_button.setObjectName("actionSecondary")
        exit_button.setIcon(control_icon("power"))
        exit_button.setFixedHeight(46)
        exit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        exit_button.clicked.connect(self.exit_app)
        action_grid.addWidget(exit_button, 0, 2)
        action_card, action_layout = self._card("快速控制")
        action_layout.addLayout(action_grid)
        layout.addWidget(action_card)
        hint = QLabel("关闭窗口后灯效继续运行。右击托盘图标可退出程序。请勿让其他灯控软件同时控制同一键盘。")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()

        device_card, device_layout = self._card("我的键盘")
        self.profile_summary = QLabel()
        self.profile_summary.setObjectName("muted")
        self.profile_summary.setWordWrap(True)
        device_layout.addWidget(self.profile_summary)
        edit_device = QPushButton("更换型号 / 编辑照片键位")
        edit_device.setObjectName("secondary")
        edit_device.clicked.connect(self._edit_device_profile)
        device_layout.addWidget(edit_device)
        settings_page.addWidget(device_card)
        settings_page.addWidget(connection_card)
        startup_card, startup_layout = self._card("启动与后台")
        startup_note = QLabel("登录 Windows 后自动运行，灯效在托盘中持续工作。")
        startup_note.setObjectName("muted")
        startup_layout.addWidget(startup_note)
        self.startup_button = SwitchButton("开机自启")
        self.startup_button.setObjectName("startupToggle")
        self.startup_button.setCheckable(True)
        self.startup_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.startup_button.clicked.connect(self._startup_toggled)
        startup_layout.addWidget(self.startup_button)
        self.startup_status = QLabel()
        self.startup_status.setObjectName("hint")
        startup_layout.addWidget(self.startup_status)
        settings_page.addWidget(startup_card)
        self._refresh_startup_control()
        author_card, author_layout = self._card("关于老必灯")
        author = QLabel("作者  Stt7L")
        author.setObjectName("muted")
        author_layout.addWidget(author)
        font_notice = QLabel("界面使用 HarmonyOS Sans 字体 · © 2021 Huawei Device Co., Ltd.")
        font_notice.setObjectName("muted")
        author_layout.addWidget(font_notice)
        font_license = QPushButton("HarmonyOS Sans 字体许可")
        font_license.setObjectName("galleryToggle")
        font_license.setIcon(control_icon("external"))
        font_license.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(
            "https://github.com/openharmony/global_system_resources/blob/master/LICENSE_Fonts"
        )))
        author_layout.addWidget(font_license)
        github_button = QPushButton("GitHub 项目")
        github_button.setObjectName("galleryToggle")
        github_button.setIcon(control_icon("external"))
        github_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(PROJECT_URL)))
        author_layout.addWidget(github_button)
        settings_page.addWidget(author_card)
        settings_page.addStretch()
        self._refresh_profile_summary()
        self._refresh_toggle_labels()
        self._show_section(0)
        for button in self.findChildren(QPushButton):
            button.setCursor(Qt.CursorShape.PointingHandCursor)

    def _show_section(self, index):
        section_titles = (
            ("灯效画廊", "预览、选择并调整键盘灯效"),
            ("颜色搭配", "让灯光呈现你喜欢的配色"),
            ("灯效参数", "亮度、速度和光带宽度"),
            ("我的预设", "保存并复用你的灯光方案"),
            ("设备与设置", "键盘、连接方式与后台运行"),
        )
        self.page_stack.setCurrentIndex(index)
        self.workspace_title.setText(section_titles[index][0])
        self.workspace_subtitle.setText(section_titles[index][1])
        for page, button in enumerate(self.nav_buttons):
            button.setChecked(page == index)

    def _card(self, title):
        card = QFrame()
        card.setObjectName("surface")
        content = QVBoxLayout(card)
        content.setContentsMargins(21, 19, 21, 21)
        content.setSpacing(16)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        content.addWidget(heading)
        return card, content

    def _refresh_startup_control(self):
        available = startup_command() is not None
        enabled = startup_enabled()
        self.startup_button.setEnabled(available)
        self.startup_button.setChecked(enabled)
        self.startup_button.setText("开机自启")
        self.startup_status.setText(
            "下次登录后自动在托盘运行" if enabled else
            "安装老必灯后可使用" if not available else
            "当前不会随 Windows 登录自动启动")

    def _startup_toggled(self, enabled):
        try:
            set_startup_enabled(enabled)
        except OSError as error:
            LOG.warning("Could not change startup preference: %s", error)
            self.startup_status.setText(f"设置失败：{error}")
            self.startup_button.setChecked(not enabled)
            return
        self._refresh_startup_control()
        LOG.info("Start with Windows: %s", enabled)

    def _slider_row(self, parent, label, low, high, value, unit):
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(18)
        name = QLabel(label)
        name.setObjectName("muted")
        name.setFixedWidth(102)
        container.name_label = name
        row.addWidget(name)
        slider = FineSlider()
        slider.setRange(low, high)
        slider.setSnapValues(
            [200, 500, 1000, 1500, 2000, 2500, 3000]
            if unit == "×" else
            range(low, high + 1, 250 if low == 500 else 100))
        slider.setValue(value)
        slider.setAccessibleName(label)
        row.addWidget(slider, 1)
        display = NoWheelSpinBox()
        display.setObjectName("settingValue")
        display.setRange(low / (10 if unit == "%" else 1000),
                         high / (10 if unit == "%" else 1000))
        display.setDecimals(1 if unit == "%" else 3)
        display.setSingleStep(0.1 if unit == "%" else 0.01)
        display.setSuffix("%" if unit == "%" else "×")
        display.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        display.setKeyboardTracking(False)
        display.setFixedSize(94, 38)
        display.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        display.setValue(value / (10 if unit == "%" else 1000))
        display.setAccessibleName(f"{label}数值")
        display.valueChanged.connect(
            lambda number: slider.setValue(round(number * (10 if unit == "%" else 1000))))
        row.addWidget(display)
        parent.addWidget(container)
        return slider, display, container

    def _build_tray(self):
        self.tray = None
        if self.preview_mode or not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(QIcon(str(ICON)), self)
        self.tray.setToolTip("老必灯 · 键盘灯效工作室")
        self.tray_menu = QMenu(self)
        show_action = self.tray_menu.addAction("显示窗口")
        show_action.triggered.connect(self.show_window)
        self.tray_toggle_action = self.tray_menu.addAction("")
        self.tray_toggle_action.triggered.connect(self._toggle_effect)
        self.tray_menu.addSeparator()
        quit_action = self.tray_menu.addAction("退出程序")
        quit_action.triggered.connect(self.exit_app)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()
        LOG.info("System tray visible with show, toggle and exit actions")
        self._refresh_toggle_labels()

    def _build_single_instance_server(self):
        self.server = None
        if self.preview_mode:
            return
        self.server = QLocalServer(self)
        QLocalServer.removeServer(SERVER_NAME)
        self.server.newConnection.connect(self._second_launch)
        if not self.server.listen(SERVER_NAME):
            LOG.warning("Local server unavailable: %s", self.server.errorString())

    def _second_launch(self):
        while self.server.hasPendingConnections():
            connection = self.server.nextPendingConnection()
            connection.disconnectFromServer()
            connection.deleteLater()
        self.show_window()

    def _set_dark_title_bar(self):
        try:
            hwnd = int(self.winId())
            value = ctypes.c_int(1)
            dwm = ctypes.WinDLL("dwmapi", use_last_error=True)
            dwm.DwmSetWindowAttribute.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                                   ctypes.c_void_p, ctypes.c_uint]
            dwm.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
        except (AttributeError, OSError):
            pass

    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_window()

    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        if self.editing_color is not None:
            self._application_state_changed(Qt.ApplicationState.ApplicationInactive)
        if self.exiting:
            event.accept()
        elif self.tray is None:
            self.exit_app()
            event.accept()
        else:
            event.ignore()
            self.hide()
            LOG.info("Window hidden to tray; lighting remains active")

    def _application_state_changed(self, state):
        if state != Qt.ApplicationState.ApplicationActive and self.editing_color is not None:
            if not re.fullmatch(r"#[0-9A-Fa-f]{6}", self.hex_input.text().strip()):
                current = getattr(self.engine, self.editing_color)
                self.hex_input.setText(color_hex(current))
            self._apply_color()

    def _connect_device(self):
        if self.engine.connected or self.preview_mode or self.profile is None:
            return
        if not is_supported_v98(self.profile):
            self.engine.preview_events = True
            if self.engine.ripples_enabled and self.engine.effect in REACTIVE:
                try:
                    self.engine._install_hook()
                except OSError as error:
                    LOG.warning("Preview keyboard hook unavailable: %s", error)
            self.retry_timer.stop()
            self.wireless_note.hide()
            self.connection_detail.setText("该型号尚无实物灯控适配 · 可使用本地键位与动画预览")
            self._set_status("仅屏幕预览", "paused")
            return
        self.engine.preview_events = False
        try:
            self.engine.connect()
        except Exception as error:
            self.wireless_note.hide()
            if str(error) != self.last_connection_error:
                LOG.warning("Keyboard connection failed: %s", error)
                self.last_connection_error = str(error)
            if "蓝牙连接" in str(error):
                self._set_status("蓝牙不支持自定义灯效", "paused")
            else:
                self._set_status("键盘未连接，正在重试", "error")
            self.connection_detail.setText(str(error))
            self.retry_timer.start()
            return
        self.retry_timer.stop()
        self.last_connection_error = None
        transport = "2.4G 接收器" if self.engine.transport == "wireless" else "USB 有线"
        self.connection_detail.setText(
            "已连接 · 2.4G（约 5 帧/秒）" if self.engine.transport == "wireless"
            else "已连接 · USB 有线")
        self.wireless_note.setVisible(self.engine.transport == "wireless")
        LOG.info("Keyboard connected via %s; lighting active=%s", transport, self.engine.ripples_enabled)
        self._set_status("灯效运行中" if self.engine.ripples_enabled else "灯效已暂停",
                         "running" if self.engine.ripples_enabled else "paused")
        self.preview.update()

    def _check_connection_mode(self):
        if self.engine.transport != "wireless":
            return
        if bluetooth_keyboard_present():
            self.engine.disconnect()
            self.wireless_note.hide()
            LOG.info("Keyboard switched to Bluetooth; custom lighting paused")
            self.connection_detail.setText("键盘已切到蓝牙模式")
            self._set_status("蓝牙不支持自定义灯效", "paused")
            self.retry_timer.start()

    def _frame_tick(self):
        wall_now = time.time()
        tick_gap = wall_now - self._last_tick_wall
        self._last_tick_wall = wall_now
        if tick_gap > 8.0 and not self.preview_mode:
            LOG.warning("Lighting timer paused for %.1f s; refreshing keyboard connection", tick_gap)
            self.engine.disconnect()
            if self.engine.effect in MUSIC:
                self.engine.audio_meter.refresh()
            self._set_status("正在恢复键盘连接", "paused")
            self.connection_detail.setText("电脑恢复运行，正在重新连接灯控接口")
            self._connect_device()
            if not self.engine.connected:
                self.retry_timer.start()
            return
        interval = (20 if self.engine.effect in MUSIC and
                    self.engine.transport == "wired" else 33)
        if self.frame_timer.interval() != interval:
            self.frame_timer.setInterval(interval)
        try:
            self.engine.tick()
        except OSError as error:
            LOG.warning("Lighting stream interrupted: %s", error)
            self._set_status("连接中断，正在重试", "error")
            self.connection_detail.setText("连接中断，正在重新寻找键盘")
            self.retry_timer.start()
            QTimer.singleShot(0, self._connect_device)
        if wall_now - self._last_health_log >= 60.0:
            self._last_health_log = wall_now
            lit_keys = sum(any(channel for channel in rgb)
                           for rgb in self.engine.last_frame)
            LOG.info("Lighting health: connected=%s transport=%s effect=%s audio=%s level=%.3f lit=%s active=%s",
                     self.engine.connected, self.engine.transport, self.engine.effect,
                     self.engine.audio_meter.mode, self.engine.audio_level,
                     lit_keys, self.engine.ripples_enabled)
        self.preview.update()
        if self.gallery_category == "music" or self.engine.effect == "custom_ecg":
            meter = self.engine.audio_meter
            self.music_status.setText(
                "播放设备已接入 · 低频 / 中频 / 高频实时响应 · 不保存声音"
                if meter.mode == "spectrum" else
                "仅音量响应 · 频段分析正在连接" if meter.available else
                "等待默认播放设备的声音；请播放音乐后查看灯光变化" if not meter.error else
                f"音频暂不可用：{meter.error}")

    def _set_status(self, text, kind):
        self.status.setText(text)
        self.status.setObjectName({"running": "statusRunning",
                                   "paused": "statusPaused",
                                   "error": "statusError"}[kind])
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _refresh_toggle_labels(self):
        active = self.engine.ripples_enabled
        self.toggle_button.setText("暂停灯效" if active else "继续灯效")
        self.toggle_button.setIcon(control_icon(
            "pause" if active else "play", "#1B2615"))
        if hasattr(self, "tray_toggle_action"):
            self.tray_toggle_action.setText("暂停灯效" if active else "继续灯效")

    def _toggle_effect(self):
        active = not self.engine.ripples_enabled
        try:
            self.engine.set_active(active)
        except OSError as error:
            LOG.warning("Keyboard hook unavailable: %s", error)
            self._set_status("按键监听不可用", "error")
            return
        self._refresh_toggle_labels()
        if self.engine.connected:
            self._set_status("灯效运行中" if active else "灯效已暂停",
                             "running" if active else "paused")
        self._save_settings()

    def _custom_key_set(self):
        if self.engine.effect == "custom_ecg":
            return self.engine.custom_heart_keys
        if self.engine.effect in ("custom_canvas", "custom_sparkle"):
            return self.engine.custom_canvas_keys
        return None

    def _refresh_custom_editor(self):
        selected = self._custom_key_set()
        self.custom_editor_card.setVisible(selected is not None)
        if selected is None:
            self.preview._hover_key = None
            self.preview.setCursor(Qt.CursorShape.ArrowCursor)
            return
        if self.engine.effect == "custom_ecg":
            hint = "心电线由音乐生成。左键点按切换爱心键，拖动会沿用起点的涂画或擦除；右键始终擦除。未选键保持白色。"
        elif self.engine.effect == "custom_sparkle":
            hint = "左键点按切换闪烁键，拖动会沿用起点的涂画或擦除；右键始终擦除。其余键保持底色。"
        else:
            hint = "左键点按切换点缀色，拖动会沿用起点的涂画或擦除；右键始终擦除。其余键保持底色。"
        self.custom_editor_hint.setText(hint + " 无可控灯位的按键无法涂画。")
        self.custom_editor_status.setText(
            f"已选 {len(selected)} 键 · 绘制完成后自动保存")

    def _edit_custom_key(self, name, enabled):
        selected = self._custom_key_set()
        if selected is None or (name in selected) == enabled:
            return
        self._custom_stroke_open = True
        if enabled:
            selected.add(name)
        else:
            selected.discard(name)
        self.engine.last_frame = self.engine.frame(time.perf_counter())
        self.preview.update()
        self._refresh_custom_editor()

    def _custom_stroke_finished(self):
        if self._custom_stroke_open:
            self._custom_stroke_open = False
            self._save_settings()

    def _clear_custom_keys(self):
        selected = self._custom_key_set()
        if selected is None or not selected:
            return
        selected.clear()
        self.engine.last_frame = self.engine.frame(time.perf_counter())
        self.preview.update()
        self._refresh_custom_editor()
        self._save_settings()

    def _fill_custom_keys(self):
        selected = self._custom_key_set()
        if selected is None:
            return
        available = {cap.name for cap in KEYCAPS if cap.leds}
        if selected == available:
            return
        selected.clear()
        selected.update(available)
        self.engine.last_frame = self.engine.frame(time.perf_counter())
        self.preview.update()
        self._refresh_custom_editor()
        self._save_settings()

    def _save_custom_keys(self):
        if self._custom_key_set() is None:
            return
        self._save_settings()
        self.custom_editor_status.setText(
            f"已保存 · 当前选择 {len(self._custom_key_set())} 个键位")

    def _select_effect(self, effect):
        if effect == self.engine.effect:
            return
        self._cancel_color_editor()
        if self.active_preset:
            palette = (self.engine.base, self.engine.accent)
        else:
            self.effect_palettes[self.engine.effect] = (
                self.engine.base, self.engine.accent)
            palette = self.effect_palettes.get(effect)
            if palette is None:
                palette = self._default_palette(effect)
                self.effect_palettes[effect] = palette
        self.engine.set_effect(effect)
        self.engine.base, self.engine.accent = palette
        self.width_row.setVisible(effect in WIDTH_EFFECTS)
        self._refresh_brightness_labels()
        for effect_id, button in self.effect_buttons.items():
            button.setChecked(effect_id == effect)
        self._update_color_buttons()
        self._update_palette_hint()
        self._refresh_gallery()
        self._refresh_custom_editor()
        self.engine.last_frame = self.engine.frame(time.perf_counter())
        self.preview.update()
        self._save_settings()
        if self._custom_key_set() is not None:
            QTimer.singleShot(0, lambda: self.scroll.ensureWidgetVisible(
                self.custom_editor_card))

    def _default_palette(self, effect):
        if effect in ("audio_ecg", "custom_ecg"):
            return (255, 81, 177), (255, 64, 91)
        if effect in ("custom_canvas", "custom_sparkle"):
            return (255, 255, 255), (255, 64, 91)
        accent = (self.engine.accent if self.engine.accent != (0, 0, 0)
                  or effect == "ripple" else (196, 239, 112))
        return self.engine.base, accent

    def _sync_global_color(self):
        if self.editing_color == "global_color":
            self._apply_color()
            if self.editing_color is not None:
                return
        else:
            self._cancel_color_editor()
        self._detach_active_preset()
        for effect_id in EFFECT_IDS:
            self.effect_palettes[effect_id] = (
                self.engine.global_color, self.engine.global_color)
        self.engine.base = self.engine.global_color
        self.engine.accent = self.engine.global_color
        self._update_color_buttons()
        self._update_palette_hint()
        self.engine.last_frame = self.engine.frame(time.perf_counter())
        self.preview.update()
        self.preset_status.setText("全局颜色已同步到全部灯效的底色和点缀色")
        self._save_settings()

    def _refresh_gallery(self):
        title = next(title for effect_id, title, _ in EFFECTS
                     if effect_id == self.engine.effect)
        self.gallery_selection.setText(f"当前 · {title}")
        for category, category_title, _ in CATEGORIES:
            open_now = category == self.gallery_category
            button = self.category_buttons[category]
            button.setChecked(open_now)
            button.setIcon(control_icon(category, "#C4EF70" if open_now else "#AEBCAA"))
            self.category_panels[category].setVisible(open_now)
        audio_visible = (self.gallery_category == "music" or
                         self.engine.effect == "custom_ecg")
        self.music_status.setVisible(audio_visible)
        self.audio_refresh.setVisible(audio_visible)

    def _refresh_audio_device(self):
        self.engine.audio_meter.refresh()
        self.music_status.setText("正在连接系统默认播放设备…")

    def _toggle_category(self, category):
        self.gallery_category = None if self.gallery_category == category else category
        self._refresh_gallery()
        self._save_settings()

    def _update_palette_hint(self):
        if self.engine.effect == "ripple":
            hint = "底色控制常亮区域，波纹色控制按键后扩散的光。"
        elif self.engine.effect == "audio_ecg":
            hint = "心电线随音乐起伏，背景色可单独选择；按键预览保持只读。"
        elif self.engine.effect == "custom_ecg":
            hint = "心电线随音乐起伏；背景色可单独选择，爱心键可在预览中绘制。"
        elif self.engine.effect in ("custom_canvas", "custom_sparkle"):
            hint = "在上方键位预览涂画；底色和所选键的点缀色可分别调整。"
        elif self.engine.effect == "solid":
            hint = "全键常亮只使用底色。"
        elif self.engine.effect in MUSIC:
            hint = "灯光跟随默认播放设备的节奏与频段；可分别调整底色和点缀色。"
        else:
            hint = "点击色块打开 RGB 色盘；每款灯效会记住自己的配色。"
        self.palette_hint.setText(hint)

    def _transport_changed(self, preference):
        if preference == self.engine.preference:
            self.transport_buttons[preference].setChecked(True)
            return
        self.engine.preference = preference
        for mode, button in self.transport_buttons.items():
            button.setChecked(mode == preference)
        if self.preview_mode:
            return
        self.engine.disconnect()
        self.wireless_note.hide()
        self.connection_detail.setText("正在切换连接方式")
        self._set_status("正在连接", "paused")
        self._connect_device()
        self._save_settings()

    def _toggle_adapter_panel(self, expanded):
        self.adapter_panel.setVisible(expanded)
        self.adapter_toggle.setText(
            "收起适配资料" if expanded else "＋  提供其他键盘的适配资料")

    def _require_setup(self):
        try:
            detected = preferred_known_keyboard(detect_keyboards(), self.engine.preference)
        except OSError as error:
            LOG.warning("Keyboard identity scan failed: %s", error)
            detected = None
        if detected:
            LOG.info("Known keyboard auto-detected: %s:%s", detected["vid"], detected["pid"])
            self._apply_device_profile({key: detected[key] for key in ("model", "vid", "pid")})
            return
        dialog = DeviceSetupDialog(DATA_DIR, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._apply_device_profile(dialog.result_profile)
        else:
            self.exit_app()

    def _edit_device_profile(self):
        dialog = DeviceSetupDialog(DATA_DIR, current=self.profile, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._apply_device_profile(dialog.result_profile)

    def _apply_device_profile(self, profile):
        self.engine.disconnect()
        self.engine.preview_events = False
        self.profile = profile
        self.setWindowTitle(f"老必灯 · {profile['model']}")
        caps = keycaps_from_profile(profile)
        if caps:
            set_keycaps(caps)
        else:
            restore_v98_layout()
        self.engine.ripples.clear()
        self.engine.last_frame = self.engine.frame(time.perf_counter())
        self.preview.model = profile["model"]
        self.preview.update()
        self._refresh_profile_summary()
        self._save_settings()
        self._connect_device()

    def _refresh_profile_summary(self):
        if self.profile is None:
            self.profile_summary.setText("尚未确认键盘型号和设备编号")
            return
        supported = "实物逐键灯效已适配" if is_supported_v98(self.profile) else "键位和动画可本地预览 · 实物灯控待适配"
        self.profile_summary.setText(
            f"{self.profile['model']}  ·  {self.profile['vid']}:{self.profile['pid']}\n"
            f"{len(KEYCAPS)} 个键位  ·  {supported}")

    def _choose_adapter_photo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择键盘实物照片", str(Path.home()),
            "图片文件 (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self.adapter_photo_path = Path(path)
            self.adapter_photo_label.setText(self.adapter_photo_path.name)
            self.adapter_status.clear()

    def _export_adapter_request(self):
        model = self.adapter_model.text().strip()
        photo = self.adapter_photo_path
        if not model and photo is None:
            self.adapter_status.setText("请填写型号，或选择一张键盘照片。")
            return
        vid = self.adapter_vid.text().strip().upper()
        pid = self.adapter_pid.text().strip().upper()
        if any(value and not re.fullmatch(r"[0-9A-F]{4}", value)
               for value in (vid, pid)):
            self.adapter_status.setText("VID 和 PID 请填写 4 位十六进制字符，或留空。")
            return
        if photo is not None and not photo.is_file():
            self.adapter_status.setText("所选照片已不存在，请重新选择。")
            return
        safe_name = re.sub(r'[<>:"/\\|?*]+', "_", model or "未知型号").strip(" ._")[:60] or "未知型号"
        desktop = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DesktopLocation) or str(Path.home())
        default_path = str(Path(desktop) / f"老必灯-适配资料-{safe_name}.zip")
        destination, _ = QFileDialog.getSaveFileName(
            self, "导出键盘适配资料", default_path, "ZIP 压缩包 (*.zip)")
        if not destination:
            return
        output = Path(destination)
        if output.suffix.lower() != ".zip":
            output = output.with_suffix(".zip")
        photo_name = f"keyboard-photo{photo.suffix.lower()}" if photo else None
        request = {
            "application": "老必灯",
            "model": model,
            "usb_vid": vid,
            "usb_pid": pid,
            "photo": photo_name,
            "purpose": "keyboard_layout_and_lighting_adapter_request",
        }
        try:
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("适配资料.json", json.dumps(request, ensure_ascii=False, indent=2))
                if photo is not None:
                    archive.write(photo, photo_name)
        except OSError as error:
            self.adapter_status.setText(f"保存失败：{error}")
            return
        self.adapter_status.setText(
            f"已保存到 {output}。提供这份资料后，可先校准键位和灯珠，再制作灯控适配。")

    def _refresh_preset_controls(self, select_name=None, message=None):
        selected = select_name or self.preset_combo.currentData()
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItem("选择已保存的预设", None)
        for name in self.saved_presets:
            self.preset_combo.addItem(name, name)
        index = self.preset_combo.findData(selected)
        self.preset_combo.setCurrentIndex(max(0, index))
        self.preset_combo.blockSignals(False)
        self._preset_selection_changed()
        if message is not None:
            self.preset_status.setText(message)
        elif self.active_preset:
            self.preset_status.setText(f"正在使用「{self.active_preset}」· 切换灯效仍沿用")
        else:
            self.preset_status.setText("调整后可保存为预设；同名保存会更新原预设")

    def _preset_selection_changed(self):
        has_selection = self.preset_combo.currentData() in self.saved_presets
        self.preset_apply_button.setEnabled(has_selection)
        self.preset_delete_button.setEnabled(has_selection)

    def _detach_active_preset(self):
        if self.active_preset is None:
            return
        former = self.active_preset
        self.active_preset = None
        self.effect_palettes[self.engine.effect] = (
            self.engine.base, self.engine.accent)
        self._refresh_preset_controls(
            former, "已调整当前设置；保存的预设仍保留原样")

    def _save_preset(self):
        name = self.preset_name_input.text().strip()
        if not name:
            self.preset_status.setText("请先输入预设名称")
            self.preset_name_input.setFocus()
            return
        if self.editing_color is not None:
            self._apply_color()
            if self.editing_color is not None:
                return
        existed = name in self.saved_presets
        self.saved_presets[name] = self._preset_snapshot()
        self.active_preset = name
        self._refresh_preset_controls(
            name, f"已{'更新' if existed else '保存'}「{name}」· 可用于所有灯效")
        self._save_settings()

    def _apply_selected_preset(self):
        name = self.preset_combo.currentData()
        if name not in self.saved_presets:
            return
        self._cancel_color_editor()
        self.active_preset = name
        self._set_preset_values(self.saved_presets[name])
        self._refresh_setting_controls()
        self._update_color_buttons()
        self._update_palette_hint()
        self.engine.last_frame = self.engine.frame(time.perf_counter())
        self.preview.update()
        self._refresh_preset_controls(
            name, f"正在使用「{name}」· 切换灯效仍沿用")
        self._save_settings()

    def _delete_selected_preset(self):
        name = self.preset_combo.currentData()
        if name not in self.saved_presets:
            return
        if self.active_preset == name:
            self._detach_active_preset()
        del self.saved_presets[name]
        self._refresh_preset_controls(
            message=f"已删除「{name}」；当前灯光保持原样")
        self._save_settings()

    def _refresh_setting_controls(self):
        self._updating_controls = True
        try:
            for slider, display, value, percent in (
                    (self.brightness_slider, self.brightness_value,
                     self.engine.brightness, True),
                    (self.base_brightness_slider, self.base_brightness_value,
                     self.engine.base_brightness, True),
                    (self.accent_brightness_slider, self.accent_brightness_value,
                     self.engine.accent_brightness, True),
                    (self.speed_slider, self.speed_value, self.engine.speed, False),
                    (self.ripple_width_slider, self.ripple_width_value,
                     self.engine.ripple_width, True)):
                slider.setValue(round(value * 1000))
                display.setValue(value * 100 if percent else value)
        finally:
            self._updating_controls = False

    def _refresh_brightness_labels(self):
        effect = self.engine.effect
        base_label = ("心电线亮度" if effect in ("audio_ecg", "custom_ecg")
                      else "底色亮度")
        accent_label = ("爱心亮度" if effect == "custom_ecg" else
                        "波纹亮度" if effect == "ripple" else "点缀色亮度")
        self.base_brightness_row.name_label.setText(base_label)
        self.base_brightness_slider.setAccessibleName(base_label)
        self.base_brightness_value.setAccessibleName(f"{base_label}数值")
        self.accent_brightness_row.name_label.setText(accent_label)
        self.accent_brightness_slider.setAccessibleName(accent_label)
        self.accent_brightness_value.setAccessibleName(f"{accent_label}数值")
        self.accent_brightness_row.setVisible(effect not in ("audio_ecg", "solid"))

    def _settings_changed(self):
        if self._updating_controls:
            return
        self._detach_active_preset()
        brightness = self.brightness_slider.value()
        base_brightness = self.base_brightness_slider.value()
        accent_brightness = self.accent_brightness_slider.value()
        speed = self.speed_slider.value()
        ripple_width = self.ripple_width_slider.value()
        self.engine.brightness = brightness / 1000
        self.engine.base_brightness = base_brightness / 1000
        self.engine.accent_brightness = accent_brightness / 1000
        self.engine.speed = speed / 1000
        self.engine.ripple_width = ripple_width / 1000
        self.brightness_value.setValue(brightness / 10)
        self.base_brightness_value.setValue(base_brightness / 10)
        self.accent_brightness_value.setValue(accent_brightness / 10)
        self.speed_value.setValue(speed / 1000)
        self.ripple_width_value.setValue(ripple_width / 10)
        self.engine.last_frame = self.engine.frame(time.perf_counter())
        self.preview.update()
        if not self.preview_mode:
            self.save_timer.start()

    def _update_color_buttons(self):
        base_label = "心电线" if self.engine.effect in ("audio_ecg", "custom_ecg") else "底色"
        accent_label = ("爱心色" if self.engine.effect == "custom_ecg" else
                        "波纹色" if self.engine.effect == "ripple" else "点缀色")
        for button, label, value in ((self.base_button, base_label, self.engine.base),
                                     (self.accent_button, accent_label, self.engine.accent),
                                     (self.global_button, "全局颜色", self.engine.global_color),
                                     (self.ecg_background_button, "心电背景色",
                                      self.engine.ecg_background)):
            button.setIcon(swatch_icon(value))
            button.setText(f"{label}    {color_hex(value)}")
        self.accent_button.setVisible(self.engine.effect not in ("audio_ecg", "solid"))
        self.ecg_background_button.setVisible(
            self.engine.effect in ("audio_ecg", "custom_ecg"))
        self.inspiration_note.setText(
            "第二色会作为背景" if self.engine.effect == "audio_ecg"
            else "全键常亮只使用第一色" if self.engine.effect == "solid"
            else "点一下，直接套用")
        for index, button in self.pairing_buttons:
            _, _, base, accent = COLOR_PAIRINGS[index]
            second = (self.engine.ecg_background if self.engine.effect == "audio_ecg"
                      else self.engine.accent)
            button.setChecked(self.engine.base == base and second == accent)

    def _show_pairing_mood(self, mood):
        self.pairing_mood = mood
        for name, button in self.pairing_mood_buttons.items():
            button.setChecked(name == mood)
            self.pairing_panels[name].setVisible(name == mood)
        if hasattr(self, "frame_timer"):
            self._save_settings()

    def _set_inspiration_expanded(self, expanded):
        self.inspiration_expanded = bool(expanded)
        self.inspiration_panel.setVisible(self.inspiration_expanded)
        self.inspiration_note.setVisible(self.inspiration_expanded)
        self.inspiration_toggle.setIcon(chevron_icon(up=self.inspiration_expanded))
        self.inspiration_toggle.setText(f"配色灵感 · {len(COLOR_PAIRINGS)} 组")
        self.inspiration_toggle.setAccessibleName(
            "收起配色灵感" if self.inspiration_expanded else "展开配色灵感")

    def _toggle_inspiration(self):
        self._set_inspiration_expanded(not self.inspiration_expanded)
        self._save_settings()

    def _apply_color_pairing(self, index):
        _, name, base, accent = COLOR_PAIRINGS[index]
        self._cancel_color_editor()
        self._detach_active_preset()
        self.engine.base = base
        if self.engine.effect == "audio_ecg":
            self.engine.ecg_background = accent
        else:
            self.engine.accent = accent
        self.effect_palettes[self.engine.effect] = (
            self.engine.base, self.engine.accent)
        self.engine.last_frame = self.engine.frame(time.perf_counter())
        self._update_color_buttons()
        self.inspiration_note.setText(f"已套用「{name}」")
        self.preview.update()
        self._save_settings()

    def _open_color_editor(self, target):
        if self.editing_color is not None:
            self._cancel_color_editor()
        self.editing_color = target
        self.editing_original = {
            field: getattr(self.engine, field)
            for field in ("base", "accent", "global_color", "ecg_background")}
        self.editor_title.setText(
            "修改心电线颜色" if target == "base" and self.engine.effect in
            ("audio_ecg", "custom_ecg") else
            "修改底色" if target == "base" else
            "修改全局颜色" if target == "global_color" else
            "修改心电背景色" if target == "ecg_background" else
            "修改爱心颜色" if self.engine.effect == "custom_ecg" else
            "修改波纹色" if self.engine.effect == "ripple" else "修改点缀色")
        self._set_picker_color(QColor(*getattr(self.engine, target)))
        self.color_error.clear()
        self.color_editor.show()
        self.color_field.setFocus()
        self._show_section(1)
        QTimer.singleShot(0, lambda: self.color_scroll.ensureWidgetVisible(self.color_editor))

    def _set_picker_color(self, color, update_hex=True):
        if not color.isValid():
            return
        self._picker_sync = True
        try:
            self.color_field.setColor(color)
            self.hue_strip.setHue(self.color_field.hue)
            for channel, number in zip(self.rgb_inputs,
                                       (color.red(), color.green(), color.blue())):
                channel.setValue(number)
            if update_hex:
                self.hex_input.setText(color.name().upper())
            self.color_preview_label.setText(color.name().upper())
            self.color_preview_chip.setStyleSheet(
                f"background: {color.name()}; border: 1px solid #869284;"
                "border-radius: 25px;")
        finally:
            self._picker_sync = False
        self._mark_hex_invalid(False)
        self.color_error.clear()
        self._preview_color(color)

    def _picker_color_changed(self, color):
        if not self._picker_sync:
            self._set_picker_color(color)

    def _rgb_inputs_changed(self, _value=None):
        if not self._picker_sync:
            self._set_picker_color(QColor(*(channel.value()
                                            for channel in self.rgb_inputs)))

    def _preview_color(self, color):
        if not self.editing_color:
            return
        rgb = (color.red(), color.green(), color.blue())
        setattr(self.engine, self.editing_color, rgb)
        self.engine.last_frame = self.engine.frame(time.perf_counter())
        self._update_color_buttons()
        self.preview.update()

    def _hex_changed(self, value):
        if re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
            self._set_picker_color(QColor(value), update_hex=False)
        elif len(value) == 7:
            self.color_error.setText("颜色代码应为 #RRGGBB")
            self._mark_hex_invalid(True)
        else:
            self.color_error.clear()
            self._mark_hex_invalid(False)

    def _mark_hex_invalid(self, invalid):
        if self.hex_input.property("invalid") == invalid:
            return
        self.hex_input.setProperty("invalid", invalid)
        self.hex_input.style().unpolish(self.hex_input)
        self.hex_input.style().polish(self.hex_input)

    def _cancel_color_editor(self):
        if self.editing_original is not None:
            for field, value in self.editing_original.items():
                setattr(self.engine, field, value)
            self.engine.last_frame = self.engine.frame(time.perf_counter())
            self._update_color_buttons()
            self.preview.update()
        self.editing_original = None
        self.editing_color = None
        self.color_editor.hide()
        self.color_error.clear()
        self._mark_hex_invalid(False)

    def _apply_color(self):
        if not self.editing_color:
            return
        value = self.hex_input.text().strip().upper()
        if len(value) != 7 or not value.startswith("#"):
            self.color_error.setText("请输入 #RRGGBB")
            self._mark_hex_invalid(True)
            return
        try:
            color = tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
        except ValueError:
            self.color_error.setText("颜色代码无效")
            self._mark_hex_invalid(True)
            return
        setattr(self.engine, self.editing_color, color)
        self._detach_active_preset()
        if self.editing_color in ("base", "accent"):
            self.effect_palettes[self.engine.effect] = (
                self.engine.base, self.engine.accent)
        self.engine.last_frame = self.engine.frame(time.perf_counter())
        self._update_color_buttons()
        self.editing_original = None
        self._cancel_color_editor()
        self.preview.update()
        self._save_settings()

    def _save_settings(self):
        if self.preview_mode:
            return
        colors = self.editing_original or {
            field: getattr(self.engine, field)
            for field in ("base", "accent", "global_color", "ecg_background")}
        saved_base, saved_accent = colors["base"], colors["accent"]
        if self.active_preset is None:
            self.effect_palettes[self.engine.effect] = (saved_base, saved_accent)
        data = {"base": color_hex(saved_base),
                "accent": color_hex(saved_accent),
                "global_color": color_hex(colors["global_color"]),
                "ecg_background": color_hex(colors["ecg_background"]),
                "effect_palettes": {
                    effect_id: {"base": color_hex(palette[0]),
                                "accent": color_hex(palette[1])}
                    for effect_id, palette in self.effect_palettes.items()},
                "gallery_category": self.gallery_category,
                "pairing_mood": self.pairing_mood,
                "pairings_expanded": self.inspiration_expanded,
                "custom_heart_keys": sorted(self.engine.custom_heart_keys),
                "custom_canvas_keys": sorted(self.engine.custom_canvas_keys),
                "brightness": self.engine.brightness,
                "base_brightness": self.engine.base_brightness,
                "accent_brightness": self.engine.accent_brightness,
                "speed": self.engine.speed,
                "ripple_width": self.engine.ripple_width,
                "saved_presets": [dict(name=name, **preset)
                                  for name, preset in self.saved_presets.items()],
                "active_preset": self.active_preset,
                "active": self.engine.ripples_enabled,
                "effect": self.engine.effect,
                "transport": self.engine.preference,
                "device_profile": self.profile}
        try:
            temp = SETTINGS.with_suffix(".tmp")
            temp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                            encoding="utf-8")
            temp.replace(SETTINGS)
        except OSError as error:
            LOG.warning("Could not save settings: %s", error)

    def exit_app(self):
        if self.exiting:
            return
        self.exiting = True
        self.frame_timer.stop()
        self.retry_timer.stop()
        self.mode_timer.stop()
        self.save_timer.stop()
        try:
            self._save_settings()
            self.engine.close()
        finally:
            if self.tray is not None:
                self.tray.hide()
            if self.server is not None:
                self.server.close()
            LOG.info("Application exited")
            QApplication.instance().quit()


def show_existing_instance():
    socket = QLocalSocket()
    socket.connectToServer(SERVER_NAME)
    if socket.waitForConnected(700):
        socket.disconnectFromServer()
        return True
    return False


def run(preview=False):
    if sys.platform != "win32":
        raise SystemExit("老必灯目前只支持 Windows。")
    app = QApplication(sys.argv)
    app.setApplicationName("老必灯")
    app.setOrganizationName("老必灯")
    app.setWindowIcon(QIcon(str(ICON)))
    app.setStyle("Fusion")
    load_ui_font()
    app.setFont(QFont(ui_font(), 10))
    app.setStyleSheet((ROOT / "ui.qss").read_text(encoding="utf-8"))
    app.setQuitOnLastWindowClosed(False)
    autostart = "--autostart" in sys.argv and not preview

    mutex = None
    if not preview:
        try:
            shell32 = ctypes.WinDLL("shell32", use_last_error=True)
            shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.c_wchar_p]
            shell32.SetCurrentProcessExplicitAppUserModelID("LaoBiDeng.Lighting.V98pro")
        except (AttributeError, OSError):
            pass
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                          ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        mutex = kernel32.CreateMutexW(None, 0, "Local\\VGN_Ripple_Qt_320F_5055")
        if not mutex:
            raise ctypes.WinError(ctypes.get_last_error())
        already_running = ctypes.get_last_error() == 183
        if already_running:
            if not autostart:
                show_existing_instance()
            kernel32.CloseHandle(mutex)
            return 0
    window = MainWindow(preview=preview)
    if not autostart or window.tray is None:
        window.show()
    else:
        LOG.info("Started with Windows; window kept in system tray")
    result = app.exec()
    if not window.exiting:
        window.engine.close()
        window._save_settings()
    if mutex:
        kernel32.CloseHandle(mutex)
    return result
