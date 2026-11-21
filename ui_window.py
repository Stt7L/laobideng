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
        painter.setBrush(QColor("#FAFAFA"))
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
        self._syncing = False
        self._resizing = False
        self._stack_dirty = True
        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.setInterval(16)
        self._sync_timer.timeout.connect(self.sync)
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
        event_type = event.type()
        if event_type in (QEvent.Type.Hide, QEvent.Type.Close):
            self._sync_timer.stop()
            self.shadow.hide()
        elif event_type in (QEvent.Type.Show, QEvent.Type.Move, QEvent.Type.Resize,
                            QEvent.Type.WindowStateChange, QEvent.Type.WindowActivate,
                            QEvent.Type.ScreenChangeInternal):
            if event_type in (QEvent.Type.Show, QEvent.Type.WindowActivate,
                              QEvent.Type.WindowStateChange):
                self._stack_dirty = True
            if self._resizing:
                # Geometry events still arrive in the native move/size loop.
                # Track them directly so the shadow doesn't wait for a timer.
                self.sync()
            else:
                if event_type in (QEvent.Type.Resize, QEvent.Type.WindowStateChange):
                    # Apply the region before the new-size paint.
                    self.sync(region_only=True)
                if not self._sync_timer.isActive():
                    self._sync_timer.start()
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

    def set_resizing(self, active):
        self._resizing = bool(active)
        self._sync_timer.stop()
        if not active:
            self._stack_dirty = True
        self.sync()

    def sync(self, region_only=False):
        if self._syncing:
            return
        self._syncing = True
        try:
            self._sync_window(region_only)
        finally:
            self._syncing = False

    def _sync_window(self, region_only=False):
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
                succeeded = self.user32.SetWindowRgn(hwnd, None, False)
            else:
                # Put the hard GDI edge inside the companion surface's fully
                # opaque pixels, including diagonal steps at fractional DPI.
                inset = math.ceil(1.5 * ratio)
                radius = round(WINDOW_RADIUS * ratio) - inset
                region = self.gdi32.CreateRoundRectRgn(inset, inset, width - inset, height - inset,
                                                      radius * 2, radius * 2)
                succeeded = self.user32.SetWindowRgn(hwnd, region, False) if region else False
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
        if region_only:
            return
        margin = self.shadow.MARGIN
        geometry = window.frameGeometry().adjusted(-margin, -margin, margin, margin)
        if self.shadow.geometry() != geometry:
            self.shadow.setGeometry(geometry)
        if not self.shadow.isVisible():
            self.shadow.show()
            self._stack_dirty = True
        # Immediately behind this window, never above its controls or another
        # application; SWP_NOMOVE | NOSIZE | NOACTIVATE avoids stealing focus.
        if self._stack_dirty:
            self.user32.SetWindowPos(int(self.shadow.winId()), hwnd, 0, 0, 0, 0, 0x0013)
            self._stack_dirty = False
