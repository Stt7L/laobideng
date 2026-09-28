"""Local device identity and photo-backed key layout editing."""

import re
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QEvent, QRectF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from layout import DEFAULT_KEYCAPS, Keycap
from backend import VK_NAMES
from device_detection import detect_keyboards


CANVAS_WIDTH = 884
CANVAS_HEIGHT = 343
PHOTO_FILTER = "键盘照片 (*.png *.jpg *.jpeg *.webp *.bmp)"


def is_supported_v98(profile):
    model = profile.get("model", "").lower().replace(" ", "")
    return ("v98" in model and "pro" in model and
            profile.get("vid", "").upper() == "320F" and
            profile.get("pid", "").upper() in ("5055", "5088"))


def keycaps_from_profile(profile):
    rows = profile.get("layout")
    if not isinstance(rows, list) or not rows:
        return list(DEFAULT_KEYCAPS) if is_supported_v98(profile) else []
    result = []
    for row in rows[:180]:
        try:
            name = str(row["name"]).strip()[:40]
            label = str(row.get("label", name)).strip()[:20]
            x, y, w, h = (float(row[field]) for field in ("x", "y", "w", "h"))
            leds = tuple(int(item) for item in row.get("leds", []))
        except (KeyError, TypeError, ValueError):
            continue
        if name and 0 <= x < CANVAS_WIDTH and 0 <= y < CANVAS_HEIGHT and 8 <= w <= 350 and 8 <= h <= 130:
            result.append(Keycap(name, label or name, x, y, w, h, leds))
    return result


def keycaps_to_data(caps):
    return [{"name": cap.name, "label": cap.label, "x": round(cap.x, 2),
             "y": round(cap.y, 2), "w": round(cap.w, 2), "h": round(cap.h, 2),
             "leds": list(cap.leds)} for cap in caps]


def generic_template(kind):
    """Create editable local geometry; LED numbers here are preview IDs only."""
    rows = []

    def add(name, label, x, y, w=31, h=31):
        rows.append(Keycap(name, label, x, y, w, h, (len(rows),)))

    if kind != "61 键":
        add("Esc", "Esc", 48, 50)
        for i in range(12):
            add(f"F{i + 1}", f"F{i + 1}", 126 + i * 38 + (i // 4) * 16, 50)
        if kind != "87 键":
            for i, label in enumerate(("Prt", "Scr", "Pau")):
                add(("Print Screen", "Scroll Lock", "Pause")[i], label, 648 + i * 38, 50)
    pitch = 37
    top = 95 if kind != "61 键" else 67
    for i, name in enumerate(("`", "1", "2", "3", "4", "5", "6", "7",
                              "8", "9", "0", "-_", "=+")):
        add(name, name[:1], 48 + i * pitch, top)
    add("Backspace", "⌫", 48 + 13 * pitch, top, 69)
    add("Tab", "Tab", 48, top + 40, 50)
    for i, name in enumerate("QWERTYUIOP"):
        add(name, name, 103 + i * pitch, top + 40)
    for i, name in enumerate(("[", "]", "\\")):
        add(name, name, 473 + i * pitch, top + 40)
    add("CapsLock", "Caps", 48, top + 80, 62)
    for i, name in enumerate("ASDFGHJKL"):
        add(name, name, 115 + i * pitch, top + 80)
    add(";", ";", 448, top + 80)
    add("'", "'", 485, top + 80)
    add("Enter", "Enter", 522, top + 80, 76)
    add("Left Shift", "Shift", 48, top + 120, 78)
    for i, name in enumerate("ZXCVBNM"):
        add(name, name, 132 + i * pitch, top + 120)
    for i, name in enumerate((",", ".", "/")):
        add(name, name, 391 + i * pitch, top + 120)
    add("Right Shift", "Shift", 505, top + 120, 93)
    for name, label, x, width in (("Left Ctrl", "Ctrl", 48, 47),
                                  ("Left Win", "Win", 99, 47),
                                  ("Left Alt", "Alt", 150, 47),
                                  ("Space", "Space", 201, 211),
                                  ("Right Alt", "Alt", 416, 47),
                                  ("Fn", "Fn", 467, 47),
                                  ("Right Ctrl", "Ctrl", 518, 80)):
        add(name, label, x, top + 160, width)
    if kind != "61 键":
        for name, label, x, y in (("Insert", "Ins", 642, top),
                                  ("Home", "Home", 679, top),
                                  ("Page Up", "PgUp", 716, top),
                                  ("Del", "Del", 642, top + 40),
                                  ("End", "End", 679, top + 40),
                                  ("Page Down", "PgDn", 716, top + 40),
                                  ("Up Arrow", "▲", 679, top + 120),
                                  ("Left Arrow", "◀", 642, top + 160),
                                  ("Down Arrow", "▼", 679, top + 160),
                                  ("Right Arrow", "▶", 716, top + 160)):
            add(name, label, x, y)
    if kind == "104 键":
        for row_index, names in enumerate((("NumLock", "Num /", "Num *", "Num -"),
                                            ("Num 7", "Num 8", "Num 9", "Num +"),
                                            ("Num 4", "Num 5", "Num 6"),
                                            ("Num 1", "Num 2", "Num 3", "Num Enter"),
                                            ("Num 0", "Num ."))):
            for column, name in enumerate(names):
                add(name, name.replace("Num ", ""), 757 + column * 32,
                    top + row_index * 40, 28, 31)
    return rows


def snap_keys_to_photo(photo, caps):
    """Locally align template rectangles to nearby high-contrast key edges."""
    if photo.isNull():
        return list(caps)
    image = photo.toImage().scaled(CANVAS_WIDTH, CANVAS_HEIGHT,
                                   Qt.AspectRatioMode.IgnoreAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
    gray = []
    for y in range(CANVAS_HEIGHT):
        row = []
        for x in range(CANVAS_WIDTH):
            pixel = image.pixel(x, y)
            row.append(((pixel >> 16) & 255) * 0.299 +
                       ((pixel >> 8) & 255) * 0.587 +
                       (pixel & 255) * 0.114)
        gray.append(row)

    def edge(x, y, vertical):
        if x < 3 or y < 3 or x >= CANVAS_WIDTH - 3 or y >= CANVAS_HEIGHT - 3:
            return 0
        return (abs(gray[y][x + 2] - gray[y][x - 2]) if vertical else
                abs(gray[y + 2][x] - gray[y - 2][x]))

    aligned = []
    for cap in caps:
        x, y, w, h = map(round, (cap.x, cap.y, cap.w, cap.h))
        x_samples = range(x + 6, x + w - 5, max(3, w // 10))
        y_samples = range(y + 6, y + h - 5, max(3, h // 8))
        score_x = lambda dx: sum(
            edge(x + dx, sy, True) + edge(x + w + dx, sy, True)
            for sy in y_samples)
        score_y = lambda dy: sum(
            edge(sx, y + dy, False) + edge(sx, y + h + dy, False)
            for sx in x_samples)
        best_x = max(range(-9, 10), key=score_x)
        best_y = max(range(-9, 10), key=score_y)
        if score_x(best_x) < score_x(0) + 6:
            best_x = 0
        if score_y(best_y) < score_y(0) + 6:
            best_y = 0
        aligned.append(Keycap(cap.name, cap.label, max(0, x + best_x),
                              max(0, y + best_y), cap.w, cap.h, cap.leds))
    return aligned


class LayoutCanvas(QWidget):
    def __init__(self, photo, caps, parent=None):
        super().__init__(parent)
        self.setFixedSize(CANVAS_WIDTH, CANVAS_HEIGHT)
        self.setMouseTracking(True)
        self.photo = QPixmap(str(photo)) if photo else QPixmap()
        self.caps = list(caps)
        self.selected = -1
        self.hovered = -1
        self.drag_mode = None
        self.drag_start = None
        self.original = None
        self.selection_changed = None

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        frame = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        path = QPainterPath()
        path.addRoundedRect(frame, 16, 16)
        painter.fillPath(path, QColor("#1D241E"))
        if not self.photo.isNull():
            painter.setClipPath(path)
            painter.drawPixmap(self.rect(), self.photo)
            painter.setClipping(False)
        for index, cap in enumerate(self.caps):
            selected = index == self.selected
            hovered = index == self.hovered
            painter.setPen(QPen(QColor("#E5FFBA" if selected else
                                       "#C4EF70" if hovered else "#91B869"),
                                2 if selected or hovered else 1.2))
            painter.setBrush(QColor(196, 239, 112, 76 if selected else
                                    48 if hovered else 27))
            painter.drawRoundedRect(QRectF(cap.x, cap.y, cap.w, cap.h), 5, 5)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(QRectF(cap.x + 2, cap.y + 1, cap.w - 4, cap.h - 2),
                             Qt.AlignmentFlag.AlignCenter, cap.label)
            if selected:
                painter.fillRect(QRectF(cap.x + cap.w - 9, cap.y + cap.h - 9, 9, 9),
                                 QColor("#D8FB9A"))
        painter.setPen(QPen(QColor("#455645"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(frame, 16, 16)
        painter.end()

    def _set_selected(self, index):
        self.selected = index
        if self.selection_changed:
            self.selection_changed(index)
        self.update()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = event.position()
        self.drag_start = (point.x(), point.y())
        for index in range(len(self.caps) - 1, -1, -1):
            cap = self.caps[index]
            if QRectF(cap.x, cap.y, cap.w, cap.h).contains(point):
                self._set_selected(index)
                self.original = cap
                self.drag_mode = ("resize" if point.x() > cap.x + cap.w - 12 and
                                  point.y() > cap.y + cap.h - 12 else "move")
                self.setCursor(Qt.CursorShape.SizeFDiagCursor if
                               self.drag_mode == "resize" else
                               Qt.CursorShape.ClosedHandCursor)
                return
        self.drag_mode = "draw"
        self._set_selected(-1)

    def mouseMoveEvent(self, event):
        if self.drag_mode is None or self.drag_start is None:
            point = event.position()
            hovered = next((index for index in range(len(self.caps) - 1, -1, -1)
                            if QRectF(self.caps[index].x, self.caps[index].y,
                                      self.caps[index].w, self.caps[index].h).contains(point)),
                           -1)
            if hovered != self.hovered:
                self.hovered = hovered
                self.update()
            if hovered >= 0:
                cap = self.caps[hovered]
                resize = point.x() > cap.x + cap.w - 12 and point.y() > cap.y + cap.h - 12
                self.setCursor(Qt.CursorShape.SizeFDiagCursor if resize else
                               Qt.CursorShape.OpenHandCursor)
            else:
                self.setCursor(Qt.CursorShape.CrossCursor)
            return
        x, y = event.position().x(), event.position().y()
        sx, sy = self.drag_start
        if self.drag_mode == "draw":
            self.update()
            return
        cap = self.original
        if self.drag_mode == "move":
            moved = Keycap(cap.name, cap.label,
                           max(0, min(CANVAS_WIDTH - cap.w, cap.x + x - sx)),
                           max(0, min(CANVAS_HEIGHT - cap.h, cap.y + y - sy)),
                           cap.w, cap.h, cap.leds)
        else:
            moved = Keycap(cap.name, cap.label, cap.x, cap.y,
                           max(12, min(CANVAS_WIDTH - cap.x, cap.w + x - sx)),
                           max(12, min(CANVAS_HEIGHT - cap.y, cap.h + y - sy)),
                           cap.leds)
        self.caps[self.selected] = moved
        self.update()

    def mouseReleaseEvent(self, event):
        if self.drag_mode == "draw" and self.drag_start is not None:
            sx, sy = self.drag_start
            x, y = event.position().x(), event.position().y()
            if abs(x - sx) >= 12 and abs(y - sy) >= 12:
                number = len(self.caps) + 1
                led = max((item for cap in self.caps for item in cap.leds), default=-1) + 1
                cap = Keycap(f"Key {number}", str(number), min(sx, x), min(sy, y),
                             abs(x - sx), abs(y - sy), (led,))
                self.caps.append(cap)
                self._set_selected(len(self.caps) - 1)
        self.drag_mode = None
        self.drag_start = None
        self.setCursor(Qt.CursorShape.OpenHandCursor if self.hovered >= 0 else
                       Qt.CursorShape.CrossCursor)
        self.update()

    def leaveEvent(self, event):
        self.hovered = -1
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()
        super().leaveEvent(event)


class PhotoLayoutEditor(QDialog):
    def __init__(self, photo, caps=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("老必灯 · 本地键位绘制")
        self.setFixedSize(930, 655)
        self.await_binding = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 20)
        outer.setSpacing(12)
        heading = QLabel("在照片上校准键位")
        heading.setObjectName("brandTitle")
        outer.addWidget(heading)
        help_text = QLabel("拖动键帽可移动；拖动右下角可缩放；在空白处拖动可新增。选中后可修改名称，Delete 可删除。")
        help_text.setObjectName("hint")
        outer.addWidget(help_text)
        self.canvas = LayoutCanvas(photo, caps or list(DEFAULT_KEYCAPS))
        self.canvas.selection_changed = self._selection_changed
        outer.addWidget(self.canvas, alignment=Qt.AlignmentFlag.AlignHCenter)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(9)
        layout_caption = QLabel("布局")
        layout_caption.setObjectName("muted")
        toolbar.addWidget(layout_caption)
        self.template = QComboBox()
        self.template.addItems(("V98 Pro", "104 键", "87 键", "61 键"))
        toolbar.addWidget(self.template)
        template_button = QPushButton("套用初始布局")
        template_button.setObjectName("secondary")
        template_button.clicked.connect(self._apply_template)
        toolbar.addWidget(template_button)
        snap_button = QPushButton("贴合照片轮廓")
        snap_button.setObjectName("secondary")
        snap_button.setToolTip("在初始布局附近寻找键帽边缘；斜拍和特殊键位仍需手动校准")
        snap_button.clicked.connect(self._snap_to_photo)
        toolbar.addWidget(snap_button)
        toolbar.addStretch()
        outer.addLayout(toolbar)
        key_row = QHBoxLayout()
        key_row.setSpacing(9)
        key_caption = QLabel("当前键位")
        key_caption.setObjectName("muted")
        key_row.addWidget(key_caption)
        self.name = QLineEdit()
        self.name.setPlaceholderText("按键名称，如 A")
        self.name.setMaxLength(40)
        self.name.editingFinished.connect(self._rename_selected)
        key_row.addWidget(self.name, 1)
        self.label = QLineEdit()
        self.label.setPlaceholderText("键帽显示文字")
        self.label.setMaxLength(20)
        self.label.editingFinished.connect(self._rename_selected)
        key_row.addWidget(self.label, 1)
        self.bind_button = QPushButton("按键绑定")
        self.bind_button.setObjectName("secondary")
        self.bind_button.clicked.connect(self._begin_binding)
        key_row.addWidget(self.bind_button)
        delete_button = QPushButton("删除键位")
        delete_button.setObjectName("quiet")
        delete_button.clicked.connect(self._delete_selected)
        key_row.addWidget(delete_button)
        outer.addLayout(key_row)
        actions = QHBoxLayout()
        actions.addStretch()
        cancel = QPushButton("取消")
        cancel.setObjectName("quiet")
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        save = QPushButton("保存键位布局")
        save.setObjectName("primary")
        save.clicked.connect(self._accept_layout)
        actions.addWidget(save)
        outer.addLayout(actions)
        for button in self.findChildren(QPushButton):
            button.setCursor(Qt.CursorShape.PointingHandCursor)

    def _selection_changed(self, index):
        cap = self.canvas.caps[index] if index >= 0 else None
        self.name.setText(cap.name if cap else "")
        self.label.setText(cap.label if cap else "")

    def _rename_selected(self):
        index = self.canvas.selected
        if index < 0:
            return
        old = self.canvas.caps[index]
        name = self.name.text().strip() or old.name
        label = self.label.text().strip() or name
        self.canvas.caps[index] = Keycap(name, label, old.x, old.y,
                                         old.w, old.h, old.leds)
        self.canvas.update()

    def _delete_selected(self):
        index = self.canvas.selected
        if index >= 0:
            del self.canvas.caps[index]
            self.canvas._set_selected(-1)

    def _apply_template(self):
        kind = self.template.currentText()
        self.canvas.caps = (list(DEFAULT_KEYCAPS) if kind == "V98 Pro"
                            else generic_template(kind))
        self.canvas._set_selected(-1)

    def _snap_to_photo(self):
        self.canvas.caps = snap_keys_to_photo(self.canvas.photo, self.canvas.caps)
        self.canvas.update()

    def _accept_layout(self):
        self._rename_selected()
        names = [cap.name for cap in self.canvas.caps]
        if not names or len(names) != len(set(names)):
            QMessageBox.warning(self, "键位未完成", "请至少绘制一颗键，并确保按键名称不重复。")
            return
        self.accept()

    def _begin_binding(self):
        if self.canvas.selected < 0:
            QMessageBox.information(self, "选择键位", "请先点选照片上的一颗键。")
            return
        self.await_binding = True
        self.bind_button.setText("请按实物键…")
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, watched, event):
        if self.await_binding and event.type() == QEvent.Type.KeyPress:
            vk = event.nativeVirtualKey()
            name = VK_NAMES.get(vk)
            if name is None and event.text().isprintable() and len(event.text()) == 1:
                name = event.text().upper()
            if name:
                index = self.canvas.selected
                cap = self.canvas.caps[index]
                self.canvas.caps[index] = Keycap(name, cap.label, cap.x, cap.y,
                                                 cap.w, cap.h, cap.leds)
                self._selection_changed(index)
                self.canvas.update()
            self.await_binding = False
            self.bind_button.setText("按键绑定")
            QApplication.instance().removeEventFilter(self)
            return True
        return super().eventFilter(watched, event)

    def done(self, result):
        if self.await_binding:
            QApplication.instance().removeEventFilter(self)
            self.await_binding = False
        super().done(result)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete and not self.name.hasFocus() and not self.label.hasFocus():
            self._delete_selected()
        else:
            super().keyPressEvent(event)


class DeviceSetupDialog(QDialog):
    def __init__(self, data_dir, current=None, parent=None):
        super().__init__(parent)
        self.data_dir = Path(data_dir)
        self.current = current or {}
        self.photo_path = self.current.get("photo") or ""
        self.layout = self.current.get("layout")
        self.layout_edited = False
        self.result_profile = None
        self.setWindowTitle("老必灯 · 键盘设置")
        self.setMinimumWidth(560)
        body = QVBoxLayout(self)
        body.setContentsMargins(26, 25, 26, 25)
        body.setSpacing(14)
        title = QLabel("先认识你的键盘")
        title.setObjectName("brandTitle")
        body.addWidget(title)
        intro = QLabel("自动读取已连接键盘的型号和设备编号。若设备只报告通用名称，可在下方修改。")
        intro.setWordWrap(True)
        intro.setObjectName("hint")
        body.addWidget(intro)
        scan_row = QHBoxLayout()
        self.detected = QComboBox()
        self.detected.setAccessibleName("已识别的键盘")
        self.detected.activated.connect(self._device_selected)
        scan_row.addWidget(self.detected, 1)
        scan = QPushButton("重新扫描")
        scan.setObjectName("secondary")
        scan.clicked.connect(self._scan_devices)
        scan_row.addWidget(scan)
        body.addLayout(scan_row)
        self.scan_status = QLabel("")
        self.scan_status.setObjectName("hint")
        self.scan_status.setWordWrap(True)
        body.addWidget(self.scan_status)
        fields = QFormLayout()
        fields.setSpacing(13)
        self.model = QLineEdit(self.current.get("model", ""))
        self.model.setPlaceholderText("例如 VGN V98 Pro")
        self.vid = QLineEdit(self.current.get("vid", ""))
        self.pid = QLineEdit(self.current.get("pid", ""))
        for entry in (self.vid, self.pid):
            entry.setMaxLength(4)
            entry.setPlaceholderText("4 位十六进制")
        fields.addRow("键盘型号", self.model)
        fields.addRow("USB VID", self.vid)
        fields.addRow("USB PID", self.pid)
        body.addLayout(fields)
        tip = QLabel("V98 Pro 示例：USB 有线 320F:5055；2.4G 接收器 320F:5088。不同版本请核对实际值。")
        tip.setObjectName("hint")
        tip.setWordWrap(True)
        body.addWidget(tip)
        photo_row = QHBoxLayout()
        self.photo_label = QLabel(Path(self.photo_path).name if self.photo_path else "尚未选择照片")
        self.photo_label.setObjectName("muted")
        choose = QPushButton("选择键盘照片")
        choose.setObjectName("secondary")
        choose.clicked.connect(self._choose_photo)
        photo_row.addWidget(choose)
        photo_row.addWidget(self.photo_label, 1)
        body.addLayout(photo_row)
        edit = QPushButton("在本地绘制 / 校准键位")
        edit.setObjectName("secondary")
        edit.clicked.connect(self._edit_layout)
        body.addWidget(edit)
        note = QLabel("新型号可先制作照片键位和屏幕灯效预览。实物逐键发光仍需该型号的灯控协议。")
        note.setObjectName("hint")
        note.setWordWrap(True)
        body.addWidget(note)
        actions = QHBoxLayout()
        actions.addStretch()
        if current:
            cancel = QPushButton("取消")
            cancel.setObjectName("quiet")
            cancel.clicked.connect(self.reject)
            actions.addWidget(cancel)
        save = QPushButton("保存并继续")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        actions.addWidget(save)
        body.addLayout(actions)
        for button in self.findChildren(QPushButton):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._scan_devices(auto_fill=not bool(current))

    def _scan_devices(self, auto_fill=False):
        try:
            devices = detect_keyboards()
        except OSError as error:
            devices = []
            self.scan_status.setText(f"扫描失败：{error}。仍可手动填写。")
        self.detected.blockSignals(True)
        self.detected.clear()
        self.detected.addItem("选择检测到的键盘", None)
        for device in devices:
            model = device["model"] or "型号未上报"
            label = f"{model}  ·  {device['vid']}:{device['pid']}  ·  {device['transport']}"
            self.detected.addItem(label, device)
        self.detected.blockSignals(False)
        if devices:
            self.scan_status.setText(
                f"找到 {len(devices)} 个键盘设备。请选择要控制的键盘；通用名称可以修改。")
            match = next((index for index, device in enumerate(devices, 1)
                          if device["vid"] == self.current.get("vid")
                          and device["pid"] == self.current.get("pid")), None)
            if match:
                self.detected.setCurrentIndex(match)
            elif auto_fill:
                known = next((index for index, device in enumerate(devices, 1)
                              if device["known"]), None)
                choice = known or (1 if len(devices) == 1 else None)
                if choice:
                    self.detected.setCurrentIndex(choice)
                    self._device_selected(choice)
        elif not self.scan_status.text():
            self.scan_status.setText("暂未检测到键盘。请检查连接，或手动输入型号和 VID/PID。")

    def _device_selected(self, index):
        device = self.detected.itemData(index)
        if not device:
            return
        if (self.vid.text().strip().upper(), self.pid.text().strip().upper()) != (
                device["vid"], device["pid"]):
            self.layout = None
            self.layout_edited = False
            self.photo_path = ""
            self.photo_label.setText("尚未选择照片")
        self.model.setText(device["model"])
        self.vid.setText(device["vid"])
        self.pid.setText(device["pid"])
        if not device["model"]:
            self.scan_status.setText("系统未上报可靠型号；VID/PID 已填入，请补充键盘型号。")

    def _choose_photo(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择键盘照片", str(Path.home()), PHOTO_FILTER)
        if path:
            if path != self.photo_path:
                self.layout = None
            self.photo_path = path
            self.photo_label.setText(Path(path).name)

    def _edit_layout(self):
        if not self.photo_path or not Path(self.photo_path).is_file():
            self._choose_photo()
        if not self.photo_path:
            return
        profile = {"model": self.model.text().strip(), "vid": self.vid.text().strip().upper(),
                   "pid": self.pid.text().strip().upper(), "layout": self.layout}
        initial = keycaps_from_profile(profile)
        editor = PhotoLayoutEditor(self.photo_path, initial or generic_template("104 键"), self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            self.layout = keycaps_to_data(editor.canvas.caps)
            self.layout_edited = True

    def _save(self):
        model = self.model.text().strip()
        vid = self.vid.text().strip().upper()
        pid = self.pid.text().strip().upper()
        if not model or not re.fullmatch(r"[0-9A-F]{4}", vid) or not re.fullmatch(r"[0-9A-F]{4}", pid):
            QMessageBox.warning(self, "请补全设备信息", "请填写键盘型号和 4 位十六进制的 VID、PID。")
            return
        profile = {"model": model, "vid": vid, "pid": pid}
        if model != self.current.get("model", model) and not self.layout_edited:
            self.layout = None
        if not is_supported_v98(profile) and not self.layout:
            QMessageBox.warning(self, "请绘制键位", "新型号请先选择照片，并在本地绘制或校准键位。")
            return
        if self.photo_path:
            source = Path(self.photo_path)
            if not source.is_file():
                QMessageBox.warning(self, "照片无法读取", "请重新选择键盘照片。")
                return
            destination = self.data_dir / f"keyboard-photo{source.suffix.lower()}"
            self.data_dir.mkdir(parents=True, exist_ok=True)
            if source.resolve() != destination.resolve():
                shutil.copy2(source, destination)
            profile["photo"] = str(destination)
        if self.layout:
            profile["layout"] = self.layout
        self.result_profile = profile
        self.accept()
