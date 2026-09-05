"""第五轮回归：滚动截图拼接 / 屏幕录像编码 / 画布缩放坐标换算。"""
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
from jianying.capture.recorder import _CODECS
from jianying.capture.scroll import ScrollWorker
from jianying.editor.window import EditorWindow, ZOOM_MAX, ZOOM_MIN
from jianying.utils import pil_to_qimage

# 1) 滚动截图拼接：合成"同一长页面滚动窗口"的帧序列
import cv2  # noqa: E402

content = np.zeros((300, 100, 3), np.uint8)
rng = np.random.default_rng(7)
for y in range(0, 300, 12):
    cv2.line(content, (0, y), (99, y),
             tuple(int(c) for c in rng.integers(30, 255, 3)), 2)
frames = [content[i * 40: i * 40 + 120].copy() for i in range(3)]
out = ScrollWorker._stitch(frames)
assert out.shape[0] > 120, out.shape          # 必须比单帧高
assert out.shape[0] <= 300 + 40, out.shape     # 且不至于离谱膨胀
print("1) scroll stitch OK, stitched height", out.shape[0], "(single frame 120)")

# 匹配度阈值生效：结构完全不同的两帧不应产生垃圾拼接
rand_frames = [content[0:120].copy(),
               (rng.integers(0, 255, (120, 100, 3))).astype(np.uint8)]
out2 = ScrollWorker._stitch(rand_frames)
assert out2.shape[0] == 120, out2.shape
print("2) low-match guard OK, height", out2.shape[0])

# 3) 录像编码器可用性（mp4v → avc1 → XVID 回退链）
tmp = Path(tempfile.gettempdir())
picked = None
for fourcc, ext in _CODECS:
    p = tmp / f"jy_codec_test{ext}"
    wr = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*fourcc), 10, (64, 64))
    if not wr.isOpened():
        wr.release()
        continue
    for _ in range(5):
        wr.write(np.zeros((64, 64, 3), np.uint8))
    wr.release()
    if p.exists() and p.stat().st_size > 0:
        picked = (fourcc, p.stat().st_size)
        break
assert picked is not None, "无可用视频编码器"
print("3) recorder codec OK, picked", picked[0], "bytes", picked[1])

# 4) 画布缩放：控件尺寸随缩放放大
ed = EditorWindow(pil_to_qimage(Image.new("RGBA", (200, 150), (255, 255, 255, 255))))
ed.show()
app.processEvents()
disp = ed._display_image()
assert (ed._canvas_widget.width(), ed._canvas_widget.height()) == disp.size
ed._set_zoom(2.0)
app.processEvents()
assert (ed._canvas_widget.width(), ed._canvas_widget.height()) == (
    disp.width * 2, disp.height * 2), ed._canvas_widget.size()
print("4) zoom widget size OK 200x150 ->", ed._canvas_widget.width(),
      "x", ed._canvas_widget.height())

# 5) 坐标换算：控件坐标 /zoom = 画布坐标（画笔落点校验）
cv = ed._canvas_widget
assert cv._c(QPointF(200.0, 100.0)) == QPointF(100.0, 50.0)
ed._set_zoom(1.0)
app.processEvents()
ed._set_zoom(2.0)
app.processEvents()

from PyQt6.QtTest import QTest  # noqa: E402

old_px = ed._base.getpixel((125, 62))
QTest.mousePress(cv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                 QPoint(200, 100))
QTest.mouseMove(cv, QPoint(300, 150))
QTest.mouseRelease(cv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                   QPoint(300, 150))
app.processEvents()
new_px = ed._base.getpixel((125, 62))
assert new_px != old_px, (old_px, new_px)   # (125,62) 在 (100,50)->(150,75) 线上
assert new_px[0] > 200 and new_px[1] < 120, new_px   # 默认红色 #E8483F
print("5) zoom coord mapping OK, pixel", new_px, "at canvas (125,62)")

# 6) 缩放边界与复位
ed._set_zoom(100.0)
assert ed._zoom == ZOOM_MAX
ed._set_zoom(0.001)
assert ed._zoom == ZOOM_MIN
ed._set_zoom(1.0)
assert ed._zoom == 1.0 and ed._canvas_widget.width() == disp.width
print("6) zoom clamp + reset OK")
print("ALL ROUND-5 PASS")
