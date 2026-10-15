"""A short-lived tray action surface using the workbench's rounded controls."""

import ctypes
from ctypes import wintypes
import time

from PySide6.QtCore import QEvent, QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter
from PySide6.QtWidgets import QApplication, QFrame, QVBoxLayout, QWidget

from ui_controls import SurfaceButton


class TrayMenu(QWidget):
    def __init__(self, parent, icon_factory):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.NoDropShadowWindowHint)
        self.setWindowTitle("老必灯 · 快捷菜单")
        self.setObjectName("trayActionPopup")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay)
        self.setFixedWidth(216)
        self._opened_at = 0.0
        self._anchor_host = None
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self.user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self._icons = icon_factory
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 26)
        layout.setSpacing(3)
        self.buttons = []
        self.show_button = self._button("显示窗口", "window_restore", parent.show_window, layout)
        self.toggle_button = self._button("暂停灯效", "pause", parent._toggle_effect, layout)
        line = QFrame(self)
        line.setFixedHeight(1)
        line.setStyleSheet("background: #E9E9EB; border: none; margin: 0 9px;")
        layout.addSpacing(3)
        layout.addWidget(line)
        layout.addSpacing(3)
        self.quit_button = self._button("退出程序", "power", parent.exit_app, layout)
        self.adjustSize()
        self.watchdog = QTimer(self)
        self.watchdog.setInterval(120)
        self.watchdog.timeout.connect(self._check_owner)
        app = QApplication.instance()
        app.applicationStateChanged.connect(self._app_state_changed)

    def _button(self, text, icon, callback, layout):
        button = SurfaceButton(text, self)
        button.setObjectName("sideNav")
        button.setIcon(self._icons(icon))
        button.setAccessibleName(text)
        button.setFixedHeight(38)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet("padding: 0 10px; border: none; background: transparent;")
        button.clicked.connect(lambda: self._invoke(callback))
        layout.addWidget(button)
        self.buttons.append(button)
        return button

    def _invoke(self, callback):
        self.hide()
        # Release the popup grab before showing a window or exiting.
        QTimer.singleShot(0, callback)

    def set_active(self, active):
        self.toggle_button.setText("暂停灯效" if active else "继续灯效")
        self.toggle_button.setAccessibleName(self.toggle_button.text())
        self.toggle_button.setIcon(self._icons("pause" if active else "play"))

    def popup(self, position=None):
        if self.isVisible():
            self.hide()
            return
        position = position if position is not None else QCursor.pos()
        foreground = self.user32.GetForegroundWindow()
        class_name = ctypes.create_unicode_buffer(128)
        self.user32.GetClassNameW(foreground, class_name, len(class_name))
        self._anchor_host = None
        if class_name.value in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd", "NotifyIconOverflowWindow", "TopLevelWindowForOverflowXamlIsland"):
            rect = wintypes.RECT()
            if self.user32.GetWindowRect(foreground, ctypes.byref(rect)):
                self._anchor_host = (foreground, (rect.left, rect.top, rect.right, rect.bottom))
        self.adjustSize()
        screen = QGuiApplication.screenAt(position) or self.screen()
        bounds = screen.availableGeometry()
        x = max(bounds.left(), min(position.x() - self.width() + 20, bounds.right() - self.width() + 1))
        y = max(bounds.top(), min(position.y() - self.height() + 10, bounds.bottom() - self.height() + 1))
        self.move(QPoint(x, y))
        self._opened_at = time.monotonic()
        self.show()
        self.user32.SetForegroundWindow(int(self.winId()))
        self.activateWindow()
        self.show_button.setFocus(Qt.FocusReason.PopupFocusReason)
        self.watchdog.start()

    def panel_rect(self):
        return QRectF(self.rect()).adjusted(14, 10, -14, -18)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        panel = self.panel_rect()
        for spread in range(12, 0, -1):
            painter.setBrush(QColor(20, 20, 24, 2 if spread > 5 else 3))
            shadow = panel.translated(0, 4).adjusted(-spread, -spread, spread, spread)
            painter.drawRoundedRect(shadow, 18 + spread, 18 + spread)
        painter.setBrush(QColor("#FCFCFC"))
        painter.drawRoundedRect(panel, 18, 18)

    def _check_owner(self):
        if not self.isVisible() or time.monotonic() - self._opened_at < .18:
            return
        # Native foreground checks also catch shell/fullscreen transitions for
        # which Qt sometimes misses WindowDeactivate on an unowned tray popup.
        if self.user32.GetForegroundWindow() != int(self.winId()):
            self.hide()
            return
        if self._anchor_host:
            hwnd, previous = self._anchor_host
            rect = wintypes.RECT()
            if (not self.user32.IsWindowVisible(hwnd) or
                    not self.user32.GetWindowRect(hwnd, ctypes.byref(rect)) or
                    previous != (rect.left, rect.top, rect.right, rect.bottom)):
                self.hide()

    def _app_state_changed(self, state):
        if state != Qt.ApplicationState.ApplicationActive and self.isVisible():
            QTimer.singleShot(0, self._check_owner)

    def event(self, event):
        if event.type() == QEvent.Type.WindowDeactivate and self.isVisible():
            self.hide()
        return super().event(event)

    def hideEvent(self, event):
        if hasattr(self, "watchdog"):
            self.watchdog.stop()
        super().hideEvent(event)

    def mousePressEvent(self, event):
        if not self.panel_rect().contains(event.position()):
            self.hide()
            event.accept()
        else:
            super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        elif event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Home, Qt.Key.Key_End):
            current = next((i for i, button in enumerate(self.buttons) if button.hasFocus()), 0)
            target = (current + (1 if event.key() == Qt.Key.Key_Down else -1)) % len(self.buttons)
            if event.key() == Qt.Key.Key_Home:
                target = 0
            elif event.key() == Qt.Key.Key_End:
                target = len(self.buttons) - 1
            self.buttons[target].setFocus(Qt.FocusReason.TabFocusReason)
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            button = next((button for button in self.buttons if button.hasFocus()), self.show_button)
            button.click()
        else:
            super().keyPressEvent(event)
