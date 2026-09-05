"""复现：confirm → crop → qimage_to_pil 全链路，定位 null QImage。"""
import sys

import mss
from PyQt6.QtCore import QRect, QRectF
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)

with mss.MSS() as sct:
    raw = sct.grab(sct.monitors[0])
w, h = raw.size
src = QImage(raw.bgra, w, h, w * 4, QImage.Format.Format_ARGB32).copy()
pm = QPixmap.fromImage(src)
print("grab image:", src.isNull(), src.size())

from jianying.capture.grabber import ScreenGrab
from jianying.capture.region import RegionOverlay
from jianying.utils import qimage_to_pil

grab = ScreenGrab(pixmap=pm, image=src, virtual_rect=QRect(0, 0, w, h), dpr=1.0)
ov = RegionOverlay(grab)

results = []


def on_captured(img, action="edit"):
    results.append(img)
    print("captured:", img.isNull(), img.size(),
          "format:", img.format(), "action:", action)


ov.captured.connect(on_captured)

# 模拟用户框选 + 确认
ov._rect = QRectF(100, 100, 400, 300)
ov.confirm()
crop = results[0]
assert not crop.isNull(), "crop is null!"
pil = qimage_to_pil(crop)
print("crop->pil:", pil.size, "OK")

# 边界场景：贴边/负坐标选区（曾经导致 null crop 的场景）
for rect in [QRectF(0, 0, 100, 100), QRectF(w - 50, h - 50, 50, 50),
             QRectF(-1920 + 10, 10, 300, 200)]:
    ov._rect = rect
    ov.confirm()
for i, img in enumerate(results):
    assert not img.isNull(), f"captured[{i}] is null!"
print("edge cases done, total captured:", len(results))
print("REPRO PASS - 链路无 null")
