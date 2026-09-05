"""滚动截图（Windows 简版，实验功能）。

流程：框选区域 → 自动循环 [截帧 → 页面无变化则结束 → 向区域中心滚轮下滚] →
模板匹配拼接 → 回调完整长图。

拼接原理：取上一帧底部条带（不含底部边缘，避开加载动画），
在当前帧中 matchTemplate 定位 y 偏移，把当前帧多出来的部分拼上。
"""
from __future__ import annotations

from PyQt6.QtCore import QRect, QThread, pyqtSignal

from jianying import config
from jianying.capture.grabber import grab_physical_rect

try:
    import cv2
    import numpy as np
    HAS_OPENCV = True
except ImportError:  # pragma: no cover
    HAS_OPENCV = False


class ScrollWorker(QThread):
    frame_done = pyqtSignal(int, int)          # (帧序号, 已捕获帧数)
    stitched = pyqtSignal(object)              # np.ndarray BGR 长图
    failed = pyqtSignal(str)

    def __init__(self, phys_rect: QRect, parent=None):
        super().__init__(parent)
        self._rect = phys_rect
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        if not HAS_OPENCV:
            self.failed.emit("滚动截图需要 opencv-python")
            return
        try:
            self._run()
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))

    def _run(self) -> None:
        from pynput.mouse import Controller as MouseController

        mouse = MouseController()
        cx = self._rect.x() + self._rect.width() // 2
        cy = self._rect.y() + self._rect.height() // 2
        notches = config.SCROLL_WHEEL_NOTCHES
        interval = config.SCROLL_INTERVAL_MS / 1000
        max_frames = config.SCROLL_MAX_FRAMES

        frames: list[np.ndarray] = []
        same_count = 0
        for i in range(max_frames):
            if self._stop:
                break
            img = grab_physical_rect(self._rect.x(), self._rect.y(),
                                     self._rect.width(), self._rect.height())
            buf = bytes(img.constBits().asarray(img.sizeInBytes()))
            arr = np.frombuffer(buf, dtype=np.uint8).reshape(
                img.height(), img.width(), 4)
            frame = arr[:, :, :3].copy()  # BGR

            if frames:
                diff = float(np.mean(cv2.absdiff(frame, frames[-1])))
                if diff < 2.0:
                    same_count += 1
                    if same_count >= 2:
                        break
                else:
                    same_count = 0

            frames.append(frame)
            self.frame_done.emit(i + 1, max_frames)

            if i < max_frames - 1:
                mouse.position = (cx, cy)
                mouse.scroll(0, -notches)
                self.msleep(int(interval * 1000))

        if len(frames) < 2:
            self.failed.emit("可滚动内容不足（未产生新帧）")
            return
        self.stitched.emit(self._stitch(frames))

    @staticmethod
    def _stitch(frames: list[np.ndarray]) -> np.ndarray:
        h, w = frames[0].shape[:2]
        strip_h = max(40, h // 6)
        result = frames[0].copy()
        for prev, cur in zip(frames, frames[1:]):
            strip = prev[h - strip_h - 4: h - 4]      # 避开最底边
            res = cv2.matchTemplate(cur, strip, cv2.TM_CCOEFF_NORMED)
            # cv2.minMaxLoc 返回 4 个值：(minVal, maxVal, minLoc, maxLoc)
            _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(res)
            if max_val < 0.6:      # 匹配度过低：页面结构变化或到底，停止拼接
                break
            offset_y = max_loc[1]                     # strip 在 cur 中的 y
            new_from = offset_y + strip_h             # cur 中新增内容的起始 y
            if new_from < h:
                result = np.vstack([result, cur[new_from:h]])
        return result
