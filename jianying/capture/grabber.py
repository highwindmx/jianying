"""屏幕抓取封装（mss）。

mss 输出 BGRA 字节序，在小端机器上与 QImage.Format_ARGB32 的内存布局
(0xAARRGGBB → BB GG RR AA) 完全一致，可直接构造。
"""
from __future__ import annotations

from dataclasses import dataclass

import mss
from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtGui import QImage, QPixmap


@dataclass
class ScreenGrab:
    """一次全虚拟桌面截图。

    pixmap 的 devicePixelRatio 已设置，显示尺寸 = 逻辑虚拟桌面尺寸。
    physical_size 为物理像素尺寸（与选区裁剪、滚动截图坐标系一致）。
    """
    pixmap: QPixmap          # 逻辑尺寸显示（已设 devicePixelRatio）
    image: QImage            # ARGB32 物理像素原图
    virtual_rect: QRect      # 逻辑坐标虚拟桌面 QRect（可能负 origin）
    dpr: float               # 主屏 devicePixelRatio

    @property
    def physical_size(self) -> tuple[int, int]:
        return self.image.width(), self.image.height()

    def to_physical(self, logical_point: QPoint) -> QPoint:
        """覆盖窗口逻辑坐标 → 截图物理像素坐标。"""
        tl = self.virtual_rect.topLeft()
        return QPoint(
            round((logical_point.x() - tl.x()) * self.dpr),
            round((logical_point.y() - tl.y()) * self.dpr),
        )

    def physical_to_logical(self, x: int, y: int) -> QPoint:
        tl = self.virtual_rect.topLeft()
        return QPoint(tl.x() + round(x / self.dpr), tl.y() + round(y / self.dpr))


def grab_virtual_desktop() -> ScreenGrab:
    """截取全部显示器拼接的虚拟桌面。"""
    from PyQt6.QtGui import QGuiApplication

    if QGuiApplication.instance() is None:
        # --test-grab 等无 GUI 场景：兜底创建实例
        QGuiApplication(["jianying"])
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        raise RuntimeError("无法获取屏幕信息（QGuiApplication 未就绪）")
    vrect = screen.virtualGeometry()
    dpr = float(screen.devicePixelRatio())

    with mss.MSS() as sct:
        mon = sct.monitors[0]  # 全部显示器
        raw = sct.grab(mon)

    w, h = raw.size
    img = QImage(raw.bgra, w, h, w * 4, QImage.Format.Format_ARGB32).copy()

    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)

    return ScreenGrab(
        pixmap=pm,
        image=img,
        virtual_rect=QRect(vrect),
        dpr=dpr,
    )


def grab_physical_rect(x: int, y: int, w: int, h: int) -> QImage:
    """直接按物理像素坐标截取一块区域（滚动截图用）。"""
    with mss.MSS() as sct:
        raw = sct.grab({"left": x, "top": y, "width": w, "height": h})
    iw, ih = raw.size
    return QImage(raw.bgra, iw, ih, iw * 4, QImage.Format.Format_ARGB32).copy()
