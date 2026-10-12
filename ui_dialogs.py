"""Opaque desktop dialogs sharing the workspace's window treatment."""

import ctypes

from PySide6.QtCore import QEvent, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QScrollArea,
    QVBoxLayout,
)

from ui_controls import SurfaceButton
from ui_window import RoundedWindowFrame


def _dialog_font(pixels, weight=QFont.Weight.Normal):
    font = QFont(QApplication.font())
    font.setPixelSize(pixels)
    font.setWeight(weight)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias |
                          QFont.StyleStrategy.NoSubpixelAntialias)
    font.setHintingPreference(QFont.HintingPreference.PreferVerticalHinting)
    return font


def _close_icon():
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#707075"), 2.4,
                        Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawLine(10, 10, 22, 22)
    painter.drawLine(22, 10, 10, 22)
    painter.end()
    return QIcon(pixmap)


class ModernDialog(QDialog):
    """A native-shadow shell with a scrollable body and a pinned action row."""

    def __init__(self, title, subtitle="", parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog |
                            Qt.WindowType.FramelessWindowHint)
        self.setObjectName("modernDialog")
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(palette.ColorRole.Window, QColor("#F6F6F6"))
        self.setPalette(palette)
        self.setAccessibleName(title)
        self._native_frame_ready = False
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.header = QFrame()
        self.header.setObjectName("dialogHeader")
        self.header.setStyleSheet("QFrame#dialogHeader { background: #F6F6F6; border: none; }")
        self.header.installEventFilter(self)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(24, 20, 20, 16)
        header_layout.setSpacing(16)
        heading = QVBoxLayout()
        heading.setSpacing(4)
        self.title_label = QLabel(title)
        self.title_label.setFont(_dialog_font(19, QFont.Weight.DemiBold))
        self.title_label.setStyleSheet("font-size: 19px; font-weight: 600; color: #1D1D1F;")
        self.title_label.installEventFilter(self)
        heading.addWidget(self.title_label)
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("hint")
        self.subtitle_label.setStyleSheet("font-size: 13px; color: #707075;")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.installEventFilter(self)
        self.subtitle_label.setVisible(bool(subtitle))
        heading.addWidget(self.subtitle_label)
        header_layout.addLayout(heading, 1)
        self.close_button = SurfaceButton()
        self.close_button.setObjectName("windowClose")
        self.close_button.setAutoDefault(False)
        self.close_button.setFixedSize(30, 30)
        self.close_button.setIcon(_close_icon())
        self.close_button.setIconSize(QSize(16, 16))
        self.close_button.setAccessibleName("关闭此窗口")
        self.close_button.setToolTip("关闭此窗口 · Esc")
        self.close_button.clicked.connect(self.reject)
        header_layout.addWidget(self.close_button,
                                alignment=Qt.AlignmentFlag.AlignTop)
        root.addWidget(self.header)

        self.content_scroll = QScrollArea()
        self.content_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.content_scroll.setWidgetResizable(True)
        self.content_scroll.setStyleSheet(
            "QScrollArea { background: #F6F6F6; border: none; }"
            "QScrollArea > QWidget > QWidget { background: #F6F6F6; }"
            "QScrollBar:horizontal { background: transparent; height: 7px; margin: 0; }"
            "QScrollBar::handle:horizontal { background: #D4D4D4; border-radius: 3px; min-width: 36px; }"
            "QScrollBar::handle:horizontal:hover { background: #AFAFAF; }"
            "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }"
            "QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: none; }")
        self.content_scroll.setViewportMargins(16, 0, 16, 0)
        self.content = QFrame()
        self.content.setObjectName("dialogContent")
        self.content.setStyleSheet(
            "QFrame#dialogContent { background: #FFFFFF; border: 1px solid #ECECEE;"
            " border-radius: 18px; }")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(20, 20, 20, 20)
        self.content_layout.setSpacing(14)
        self.content_scroll.setWidget(self.content)
        root.addWidget(self.content_scroll, 1)

        self.footer = QFrame()
        self.footer.setObjectName("dialogFooter")
        self.footer.setStyleSheet(
            "QFrame#dialogFooter { background: #F6F6F6; border: none; }")
        self.actions = QHBoxLayout(self.footer)
        self.actions.setContentsMargins(24, 16, 24, 20)
        self.actions.setSpacing(10)
        root.addWidget(self.footer)

    def fit_to_available(self, preferred_size, available=None):
        """Keep actions on screen, even when Windows uses a large text scale."""
        if available is None:
            screen = self.parentWidget().screen() if self.parentWidget() else self.screen()
            screen = screen or QApplication.primaryScreen()
            available = screen.availableGeometry()
        available = QRect(available)
        max_width = max(1, available.width() - 48)
        max_height = max(1, available.height() - 48)
        self.setMinimumSize(min(560, max_width), min(360, max_height))
        self.resize(min(preferred_size.width(), max_width),
                    min(preferred_size.height(), max_height))
        anchor = self.parentWidget().frameGeometry() if self.parentWidget() else available
        x = anchor.center().x() - self.width() // 2
        y = anchor.center().y() - self.height() // 2
        self.move(max(available.left() + 24,
                      min(x, available.right() - self.width() - 23)),
                  max(available.top() + 24,
                      min(y, available.bottom() - self.height() - 23)))

    def showEvent(self, event):
        super().showEvent(event)
        if not self._native_frame_ready:
            self._native_frame_ready = True
            self._apply_native_frame()
            self._window_frame = RoundedWindowFrame(self)
            self._window_frame.sync()

    def _apply_native_frame(self):
        try:
            hwnd = int(self.winId())
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
            user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
            user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                                 ctypes.c_ssize_t]
            user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
            user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                           ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            style = user32.GetWindowLongPtrW(hwnd, -16)
            user32.SetWindowLongPtrW(hwnd, -16, style | 0x00040000 | 0x00C00000)
            user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0027)
            dwm = ctypes.WinDLL("dwmapi", use_last_error=True)
            dwm.DwmSetWindowAttribute.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                                   ctypes.c_void_p, ctypes.c_uint]
            for attribute, value in ((20, ctypes.c_int(0)),
                                     (33, ctypes.c_int(1)),
                                     (2, ctypes.c_int(1)),
                                     (34, ctypes.c_uint(0xFFFFFFFE))):
                dwm.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value),
                                         ctypes.sizeof(value))
        except (AttributeError, OSError):
            pass

    def eventFilter(self, watched, event):
        if watched in (getattr(self, "header", None),
                       getattr(self, "title_label", None),
                       getattr(self, "subtitle_label", None)):
            if (event.type() == QEvent.Type.MouseButtonPress and
                    event.button() == Qt.MouseButton.LeftButton and
                    self.windowHandle() is not None):
                return self.windowHandle().startSystemMove()
        return super().eventFilter(watched, event)
