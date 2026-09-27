"""Desktop UI and lifecycle for 老必灯."""

import ctypes
import json
import logging
import os
import re
import shutil
import sys
import time
import zipfile
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QSize, QRectF, QPointF, QStandardPaths, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QColorDialog, QDoubleSpinBox, QFrame,
    QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMenu, QPushButton, QScrollArea, QSlider, QStackedWidget,
    QSystemTrayIcon, QVBoxLayout, QWidget,
)

from backend import LightingController, bluetooth_keyboard_present
from device_setup import DeviceSetupDialog, is_supported_v98, keycaps_from_profile
from device_detection import detect_keyboards, preferred_known_keyboard
from effects import CATEGORIES, EFFECTS, EFFECT_CATEGORY, EFFECT_IDS, MUSIC, REACTIVE, WIDTH_EFFECTS
from layout import KEYCAPS, restore_v98_layout, set_keycaps


ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "老必灯"
DATA_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS = DATA_DIR / "settings.json"
LEGACY_SETTINGS = ROOT / "settings.json"
ICON = ROOT / "assets" / "ripple.ico"
SERVER_NAME = "vgn-ripple-v98pro-320f-5055"
PROJECT_URL = "https://github.com/Stt7L/laobideng"
LOG = logging.getLogger("vgn-ripple")


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


def swatch_icon(rgb):
    pixmap = QPixmap(28, 28)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#8D9988"), 1))
    painter.setBrush(QColor(*rgb))
    painter.drawRoundedRect(2, 2, 24, 24, 7, 7)
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


class FineSlider(QSlider):
    """Pill-shaped slider with direct, fine-grained pointer adjustment."""

    THUMB_HALF_WIDTH = 13

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setFixedHeight(30)
        self.setSingleStep(1)
        self.setPageStep(10)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self._hovered = False
        self.valueChanged.connect(self.update)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center_y = self.height() / 2
        left = self.THUMB_HALF_WIDTH + 1
        track_width = max(1, self.width() - 2 * left)
        span = max(1, self.maximum() - self.minimum())
        x = left + track_width * (self.value() - self.minimum()) / span

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#414D40"))
        painter.drawRoundedRect(QRectF(1, center_y - 3, self.width() - 2, 6), 3, 3)
        painter.setBrush(QColor("#C4EF70"))
        painter.drawRoundedRect(QRectF(1, center_y - 3, max(0, x - 1), 6), 3, 3)

        painter.setPen(QPen(QColor("#C4EF70"), 2 if self.hasFocus() else 1.5))
        painter.setBrush(QColor("#FCFFF5" if self.isSliderDown() else
                                "#EFF8D9" if self._hovered else "#F4F9EA"))
        painter.drawRoundedRect(QRectF(x - left, center_y - 8, 2 * left, 16), 8, 8)

    def _set_from_pointer(self, x):
        left = self.THUMB_HALF_WIDTH + 1
        width = max(1, self.width() - 2 * left)
        fraction = min(1.0, max(0.0, (x - left) / width))
        self.setValue(round(self.minimum() + fraction * (self.maximum() - self.minimum())))

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


class KeyboardPreview(QWidget):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setMinimumHeight(275)
        self.setAccessibleName("键盘灯效预览")

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#384439"), 1))
        painter.setBrush(QColor("#1A211B"))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 20, 20)
        painter.setPen(QColor("#EAF3DE"))
        painter.setFont(QFont("Microsoft YaHei UI", 10, QFont.Weight.DemiBold))
        painter.drawText(20, 30, f"{getattr(self, 'model', 'V98 Pro')}  /  键位预览")
        painter.setPen(QColor("#9AAA97"))
        painter.setFont(QFont("Microsoft YaHei UI", 9))
        painter.drawText(self.width() - 166, 30, f"实时灯效 · {len(KEYCAPS)} 键")

        scale = min((self.width() - 28) / 790, (self.height() - 62) / 270)
        x0 = (self.width() - 790 * scale) / 2
        y0 = 42 + (self.height() - 52 - 270 * scale) / 2
        painter.save()
        painter.translate(x0, y0)
        painter.scale(scale, scale)
        painter.setPen(QPen(QColor("#414942"), 1.5))
        painter.setBrush(QColor("#2A302B"))
        painter.drawRoundedRect(QRectF(0, 0, 790, 270), 18, 18)
        frame = self.engine.preview_frame()
        label_font = QFont("Microsoft YaHei UI")
        label_font.setPixelSize(12)
        label_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(label_font)
        for cap in KEYCAPS:
            cx, cy, cw, ch = cap.x - 48, cap.y - 43, cap.w, cap.h
            colors = [frame[led] for led in cap.leds if led < len(frame)]
            rgb = tuple(round(sum(color[i] for color in colors) / len(colors))
                        for i in range(3)) if colors else (40, 46, 40)
            lit = QColor(*rgb)
            surface = QColor(*(round(34 * 0.38 + c * 0.62) for c in rgb))
            painter.setPen(QPen(lit.lighter(125), 1.2))
            painter.setBrush(surface)
            painter.drawRoundedRect(QRectF(cx, cy, cw, ch), 5, 5)
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
        self.engine.brightness = self._clamp(self.settings.get("brightness"), 0.0, 1.0, 0.65)
        self.engine.speed = self._clamp(self.settings.get("speed"), 0.2, 3.0, 1.0)
        self.engine.ripple_width = self._clamp(
            self.settings.get("ripple_width"), 0.5, 2.0, 1.0)
        self.engine.ripples_enabled = bool(self.settings.get("active", True))
        self.engine.effect = self.settings.get("effect") if self.settings.get("effect") in EFFECT_IDS else "ripple"
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
        saved_category = self.settings.get("gallery_category")
        self.gallery_category = (
            saved_category if saved_category in {item[0] for item in CATEGORIES}
            or (saved_category is None and "gallery_category" in self.settings)
            else EFFECT_CATEGORY[self.engine.effect])
        self.engine.preference = self.settings.get("transport") if self.settings.get("transport") in ("auto", "wired", "wireless") else "auto"
        self.engine.last_frame = self.engine.frame(0)

        self.setWindowTitle(f"老必灯 · {self.profile['model'] if self.profile else '键盘灯效工作室'}")
        self.setWindowIcon(QIcon(str(ICON)))
        self.setMinimumSize(680, 620)
        available = QApplication.primaryScreen().availableGeometry()
        self.resize(790, min(780, max(620, available.height() - 80)))
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
        self.retry_timer = QTimer(self)
        self.retry_timer.setInterval(3000)
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

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)

        self.page_stack = QStackedWidget()
        outer.addWidget(self.page_stack)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.page_stack.addWidget(scroll)
        body = QWidget()
        body.setObjectName("root")
        scroll.setWidget(body)
        self.scroll = scroll
        layout = QVBoxLayout(body)
        layout.setContentsMargins(28, 27, 28, 24)
        layout.setSpacing(16)

        header = QHBoxLayout()
        header.setSpacing(14)
        logo = QLabel()
        logo.setPixmap(QIcon(str(ICON)).pixmap(QSize(52, 52)))
        logo.setFixedSize(52, 52)
        header.addWidget(logo)
        title_column = QVBoxLayout()
        title_column.setSpacing(1)
        title = QLabel("老必灯")
        title.setObjectName("brandTitle")
        title_column.addWidget(title)
        subtitle = QLabel("逐键灯效工作室  ·  本地键位追踪")
        subtitle.setObjectName("brandSub")
        title_column.addWidget(subtitle)
        header.addLayout(title_column)
        header.addStretch()
        settings_button = QPushButton("设置")
        settings_button.setObjectName("secondary")
        settings_button.setFixedWidth(78)
        settings_button.clicked.connect(lambda: self.page_stack.setCurrentIndex(1))
        header.addWidget(settings_button)
        self.status = QLabel("正在连接")
        self.status.setObjectName("statusPaused")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.status)
        layout.addLayout(header)

        self.preview = KeyboardPreview(self.engine)
        self.preview.model = self.profile.get("model", "V98 Pro") if self.profile else "V98 Pro"
        layout.addWidget(self.preview)

        effects_card, effects_layout = self._card("灯效画廊")
        effects_hint = QLabel("每款灯效独立保存配色 · 点击分类按钮展开或收起")
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
            button = QPushButton(f"{title}  {count}")
            button.setObjectName("categoryChoice")
            button.setCheckable(True)
            button.setAccessibleName(f"{title}，{count} 种，点击展开或收起")
            button.setToolTip(subtitle)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setIconSize(QSize(16, 16))
            button.clicked.connect(lambda _checked=False, chosen=category:
                                   self._toggle_category(chosen))
            category_row.addWidget(button, 0, index)
            self.category_buttons[category] = button
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
            button = QPushButton(f"{title}\n{description}")
            button.setObjectName("effectChoice")
            button.setCheckable(True)
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
        self.audio_refresh.clicked.connect(self._refresh_audio_device)
        music_status_row.addWidget(self.audio_refresh)
        effects_layout.addLayout(music_status_row)
        self._refresh_gallery()

        colors_layout = effects_layout
        palette_heading = QLabel("当前灯效配色")
        palette_heading.setObjectName("sectionTitle")
        colors_layout.addWidget(palette_heading)
        self.palette_hint = QLabel()
        self.palette_hint.setObjectName("muted")
        colors_layout.addWidget(self.palette_hint)
        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self.base_button = QPushButton()
        self.accent_button = QPushButton()
        for button, target in ((self.base_button, "base"),
                               (self.accent_button, "accent")):
            button.setObjectName("colorTile")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setIconSize(QSize(28, 28))
            button.clicked.connect(lambda _checked=False, which=target:
                                   self._open_color_editor(which))
            tiles.addWidget(button)
        colors_layout.addLayout(tiles)
        self._update_color_buttons()

        self.color_editor = QFrame()
        self.color_editor.setObjectName("inlineEditor")
        editor_layout = QVBoxLayout(self.color_editor)
        editor_layout.setContentsMargins(15, 14, 15, 14)
        editor_layout.setSpacing(10)
        self.editor_title = QLabel("选择颜色")
        self.editor_title.setObjectName("sectionTitle")
        editor_layout.addWidget(self.editor_title)
        color_hint = QLabel("自由选色 · 切换到其他窗口或收起程序时，当前颜色会自动保存")
        color_hint.setObjectName("muted")
        editor_layout.addWidget(color_hint)
        self.color_editor_layout = editor_layout
        self.color_dialog = None
        editor_actions = QHBoxLayout()
        editor_actions.setSpacing(8)
        hex_label = QLabel("颜色代码")
        hex_label.setObjectName("muted")
        editor_actions.addWidget(hex_label)
        self.hex_input = QLineEdit()
        self.hex_input.setMaxLength(7)
        self.hex_input.setPlaceholderText("#RRGGBB")
        self.hex_input.setFixedWidth(120)
        self.hex_input.returnPressed.connect(self._apply_color)
        self.hex_input.textEdited.connect(self._hex_changed)
        editor_actions.addWidget(self.hex_input)
        self.color_error = QLabel("")
        self.color_error.setStyleSheet("color: #F2B9A9;")
        editor_actions.addWidget(self.color_error)
        editor_actions.addStretch()
        cancel = QPushButton("取消")
        cancel.setObjectName("quiet")
        cancel.clicked.connect(self._cancel_color_editor)
        editor_actions.addWidget(cancel)
        apply = QPushButton("应用颜色")
        apply.setObjectName("primary")
        apply.clicked.connect(self._apply_color)
        editor_actions.addWidget(apply)
        self.editor_actions_layout = editor_actions
        editor_layout.addLayout(editor_actions)
        colors_layout.addWidget(self.color_editor)
        self.color_editor.hide()
        self._update_palette_hint()
        layout.addWidget(effects_card)

        settings_card, settings_layout = self._card("灯效设置")
        self.brightness_slider, self.brightness_value, _ = self._slider_row(
            settings_layout, "常亮亮度", 0, 1000,
            round(self.engine.brightness * 1000), "%")
        self.speed_slider, self.speed_value, _ = self._slider_row(
            settings_layout, "动画速度", 200, 3000,
            round(self.engine.speed * 1000), "×")
        self.ripple_width_slider, self.ripple_width_value, self.width_row = self._slider_row(
            settings_layout, "光带宽度", 500, 2000,
            round(self.engine.ripple_width * 1000), "%")
        self.brightness_slider.valueChanged.connect(self._settings_changed)
        self.speed_slider.valueChanged.connect(self._settings_changed)
        self.ripple_width_slider.valueChanged.connect(self._settings_changed)
        self.width_row.setVisible(self.engine.effect in WIDTH_EFFECTS)
        settings_hint = QLabel("拖动滑块，或点击右侧数值输入后按回车")
        settings_hint.setObjectName("hint")
        settings_layout.addWidget(settings_hint)
        layout.addWidget(settings_card)

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

        self.adapter_toggle = QPushButton("＋  提供其他键盘的适配资料")
        self.adapter_toggle.setObjectName("actionSecondary")
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
        self.toggle_button.setFixedHeight(46)
        self.toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_button.clicked.connect(self._toggle_effect)
        action_grid.addWidget(self.toggle_button, 0, 0, 1, 2)
        exit_button = QPushButton("退出程序")
        exit_button.setObjectName("actionSecondary")
        exit_button.setFixedHeight(46)
        exit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        exit_button.clicked.connect(self.exit_app)
        action_grid.addWidget(exit_button, 0, 2)
        action_card, action_layout = self._card("快速控制")
        action_layout.addLayout(action_grid)
        layout.addWidget(action_card)
        hint = QLabel("关闭窗口后灯效继续运行。右击托盘图标可退出程序。请勿同时打开 VHUB。")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()

        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.page_stack.addWidget(settings_scroll)
        settings_body = QWidget()
        settings_body.setObjectName("root")
        settings_scroll.setWidget(settings_body)
        settings_page = QVBoxLayout(settings_body)
        settings_page.setContentsMargins(28, 27, 28, 24)
        settings_page.setSpacing(16)
        settings_header = QHBoxLayout()
        back_button = QPushButton("←  返回灯效")
        back_button.setObjectName("quiet")
        back_button.clicked.connect(lambda: self.page_stack.setCurrentIndex(0))
        settings_header.addWidget(back_button)
        settings_header.addStretch()
        settings_title = QLabel("设置")
        settings_title.setObjectName("brandTitle")
        settings_header.addWidget(settings_title)
        settings_page.addLayout(settings_header)

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
        author_card, author_layout = self._card("关于老必灯")
        author = QLabel("作者  Stt7L")
        author.setObjectName("muted")
        author_layout.addWidget(author)
        github_button = QPushButton("GitHub 项目  ↗")
        github_button.setObjectName("galleryToggle")
        github_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(PROJECT_URL)))
        author_layout.addWidget(github_button)
        settings_page.addWidget(author_card)
        settings_page.addStretch()
        self._refresh_profile_summary()
        self._refresh_toggle_labels()

    def _card(self, title):
        card = QFrame()
        card.setObjectName("surface")
        content = QVBoxLayout(card)
        content.setContentsMargins(19, 17, 19, 19)
        content.setSpacing(15)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        content.addWidget(heading)
        return card, content

    def _slider_row(self, parent, label, low, high, value, unit):
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(18)
        name = QLabel(label)
        name.setObjectName("muted")
        name.setFixedWidth(80)
        row.addWidget(name)
        slider = FineSlider()
        slider.setRange(low, high)
        slider.setValue(value)
        slider.setAccessibleName(label)
        row.addWidget(slider, 1)
        display = QDoubleSpinBox()
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
                current = self.engine.base if self.editing_color == "base" else self.engine.accent
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
        self.preview.update()
        if self.gallery_category == "music":
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

    def _select_effect(self, effect):
        if effect == self.engine.effect:
            return
        self._cancel_color_editor()
        self.effect_palettes[self.engine.effect] = (self.engine.base, self.engine.accent)
        palette = self.effect_palettes.get(effect)
        if palette is None:
            accent = (self.engine.accent if self.engine.accent != (0, 0, 0)
                      or effect == "ripple" else (196, 239, 112))
            palette = (self.engine.base, accent)
            self.effect_palettes[effect] = palette
        self.engine.set_effect(effect)
        self.engine.base, self.engine.accent = palette
        self.width_row.setVisible(effect in WIDTH_EFFECTS)
        for effect_id, button in self.effect_buttons.items():
            button.setChecked(effect_id == effect)
        self._update_color_buttons()
        self._update_palette_hint()
        self._refresh_gallery()
        self.engine.last_frame = self.engine.frame(time.perf_counter())
        self.preview.update()
        self._save_settings()

    def _refresh_gallery(self):
        title = next(title for effect_id, title, _ in EFFECTS
                     if effect_id == self.engine.effect)
        self.gallery_selection.setText(f"当前 · {title}")
        for category, category_title, _ in CATEGORIES:
            open_now = category == self.gallery_category
            button = self.category_buttons[category]
            button.setChecked(open_now)
            button.setIcon(chevron_icon(up=open_now))
            self.category_panels[category].setVisible(open_now)
        self.music_status.setVisible(self.gallery_category == "music")
        self.audio_refresh.setVisible(self.gallery_category == "music")

    def _refresh_audio_device(self):
        self.engine.audio_meter.refresh()
        self.music_status.setText("正在连接系统默认播放设备…")

    def _toggle_category(self, category):
        self.gallery_category = None if self.gallery_category == category else category
        self._refresh_gallery()
        self._save_settings()

    def _update_palette_hint(self):
        if self.engine.effect == "ripple":
            hint = "波纹色就是按键后扩散的颜色，默认黑色；打开色盘即可实时调整。"
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

    def _settings_changed(self):
        brightness = self.brightness_slider.value()
        speed = self.speed_slider.value()
        ripple_width = self.ripple_width_slider.value()
        self.engine.brightness = brightness / 1000
        self.engine.speed = speed / 1000
        self.engine.ripple_width = ripple_width / 1000
        self.brightness_value.setValue(brightness / 10)
        self.speed_value.setValue(speed / 1000)
        self.ripple_width_value.setValue(ripple_width / 10)
        if not self.preview_mode:
            self.save_timer.start()

    def _update_color_buttons(self):
        accent_label = "波纹色" if self.engine.effect == "ripple" else "点缀色"
        for button, label, value in ((self.base_button, "底色", self.engine.base),
                                     (self.accent_button, accent_label, self.engine.accent)):
            button.setIcon(swatch_icon(value))
            button.setText(f"{label}    {color_hex(value)}")

    def _open_color_editor(self, target):
        if self.editing_color is not None:
            self._cancel_color_editor()
        self._ensure_color_dialog()
        self.editing_color = target
        self.editing_original = (self.engine.base, self.engine.accent)
        self.editor_title.setText(
            "修改底色" if target == "base" else
            "修改波纹色" if self.engine.effect == "ripple" else "修改点缀色")
        self.hex_input.setText(color_hex(self.engine.base if target == "base"
                                         else self.engine.accent))
        self.color_dialog.setCurrentColor(QColor(self.hex_input.text()))
        self.color_error.clear()
        self.color_editor.show()
        self.hex_input.setFocus()
        self.hex_input.selectAll()
        QTimer.singleShot(0, lambda: self.scroll.ensureWidgetVisible(self.color_editor))

    def _ensure_color_dialog(self):
        if self.color_dialog is not None:
            return
        self.color_dialog = QColorDialog(self.color_editor)
        self.color_dialog.setOptions(QColorDialog.ColorDialogOption.DontUseNativeDialog |
                                     QColorDialog.ColorDialogOption.NoButtons)
        self.color_dialog.setWindowFlags(Qt.WindowType.Widget)
        self.color_dialog.currentColorChanged.connect(self._color_wheel_changed)
        insert_at = self.color_editor_layout.indexOf(self.editor_actions_layout)
        self.color_editor_layout.insertWidget(insert_at, self.color_dialog)

    def _color_wheel_changed(self, color):
        if color.isValid() and self.editing_color:
            self.hex_input.setText(color.name().upper())
            self.color_error.clear()
            self._preview_color(color)

    def _preview_color(self, color):
        if not self.editing_color:
            return
        rgb = (color.red(), color.green(), color.blue())
        if self.editing_color == "base":
            self.engine.base = rgb
        else:
            self.engine.accent = rgb
        self.engine.last_frame = self.engine.frame(time.perf_counter())
        self._update_color_buttons()
        self.preview.update()

    def _hex_changed(self, value):
        color = QColor(value)
        if color.isValid() and len(value) == 7 and self.color_dialog is not None:
            self.color_dialog.setCurrentColor(color)
            self.color_error.clear()

    def _cancel_color_editor(self):
        if self.editing_original is not None:
            self.engine.base, self.engine.accent = self.editing_original
            self.engine.last_frame = self.engine.frame(time.perf_counter())
            self._update_color_buttons()
            self.preview.update()
        self.editing_original = None
        self.editing_color = None
        self.color_editor.hide()
        self.color_error.clear()

    def _apply_color(self):
        if not self.editing_color:
            return
        value = self.hex_input.text().strip().upper()
        if len(value) != 7 or not value.startswith("#"):
            self.color_error.setText("请输入 #RRGGBB")
            return
        try:
            color = tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
        except ValueError:
            self.color_error.setText("颜色代码无效")
            return
        if self.editing_color == "base":
            self.engine.base = color
        else:
            self.engine.accent = color
        self.effect_palettes[self.engine.effect] = (self.engine.base, self.engine.accent)
        self.engine.last_frame = self.engine.frame(time.perf_counter())
        self._update_color_buttons()
        self.editing_original = None
        self._cancel_color_editor()
        self.preview.update()
        self._save_settings()

    def _save_settings(self):
        if self.preview_mode:
            return
        saved_base, saved_accent = (self.editing_original if self.editing_original is not None
                                    else (self.engine.base, self.engine.accent))
        self.effect_palettes[self.engine.effect] = (saved_base, saved_accent)
        data = {"base": color_hex(saved_base),
                "accent": color_hex(saved_accent),
                "effect_palettes": {
                    effect_id: {"base": color_hex(palette[0]),
                                "accent": color_hex(palette[1])}
                    for effect_id, palette in self.effect_palettes.items()},
                "gallery_category": self.gallery_category,
                "brightness": self.engine.brightness,
                "speed": self.engine.speed,
                "ripple_width": self.engine.ripple_width,
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
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyleSheet((ROOT / "ui.qss").read_text(encoding="utf-8"))
    app.setQuitOnLastWindowClosed(False)

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
            show_existing_instance()
            kernel32.CloseHandle(mutex)
            return 0
    window = MainWindow(preview=preview)
    window.show()
    result = app.exec()
    if not window.exiting:
        window.engine.close()
        window._save_settings()
    if mutex:
        kernel32.CloseHandle(mutex)
    return result
