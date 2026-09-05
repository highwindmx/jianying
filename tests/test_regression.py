"""回归：QImage 缓冲修复（constBits.asarray）+ 窗口猜测管线。

运行：QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe tests/test_regression.py
"""
import sys

import mss
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication, QWidget

app = QApplication(sys.argv)  # QWidget 需要 QApplication（QGuiApplication 会崩）

# 1) QImage → PIL → QImage 往返
from jianying.utils import pil_to_qimage, qimage_to_pil  # noqa: E402

with mss.MSS() as sct:
    raw = sct.grab(sct.monitors[0])
w, h = raw.size
src = QImage(raw.bgra, w, h, w * 4, QImage.Format.Format_ARGB32).copy()

pil = qimage_to_pil(src)
back = pil_to_qimage(pil)
assert pil.size == (w, h), f"size mismatch {pil.size}"
assert back.size() == src.size(), "qimage size mismatch"
assert not back.isNull()
c1, c2 = src.pixelColor(100, 100), back.pixelColor(100, 100)
assert (c1.red(), c1.green(), c1.blue()) == (c2.red(), c2.green(), c2.blue()), (
    f"color mismatch {c1.name()} vs {c2.name()}")
print(f"1) roundtrip OK {w}x{h}")

# 2) RegionOverlay 窗口猜测轮廓提取（数据管线，不 show 窗口）
from jianying.capture.grabber import ScreenGrab  # noqa: E402
from jianying.capture.region import RegionOverlay  # noqa: E402

grab = ScreenGrab(pixmap=None, image=src, virtual_rect=QRect(0, 0, w, h), dpr=1.0)
ov = RegionOverlay.__new__(RegionOverlay)
QWidget.__init__(ov)
ov._grab = grab
ov._guess_enabled = True
ov._build_guess_rects()
print(f"2) guess rects: {len(ov._guess_rects)} | top3: {ov._guess_rects[:3]}")
assert len(ov._guess_rects) > 0, "no rects detected"

# 3) 逻辑↔物理坐标换算
p = grab.to_physical(QRect(0, 0, 10, 10).topLeft())
q = grab.physical_to_logical(100, 200)
assert p == QRect(0, 0, 10, 10).topLeft() and q == QRect(100, 200, 0, 0).topLeft()
print("3) coordinate mapping OK (dpr=1.0)")
print("ALL REGRESSION PASS")
