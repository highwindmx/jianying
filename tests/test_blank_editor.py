"""复现：截图内容未在编辑器呈现。

链路：grab_virtual_desktop → RegionOverlay 确认('edit') → EditorWindow
→ 渲染 _Canvas 到 QImage，统计有效像素，判断画布是否空白。
"""
import sys

from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)

from jianying.capture.grabber import grab_virtual_desktop
from jianying.capture.region import RegionOverlay
from jianying.editor.window import EditorWindow
from jianying.utils import qimage_to_pil

grab = grab_virtual_desktop()
print("grab:", grab.image.width(), "x", grab.image.height(), "dpr=", grab.dpr)

received = []
ov = RegionOverlay(grab)
ov.captured.connect(lambda img, action: received.append((img, action)))

# 模拟用户在虚拟桌面中部框选 800x500
ov._rect = QRectF(200, 150, 800, 500)
ov.confirm("edit")
assert received, "confirm 未发出 captured 信号"
img, action = received[0]
print("captured:", img.width(), "x", img.height(), "action=", action, "null=", img.isNull())
assert not img.isNull()

# 进入编辑器
ed = EditorWindow(img)
pm = ed._canvas
print("editor _base:", ed._base.size, "mode=", ed._base.mode)
print("canvas pixmap:", pm.width(), "x", pm.height(), "null=", pm.isNull())

# 渲染画布组件到 QImage 检查是否空白
assert ed._canvas_widget._pm is not None
cw = ed._canvas_widget
render_w = min(cw._pm.width(), 1200)
render_h = min(cw._pm.height(), 800)
target = QImage(render_w, render_h, QImage.Format.Format_ARGB32)
target.fill(0xFFFFFFFF)
cw.resize(cw._pm.size())
cw.render(target)
pil = qimage_to_pil(target)
colors = pil.convert("RGB").getcolors(maxcolors=100000)
n_colors = len(colors) if colors else 100000
top = sorted(colors or [], reverse=True)[:3]
print(f"render {render_w}x{render_h}: distinct colors = {n_colors}, top3 = {top}")
if n_colors <= 2:
    print("!!! CANVAS BLANK — 复现成功")
    sys.exit(1)
print("CANVAS HAS CONTENT — 沙箱未复现空白")
