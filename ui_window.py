"""Large, antialiased corners around an opaque Windows content window.

Only a small, input-transparent companion surface is layered. The app itself
stays opaque, with no window-opacity animations or full-window blur effect.
"""

import ctypes
from ctypes import wintypes
import logging
import math
import sys

from PySide6.QtCore import QEvent, QObject, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

LOG = logging.getLogger("vgn-ripple")
WINDOW_RADIUS = 32
WINDOW_INSET = 12
SIDEBAR_RADIUS = WINDOW_RADIUS - WINDOW_INSET


class _WindowShadow(QWidget):
    MARGIN = 24
    CORNER = WINDOW_RADIUS + MARGIN + 2

    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.NoDropShadowWindowHint |
                         Qt.WindowType.WindowTransparentForInput |
                         Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setObjectName("windowShadow")
        self._tile = None
        self._tile_ratio = None

    def _shadow_tile(self):
        ratio = self.devicePixelRatioF()
        if self._tile is not None and self._tile_ratio == ratio:
            return self._tile
        side = self.CORNER * 2 + 1
        tile = QPixmap(math.ceil(side * ratio), math.ceil(side * ratio))
        tile.setDevicePixelRatio(ratio)
        tile.fill(Qt.GlobalColor.transparent)
        painter = QPainter(tile)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        panel = QRectF(self.MARGIN, self.MARGIN,
                       side - self.MARGIN * 2, side - self.MARGIN * 2)
        for spread in range(20, 0, -1):
            alpha = 1 if spread > 10 else 2
            painter.setBrush(QColor(20, 20, 24, alpha))
            painter.drawRoundedRect(panel.translated(0, 5).adjusted(
                -spread, -spread, spread, spread), WINDOW_RADIUS + spread,
                WINDOW_RADIUS + spread)
        painter.setBrush(QColor("#F6F6F6"))
        painter.drawRoundedRect(panel, WINDOW_RADIUS, WINDOW_RADIUS)
        painter.end()
        self._tile, self._tile_ratio = tile, ratio
        return tile

    def paintEvent(self, _event):
        tile = self._shadow_tile()
        ratio = tile.devicePixelRatio()
        edge = self.CORNER
        source_side = edge * 2 + 1
        source = (0, edge, edge + 1, source_side)
        target_x = (0, edge, self.width() - edge, self.width())
        target_y = (0, edge, self.height() - edge, self.height())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        # Nine-slice the cached corner/shadow tile. Window resizing never
        # re-blurs the full interface or regenerates a full-size shadow image.
        for row in range(3):
            for column in range(3):
                if row == 1 and column == 1:
                    continue  # The opaque app owns the entire center.
                dest = QRectF(target_x[column], target_y[row],
                              target_x[column + 1] - target_x[column],
                              target_y[row + 1] - target_y[row])
                src = QRectF(source[column] * ratio, source[row] * ratio,
                             (source[column + 1] - source[column]) * ratio,
                             (source[row + 1] - source[row]) * ratio)
                painter.drawPixmap(dest, tile, src)


class RoundedWindowFrame(QObject):
    """Keep a large native region and its cached shadow in sync with a window."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.shadow = _WindowShadow() if sys.platform == "win32" else None
        self._region_signature = None
        self._pending = False
        self._syncing = False
        if self.shadow is not None:
            self.user32 = ctypes.WinDLL("user32", use_last_error=True)
            self.gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
            self.user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
            self.user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
            self.user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
            self.user32.SetWindowRgn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool]
            self.user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            self.gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
            self.gdi32.CreateRoundRectRgn.restype = ctypes.c_void_p
            self.gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
            window.installEventFilter(self)
            window.destroyed.connect(self.shadow.deleteLater)
            QApplication.instance().aboutToQuit.connect(self.shadow.close)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Hide, QEvent.Type.Close):
            self.shadow.hide()
        elif event.type() in (QEvent.Type.Show, QEvent.Type.Move, QEvent.Type.Resize,
                              QEvent.Type.WindowStateChange, QEvent.Type.WindowActivate,
                              QEvent.Type.ScreenChangeInternal):
            if event.type() in (QEvent.Type.Resize, QEvent.Type.WindowStateChange):
                # Apply the region before the new-size paint. A deferred old
                # region would briefly expose desktop in the newly grown area.
                self.sync()
            # Coalesce geometry/activation events from the same event-loop turn.
            if not self._pending:
                self._pending = True
                QTimer.singleShot(0, self.sync)
        return False

    def content_visible(self):
        if not self.window.isVisible() or self.window.isMinimized():
            return False
        return (bool(self.user32.IsWindowVisible(int(self.window.winId())))
                if self.shadow is not None else True)

    def ensure_visible(self):
        # STARTF_USESHOWWINDOW can hide the first native ShowWindow even though
        # Qt reports the widget visible. A tray/shortcut request must still open
        # the actual window, with no floating shadow left on the desktop.
        if self.shadow is not None and self.window.isVisible():
            self.user32.ShowWindow(int(self.window.winId()), 5)
            self.sync()

    def sync(self):
        if self._syncing:
            return
        self._syncing = True
        try:
            self._sync_window()
        finally:
            self._syncing = False

    def _sync_window(self):
        self._pending = False
        if self.shadow is None:
            return
        window = self.window
        if not window.isVisible() or window.isMinimized():
            self.shadow.hide()
            return
        hwnd = int(window.winId())
        if not self.user32.IsWindowVisible(hwnd):
            self.shadow.hide()
            return
        square = window.isMaximized() or window.isFullScreen()
        rect = wintypes.RECT()
        if not self.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return
        width, height = rect.right - rect.left, rect.bottom - rect.top
        ratio = window.devicePixelRatioF()
        signature = (width, height, ratio, square)
        if signature != self._region_signature:
            if square:
                succeeded = self.user32.SetWindowRgn(hwnd, None, True)
            else:
                # Leave one physical pixel for the antialiased companion edge.
                radius = round(WINDOW_RADIUS * ratio)
                region = self.gdi32.CreateRoundRectRgn(1, 1, width - 1, height - 1,
                                                      radius * 2, radius * 2)
                succeeded = self.user32.SetWindowRgn(hwnd, region, True) if region else False
                if region and not succeeded:
                    self.gdi32.DeleteObject(region)
            if succeeded:
                self._region_signature = signature
            else:
                LOG.warning("Could not apply custom window corners: %s", ctypes.get_last_error())
                self.shadow.hide()
                return
        if square:
            self.shadow.hide()
            return
        margin = self.shadow.MARGIN
        geometry = window.frameGeometry().adjusted(-margin, -margin, margin, margin)
        if self.shadow.geometry() != geometry:
            self.shadow.setGeometry(geometry)
        if not self.shadow.isVisible():
            self.shadow.show()
        # Immediately behind this window, never above its controls or another
        # application; SWP_NOMOVE | NOSIZE | NOACTIVATE avoids stealing focus.
        self.user32.SetWindowPos(int(self.shadow.winId()), hwnd, 0, 0, 0, 0, 0x0013)
