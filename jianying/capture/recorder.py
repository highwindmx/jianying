"""屏幕录像：按物理像素矩形连帧抓取 → OpenCV 写 MP4。

编码回退链 mp4v → avc1 → XVID(avi)，任一可用即开工；录制期间由
RecordBar 悬浮条显示时长并提供停止入口。
"""
from __future__ import annotations

import time

import cv2
import numpy as np
from PyQt6.QtCore import QRect, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QToolButton, QWidget)

from jianying import config
from jianying.capture.grabber import grab_physical_rect

_CODECS = (("mp4v", ".mp4"), ("avc1", ".mp4"), ("XVID", ".avi"))


class RecordFrame(QWidget):
    """录制范围红框提示：透明、置顶、鼠标穿透、加粗红边。

    仅作视觉提示；鼠标事件穿透到下层窗口，不干扰录制操作。
    （因 mss 直接抓取屏幕，红框会落进录像边缘——这是预期的范围指示。）
    """

    def __init__(self, logical_rect: QRect, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setGeometry(logical_rect)

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setPen(QPen(QColor("#FF3B30"), 3))
        p.drawRect(self.rect().adjusted(1, 1, -2, -2))
        p.end()


class RecorderWorker(QThread):
    """区域屏幕录像。elapsed(毫秒) / saved(路径) / failed(原因)。"""

    elapsed = pyqtSignal(int)
    saved = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, rect: QRect, fps: int | None = None, parent=None):
        super().__init__(parent)
        self._rect = rect
        self._fps = fps or config.RECORD_FPS
        self._stop = False

    def stop(self) -> None:
        """请求停止（线程跑完当前帧后收尾并释放编码器）。"""
        self._stop = True

    def run(self) -> None:
        x, y = self._rect.x(), self._rect.y()
        w = self._rect.width() & ~1     # 多数编码器要求偶数边长
        h = self._rect.height() & ~1
        if w < 8 or h < 8:
            self.failed.emit("录制区域过小（至少 8×8）")
            return

        config.ensure_save_dir()
        stem = time.strftime("record_%Y%m%d_%H%M%S")
        writer = None
        path = None
        for fourcc, ext in _CODECS:
            p = config.SAVE_DIR / f"{stem}{ext}"
            wr = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*fourcc),
                                 self._fps, (w, h))
            if wr.isOpened():
                writer, path = wr, p
                break
            wr.release()
        if writer is None:
            self.failed.emit("无法初始化视频编码器（mp4v/avc1/XVID 均不可用）")
            return

        try:
            interval = 1.0 / max(1, self._fps)
            t0 = time.monotonic()
            next_at = t0
            while not self._stop:
                img = grab_physical_rect(x, y, w, h)
                buf = bytes(img.constBits().asarray(img.sizeInBytes()))
                arr = np.frombuffer(buf, dtype=np.uint8).reshape(
                    img.height(), img.width(), 4)
                writer.write(arr[:, :, :3])
                self.elapsed.emit(int((time.monotonic() - t0) * 1000))
                next_at += interval
                delay = next_at - time.monotonic()
                if delay > 0:
                    self.msleep(int(delay * 1000))     # 帧率节流
                else:
                    next_at = time.monotonic()          # 追不上时重置基准
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"录制中断：{e}")
        finally:
            writer.release()

        if path is not None and path.exists() and path.stat().st_size > 0:
            self.saved.emit(str(path))
        elif path is not None:
            self.failed.emit("录制失败：输出文件为空")


class RecordBar(QWidget):
    """录制悬浮条：时长显示 + 停止按钮（可拖动）。"""

    stop_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_offset = None
        self.setWindowFlags(Qt.WindowType.Tool
                            | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint)
        self.setCursor(Qt.CursorShape.ArrowCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 5, 6, 5)
        lay.setSpacing(6)
        self._label = QLabel("● 录制中 00:00")
        self._label.setStyleSheet("color:#ff5f56;font-size:12px;")
        lay.addWidget(self._label)
        stop = QToolButton()
        stop.setText("■ 停止")
        stop.setToolTip("停止并保存录像")
        stop.setFixedHeight(26)
        stop.clicked.connect(self.stop_requested.emit)
        lay.addWidget(stop)
        self.setStyleSheet(
            "RecordBar{background:rgba(20,20,20,235);border-radius:6px;}"
            "QToolButton{background:#3a3a3a;color:white;border:none;"
            "border-radius:4px;font-size:12px;padding:0 8px;}"
            "QToolButton:hover{background:#00A8FF;}")
        self._place()

    def _place(self) -> None:
        scr = QGuiApplication.primaryScreen()
        geo = scr.availableGeometry() if scr else QRect(0, 0, 800, 600)
        self.adjustSize()
        self.move(geo.x() + (geo.width() - self.width()) // 2,
                  geo.y() + geo.height() - self.height() - 12)

    def set_elapsed(self, ms: int) -> None:
        s = ms // 1000
        self._label.setText(f"● 录制中 {s // 60:02d}:{s % 60:02d}")

    # —— 拖动 ——
    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e) -> None:
        if self._drag_offset is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, _) -> None:
        self._drag_offset = None
