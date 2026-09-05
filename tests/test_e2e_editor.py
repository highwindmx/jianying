# 端到端：mss 抓屏 → RegionOverlay.confirm → EditorWindow 画布像素采样
import sys

from PyQt6.QtCore import QRectF
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)

import mss

with mss.MSS() as sct:
    raw = sct.grab(sct.monitors[0])
w, h = raw.size

from jianying.capture.grabber import ScreenGrab
from jianying.capture.region import RegionOverlay
from jianying.editor.window import EditorWindow
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QImage

img = QImage(raw.bgra, w, h, w * 4, QImage.Format.Format_ARGB32).copy()
grab = ScreenGrab(pixmap=None, image=img, virtual_rect=QRect(0, 0, w, h), dpr=1.0)

ov = RegionOverlay.__new__(RegionOverlay)
RegionOverlay.__init__(ov, grab)
ov._rect = QRectF(100, 80, 400, 300)

results = []
ov.captured.connect(lambda im, a: results.append((im, a)))
ov.confirm("edit")
assert results and results[0][1] == "edit", "confirm 未发信号"
crop = results[0][0]
assert not crop.isNull(), "crop 为 null"

# 像素一致性：裁剪 rect 左上角 (100,80)，故 crop(10,10) 对应源图 (110,90)
c_src = img.pixelColor(110, 90)
c_crop = crop.pixelColor(10, 10)
print("src(110,90)=", c_src.name(), " crop(10,10)=", c_crop.name())
assert c_src.name() == c_crop.name(), "裁剪像素错位/错色"

ed = EditorWindow(crop)
ed._refresh_canvas()
pm = ed._canvas
assert pm is not None and not pm.isNull(), "画布 pixmap 无效"
assert pm.size() == crop.size(), f"画布尺寸不符 {pm.size()} vs {crop.size()}"
# 编辑器底图 vs crop 像素
pil = ed._base
px = pil.getpixel((10, 10))
print("editor base(10,10)=", px, " crop=", c_crop.name())
assert (px[0], px[1], px[2]) == (c_crop.red(), c_crop.green(), c_crop.blue()), "编辑器底图像素不符"

print("E2E PASS: 沙箱内链路像素一致，画布正常")
