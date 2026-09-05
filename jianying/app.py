"""应用总装：托盘 + 热键 + 截图/编辑/贴图/滚动流程编排。"""
from __future__ import annotations

from PyQt6.QtCore import QObject, QRect, pyqtSlot
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication, QMessageBox

from jianying.capture.grabber import grab_virtual_desktop
from jianying.capture.region import RegionOverlay
from jianying.capture.scroll import ScrollWorker
from jianying.editor.window import EditorWindow
from jianying.hotkey import HotkeyManager
from jianying.pin import PinWindow
from jianying.tray import TrayIcon

MODE_SHOT = "shot"      # 截图 → 编辑器
MODE_SCROLL = "scroll"  # 框选 → 滚动采集 → 拼接 → 编辑器


class JianyingApp(QObject):
    def __init__(self):
        super().__init__()
        self._overlay: RegionOverlay | None = None
        self._editor: EditorWindow | None = None
        self._pins: list[PinWindow] = []
        self._last_capture: QImage | None = None
        self._scroll_worker: ScrollWorker | None = None
        self._recorder: object | None = None       # RecorderWorker（延迟导入）
        self._record_bar: object | None = None     # RecordBar 悬浮控制条
        self._record_frame: object | None = None   # RecordFrame 红框提示
        self._mode = MODE_SHOT

        self._hotkeys = HotkeyManager(self)
        self._hotkeys.capture_triggered.connect(self.start_capture)
        self._hotkeys.fullscreen_triggered.connect(self.start_fullscreen)
        self._hotkeys.pin_last_triggered.connect(self.pin_last)
        self._hotkeys.scroll_triggered.connect(self.start_scroll)

        self._tray = TrayIcon()
        self._tray.capture_clicked.connect(self.start_capture)
        self._tray.fullscreen_clicked.connect(self.start_fullscreen)
        self._tray.pin_last_clicked.connect(self.pin_last)
        self._tray.scroll_clicked.connect(self.start_scroll)
        self._tray.quit_clicked.connect(self.quit)

    # ---------- 截图入口 ----------
    def _begin_capture(self, mode: str) -> None:
        try:
            grab = grab_virtual_desktop()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(None, "截图失败", f"屏幕抓取失败：{e}")
            return
        self._mode = mode
        self._overlay = RegionOverlay(grab)
        self._overlay.captured.connect(self._on_captured)
        self._overlay.cancelled.connect(self._on_cancelled)
        self._overlay.record_requested.connect(self._on_record_requested)
        self._overlay.launch()

    @pyqtSlot()
    def start_capture(self) -> None:
        self._begin_capture(MODE_SHOT)

    @pyqtSlot()
    def start_scroll(self) -> None:
        self._begin_capture(MODE_SCROLL)

    @pyqtSlot()
    def start_fullscreen(self) -> None:
        grab = grab_virtual_desktop()
        self._last_capture = grab.image
        self._open_editor(grab.image)

    @pyqtSlot()
    def pin_last(self) -> None:
        if self._last_capture is None:
            QMessageBox.information(
                None, "剪影", "还没有可贴图的截图，先按 Ctrl+Shift+A 截一张。")
            return
        self._open_pin(self._last_capture)

    # ---------- 流程回调 ----------
    def _on_captured(self, image: QImage, action: str = "edit") -> None:
        self._last_capture = image
        if action == "scroll" or self._mode == MODE_SCROLL:
            self._mode = MODE_SHOT
            rect = self._overlay.result_rect if self._overlay else QRect()
            self._start_scroll_worker(rect)
            return
        if action == "copy":
            from jianying.utils import copy_image_to_clipboard, qimage_to_pil

            copy_image_to_clipboard(qimage_to_pil(image))
            return
        if action == "save":
            import time

            from jianying import config

            config.ensure_save_dir()
            path = config.SAVE_DIR / f"shot_{time.strftime('%Y%m%d_%H%M%S')}.png"
            image.save(str(path), "PNG")
            return
        self._open_editor(image)  # action == "edit"

    def _on_cancelled(self) -> None:
        self._mode = MODE_SHOT

    @pyqtSlot(QRect)
    def _on_record_requested(self, rect: QRect) -> None:
        """屏幕录像：选区（物理像素）→ 连帧录制 → 悬浮条控制停止。"""
        if rect.isEmpty():
            QMessageBox.warning(None, "屏幕录像", "选区无效")
            return
        if self._recorder is not None and self._recorder.isRunning():
            QMessageBox.information(None, "屏幕录像", "已有录像在进行中")
            return
        from jianying.capture.recorder import RecordBar, RecordFrame, RecorderWorker

        self._recorder = RecorderWorker(rect)
        self._record_bar = RecordBar()
        self._record_bar.stop_requested.connect(self._stop_record)
        self._recorder.elapsed.connect(self._record_bar.set_elapsed)
        self._recorder.saved.connect(self._on_record_saved)
        self._recorder.failed.connect(self._on_record_failed)
        self._recorder.finished.connect(self._on_record_thread_done)
        self._recorder.start()
        self._record_bar.show()

        # 录制范围红框提示（物理 rect → 逻辑坐标）
        if self._overlay is not None:
            grab = self._overlay._grab
            tl = grab.physical_to_logical(rect.left(), rect.top())
            br = grab.physical_to_logical(rect.right(), rect.bottom())
            self._record_frame = RecordFrame(QRect(tl, br))
            self._record_frame.show()

    def _stop_record(self) -> None:
        if self._recorder is not None:
            self._recorder.stop()
        if self._record_bar is not None:
            self._record_bar.close()
            self._record_bar = None
        if self._record_frame is not None:
            self._record_frame.close()
            self._record_frame = None

    def _on_record_thread_done(self) -> None:
        """线程收尾：无论成功失败都清掉悬浮条与红框，避免留下无法关闭的窗口。"""
        if self._record_bar is not None:
            self._record_bar.close()
            self._record_bar = None
        if self._record_frame is not None:
            self._record_frame.close()
            self._record_frame = None
        self._recorder = None

    def _on_record_saved(self, path: str) -> None:
        QMessageBox.information(None, "剪影 · 录像完成",
                                f"已保存：\n{path}")

    def _on_record_failed(self, msg: str) -> None:
        QMessageBox.warning(None, "屏幕录像失败", msg)

    def _start_scroll_worker(self, rect: QRect) -> None:
        if rect.isEmpty():
            QMessageBox.warning(None, "滚动截图失败", "选区无效")
            return
        self._scroll_worker = ScrollWorker(rect)
        self._scroll_worker.stitched.connect(self._on_scroll_done)
        self._scroll_worker.failed.connect(
            lambda msg: QMessageBox.warning(None, "滚动截图失败", msg))
        self._scroll_worker.start()

    def _on_scroll_done(self, arr) -> None:
        from PIL import Image

        from jianying.utils import pil_to_qimage

        rgb = arr[:, :, ::-1]  # BGR → RGB
        img = pil_to_qimage(Image.fromarray(rgb))
        self._last_capture = img
        self._open_editor(img)

    def _open_editor(self, image: QImage) -> None:
        self._editor = EditorWindow(image)
        self._editor.pin_requested.connect(self._open_pin)
        self._editor.show()

    def _open_pin(self, image: QImage) -> None:
        win = PinWindow(image)
        self._pins.append(win)
        win.destroyed.connect(
            lambda *_: self._pins.remove(win) if win in self._pins else None)

    # ---------- 退出 ----------
    @pyqtSlot()
    def quit(self) -> None:
        self._hotkeys.stop()
        self._tray.stop()
        QApplication.quit()
