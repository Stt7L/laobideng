"""UI regression checks using an isolated, hardware-free preview window."""

import argparse
import ctypes
from pathlib import Path
import sys
import time

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QFontInfo, QPainter, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import ui_app
from layout import KEYCAPS
from ui_controls import SurfaceButton
from ui_select import SurfaceComboBox
from ui_window import WINDOW_RADIUS, WINDOW_INSET, SIDEBAR_RADIUS


def wait_for(predicate, timeout=1.2):
    deadline = time.perf_counter() + timeout
    while not predicate() and time.perf_counter() < deadline:
        QTest.qWait(20)


def run(output, interactive=False):
    app = QApplication([sys.argv[0], "-platform", "windows:fontengine=freetype"])
    app.setStyle("Fusion")
    ui_app.load_ui_font()
    app.setFont(ui_app.ui_display_font(10))
    app.setStyleSheet(ui_app.ui_stylesheet())
    # Never read, overwrite or exercise the user's device configuration.
    ui_app.read_settings = lambda: {
        "effect": "ripple", "base": "#FFFFFF", "accent": "#FF6157",
        "brightness": 1, "base_brightness": 1, "accent_brightness": 1,
        "pairing_mood": "撞色", "pairings_expanded": True,
    }
    window = ui_app.MainWindow(preview=True)
    window.show()
    passed = []

    def check(condition, name):
        assert condition, name
        passed.append(name)

    try:
        check(QFontInfo(app.font()).family() == "HarmonyOS Sans SC", "bundled font")
        check(all(isinstance(button, SurfaceButton) for button in window.nav_buttons),
              "shared button contract")
        for width, height in ((880, 600), (960, 650), (1180, 760), (1600, 1000)):
            window.resize(width, height)
            QTest.qWait(240)
            for page in range(5):
                window._show_section(page)
                QTest.qWait(240)
                scroll = window.page_stack.currentWidget()
                for card, owner, _limit in window._centered_cards:
                    if owner is scroll and not card.isHidden():
                        point = card.mapTo(scroll.widget(), QPoint(0, 0))
                        check(point.x() >= 0 and point.x() + card.width() <=
                              scroll.viewport().width(), f"page {page} fits {width}x{height}")
                if output:
                    window.grab().save(str(output / f"ui-{width}-{page}.png"))
            check(not window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground),
                  f"opaque window {width}")
        check(window.preview.minimumHeight() <= 340, "adaptive preview height")

        window._show_section(2)
        slider = window.brightness_slider
        slider.setValue(0)
        # Native timer delivery can be coalesced on a busy Windows desktop;
        # wait for completion rather than assuming a fixed number of ticks.
        wait_for(lambda: slider._visual_fraction == 0)
        check(slider._visual_fraction == 0, "slider zero endpoint")
        slider.setValue(1000)
        wait_for(lambda: slider._visual_fraction == 1)
        check(slider._visual_fraction == 1, "slider full endpoint")
        QTest.mousePress(slider, Qt.MouseButton.LeftButton,
                         pos=QPoint(slider.EDGE, slider.height() // 2))
        QTest.mouseMove(slider, QPoint(round(slider._position(.653)), slider.height() // 2))
        check(abs(slider._visual_fraction - slider._fraction()) < 0.0001,
              "slider directly follows pointer")
        check(abs(window.engine.brightness - slider.value() / 1000) < 0.0001,
              "rounded display does not feed back")
        QTest.mouseRelease(slider, Qt.MouseButton.LeftButton,
                           pos=QPoint(round(slider._position(.653)), slider.height() // 2))
        old = slider.value()
        wheel = QWheelEvent(QPointF(30, 20), QPointF(slider.mapToGlobal(QPoint(30, 20))),
                            QPoint(), QPoint(0, 120), Qt.MouseButton.NoButton,
                            Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        app.sendEvent(slider, wheel)
        check(slider.value() == old, "wheel cannot change slider")

        window._select_effect("custom_canvas")
        window._show_section(0)
        window.scroll.verticalScrollBar().setValue(0)
        QTest.qWait(240)
        preview = window.preview
        preview.setFocus(Qt.FocusReason.TabFocusReason)
        QTest.keyClick(preview, Qt.Key.Key_Home)
        name = preview._focused_key
        QTest.keyClick(preview, Qt.Key.Key_Space)
        check(name in window.engine.custom_canvas_keys, "keyboard can draw")
        QTest.keyClick(preview, Qt.Key.Key_Space)
        check(name not in window.engine.custom_canvas_keys, "second click cancels")
        QTest.keyClick(preview, Qt.Key.Key_Right)
        check(preview._focused_key != name, "spatial keyboard navigation")
        QTest.keyClick(preview, Qt.Key.Key_Space)
        QTest.keyClick(preview, Qt.Key.Key_Delete)
        check(preview._focused_key not in window.engine.custom_canvas_keys, "keyboard can erase")

        check(ui_app.keyboard_cap_color((255, 0, 0)).getRgb()[:3] == (255, 0, 0),
              "preview preserves saturated hue")
        check(ui_app.keyboard_cap_color((6, 6, 6), ((255, 255, 255),)).getRgb()[:3] ==
              (255, 255, 255), "dim white background stays white")
        check(ui_app.keyboard_cap_color((0, 2, 6), ((0, 85, 255),)).getRgb()[:3] ==
              (0, 85, 255), "dim blue background retains selected color")
        check(ui_app.keyboard_cap_color((14, 39, 39), ((78, 219, 219),)).getRgb()[:3] ==
              (78, 219, 219), "dim cyan background retains selected color")
        check(ui_app.keyboard_cap_color((12, 24, 35)).getRgb()[:3] == (69, 137, 200),
              "unmatched low-power color keeps hue visible")
        check(ui_app.keyboard_cap_color((0, 0, 0)).name() == "#e7e7e9",
              "zero light stays neutral off")
        references = ((0, 85, 255), (255, 97, 87))
        colors = [ui_app.keyboard_cap_color(rgb, references).getRgb()[:3]
                  for rgb in ((1, 14, 44), (2, 14, 44))]
        check(max(abs(a - b) for a, b in zip(*colors)) < 20,
              "animated hue does not jump at reference boundary")
        preview.clearFocus()
        preview._hover_key = None
        frame = [(100, 130, 160)] * 128
        for index, rgb in zip((80, 82, 83, 57, 58, 59),
                              ((255, 0, 0), (0, 255, 0), (0, 0, 255)) * 2):
            frame[index] = rgb
        original_preview = window.engine.preview_frame
        window.engine.preview_frame = lambda: frame
        rendered = preview.grab()
        image = rendered.toImage()
        ratio = rendered.devicePixelRatio()
        scale, x, y = preview._transform()
        long_caps = [cap for cap in KEYCAPS if cap.name in ("Space", "Enter")]
        check(len(long_caps) == 2, "both physical long keys are checked")
        for cap in long_caps:
            py = round(y + (cap.y - 43 + cap.h - 8) * scale)
            points = [round(x + (cap.x - 48 + cap.w * portion) * scale)
                      for portion in (.12, .88)]
            check(image.pixelColor(round(points[0] * ratio), round(py * ratio)) ==
                  image.pixelColor(round(points[1] * ratio), round(py * ratio)),
                  f"{cap.name} is one uniform key")
        window.engine.preview_frame = original_preview

        original_base, original_effect = window.engine.base, window.engine.effect
        window.engine.effect = "audio_spectrum"
        cap = next(cap for cap in KEYCAPS if cap.name == "Esc")
        sample = QPoint(round(x + (cap.x - 48 + cap.w / 2) * scale),
                        round(y + (cap.y - 43 + cap.h - 8) * scale))
        for name, base, dim in (("white", (255, 255, 255), (46, 46, 46)),
                               ("blue", (0, 85, 255), (0, 15, 46)),
                               ("cyan", (78, 219, 219), (14, 39, 39))):
            window.engine.base = base
            frame = [dim] * 128
            window.engine.preview_frame = lambda: frame
            rendered = preview.grab()
            ratio = rendered.devicePixelRatio()
            pixel = QPoint(round(sample.x() * ratio), round(sample.y() * ratio))
            check(rendered.toImage().pixelColor(pixel).getRgb()[:3] == base,
                  f"{name} background displayed in physical key")
            check(frame[0] == dim, f"{name} preview does not alter device frame")
            if output:
                rendered.save(str(output / f"keyboard-{name}.png"))
        window.engine.base, window.engine.effect = original_base, original_effect
        window.engine.preview_frame = original_preview

        window._show_section(1)
        original = window.engine.base
        window._open_color_editor("base")
        window._set_picker_color(QColor("#31A4F2"))
        window._cancel_color_editor()
        check(window.engine.base == original, "cancel color restores original")
        window._open_color_editor("base")
        window.hex_input.setText("#invalid")
        window._apply_color()
        check(window.editing_color == "base", "invalid color cannot apply")
        window._cancel_color_editor()
        window.engine.global_color = (44, 120, 200)
        window._sync_global_color()
        check(window.engine.base == window.engine.accent == (44, 120, 200),
              "global color updates both colors")

        window.preset_name_input.setText("UI check")
        window._save_preset()
        window._select_effect("solid")
        check(window.engine.base == (44, 120, 200), "preset follows effect switch")
        window._show_section(3)
        combo = window.preset_combo
        check(isinstance(combo, SurfaceComboBox), "preset uses shared surface selector")
        combo.setCurrentIndex(0)
        combo.showPopup()
        QTest.qWait(220)
        popup = combo._popup
        check(popup.isVisible() and popup.list.font().family() == "HarmonyOS Sans SC",
              "rounded popup inherits bundled font")
        check(popup.panel_rect().width() == combo.width(), "popup aligns with selector edges")
        if output:
            popup.grab().save(str(output / "preset-popup.png"))
        QTest.keyClick(popup.list, Qt.Key.Key_Down)
        QTest.keyClick(popup.list, Qt.Key.Key_Return)
        check(combo.currentText() == "UI check" and not popup.isVisible(),
              "preset keyboard selection commits")
        combo.showPopup()
        QTest.keyClick(popup.list, Qt.Key.Key_Up)
        QTest.keyClick(popup.list, Qt.Key.Key_Escape)
        check(combo.currentText() == "UI check" and not popup.isVisible(),
              "preset escape keeps existing selection")
        if output:
            combo.showPopup()
            QTest.qWait(180)
            composite = window.grab()
            painter = QPainter(composite)
            painter.drawPixmap(window.mapFromGlobal(popup.pos()), popup.grab())
            painter.end()
            composite.save(str(output / "presets-expanded.png"))
            combo.hidePopup()
        window._show_section(0)
        window._toggle_quick_panel()
        QTest.qWait(230)
        QTest.keyClick(window.quick_button, Qt.Key.Key_Escape)
        check(not window.quick_panel.isVisible(), "escape closes quick control")
        window.effect_search.setText("no-matching-effect-782")
        check(window.gallery_empty.isVisible(), "search has explicit empty state")
        window.effect_search.clear()
        window._reveal_current_effect()
        QTest.qWait(240)
        check(window.gallery_category == ui_app.EFFECT_CATEGORY[window.engine.effect],
              "current effect can be located")
        check(window.effect_buttons[window.engine.effect].accessibleName() != "",
              "custom option has accessible name")
        check(WINDOW_RADIUS == 32 and WINDOW_RADIUS - WINDOW_INSET == SIDEBAR_RADIUS,
              "outer and sidebar curves are concentric")
        check(window._resize_edges(QPoint(16, 16)) == Qt.Edge.LeftEdge | Qt.Edge.TopEdge,
              "diagonal resizing follows the enlarged corner")
        check("numpy" not in sys.modules and "soundcard" not in sys.modules,
              "ordinary UI does not load audio analysis dependencies")
        window.scroll.verticalScrollBar().setValue(0)
        QTest.qWait(240)
        frame_controller = window._window_frame
        check(frame_controller.shadow.isVisible(), "window has an independent shadow")
        check(frame_controller.shadow.windowFlags() & Qt.WindowType.WindowTransparentForInput,
              "shadow cannot intercept clicks")
        frame_controller.gdi32.CreateRectRgn.argtypes = [ctypes.c_int] * 4
        frame_controller.gdi32.CreateRectRgn.restype = ctypes.c_void_p
        region = frame_controller.gdi32.CreateRectRgn(0, 0, 0, 0)
        # Set pointer signatures explicitly on 64-bit Windows.
        native = frame_controller.user32
        native.GetWindowRgn.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        frame_controller.gdi32.PtInRegion.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        try:
            check(native.GetWindowRgn(int(window.winId()), region) == 3,
                  "window uses a real rounded native region")
            ratio = window.devicePixelRatioF()
            check(not frame_controller.gdi32.PtInRegion(region, round(6 * ratio), round(6 * ratio)),
                  "actual native corner is larger than the old eight-pixel corner")
            check(frame_controller.gdi32.PtInRegion(region, round(40 * ratio), round(40 * ratio)),
                  "native region retains the interior")
        finally:
            frame_controller.gdi32.DeleteObject(region)
        window._last_preview_update = 0
        window._last_preview_signature = None
        clock = time.monotonic() + .3
        check(window._refresh_preview_frame(clock), "changed visible frame refreshes")
        check(not window._refresh_preview_frame(clock + .04), "identical frame is not repainted")
        window.showMinimized()
        QTest.qWait(100)
        check(not frame_controller.shadow.isVisible(), "minimizing hides companion shadow")
        check(not window._refresh_preview_frame(clock + 1), "minimized preview does not repaint")
        window.showMaximized()
        QTest.qWait(120)
        check(not frame_controller.shadow.isVisible(), "maximized window has no floating shadow")
        window.showNormal()
        QTest.qWait(240)
        check(frame_controller.shadow.isVisible(), "restoring reattaches rounded shadow")
        window._show_section(1)
        check(not window._refresh_preview_frame(clock + 2), "other pages do not repaint keyboard")
        window._show_section(0)
        window.hide()
        check(not frame_controller.shadow.isVisible(), "tray state leaves no orphan shadow")
        window.show()
        frame_controller.user32.ShowWindow(int(window.winId()), 0)
        frame_controller.sync()
        check(not frame_controller.content_visible() and not frame_controller.shadow.isVisible(),
              "native-hidden windows leave no floating shadow")
        window.show_window()
        QTest.qWait(150)
        check(frame_controller.content_visible() and frame_controller.shadow.isVisible(),
              "tray and shortcut requests restore native visibility")
        if interactive:
            window.setWindowTitle("老必灯 · 设计检查")
            window.resize(1180, 800)
            window._select_effect("audio_spectrum")
            window.engine.last_frame = window.engine.frame(0)
            window.scroll.verticalScrollBar().setValue(0)
            print(f"READY: {len(passed)} checks; interactive isolated preview", flush=True)
            app.exec()
    finally:
        window.close()
        app.processEvents()
    print(f"PASS: {len(passed)} UI checks; preview only, no device writes")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-dir", type=Path)
    parser.add_argument("--interactive", action="store_true")
    args = parser.parse_args()
    if args.capture_dir:
        args.capture_dir.mkdir(parents=True, exist_ok=True)
    run(args.capture_dir, args.interactive)
