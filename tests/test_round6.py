"""第 6 轮回归：录像红框 / 缩放光标 / 取色快捷键。

覆盖：
- _handle_at 整圈边框（8 区）命中
- _CURSOR_MAP 8 向光标映射
- _copy_color 生成 #RRGGBB / rgb(r,g,b) 并写入剪贴板
- RecordFrame 透明/穿透/红边窗口属性
"""
import sys

from PyQt6.QtCore import QPointF, QRect, QRectF
from PyQt6.QtGui import QColor, QImage, QPixmap
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)

from jianying.capture.grabber import ScreenGrab
from jianying.capture.region import RegionOverlay, _CURSOR_MAP, _COLOR_HINT
from jianying.capture.recorder import RecordFrame


def _make_grab() -> ScreenGrab:
    img = QImage(4, 4, QImage.Format.Format_ARGB32)
    img.fill(0)
    img.setPixelColor(2, 2, QColor(255, 0, 0))   # 红点供取色
    return ScreenGrab(pixmap=QPixmap.fromImage(img), image=img,
                      virtual_rect=QRect(0, 0, 4, 4), dpr=1.0)


# 1) _handle_at 整圈边框（含中边）
ov = RegionOverlay(_make_grab())
ov._rect = QRectF(100, 100, 200, 150)   # 左100 上100 右300 下250
cases = {
    (100, 100): "tl", (300, 100): "tr",
    (100, 250): "bl", (300, 250): "br",
    (100, 175): "l",  (300, 175): "r",
    (200, 100): "t",  (200, 250): "b",
    (200, 175): "",   # 选区内
}
for (x, y), exp in cases.items():
    got = ov._handle_at(QPointF(x, y))
    assert got == exp, f"_handle_at({x},{y})={got!r} want {exp!r}"
print("1) _handle_at 8-zone + inside OK")

# 2) 光标映射
assert _CURSOR_MAP["tl"] == _CURSOR_MAP["br"]
assert _CURSOR_MAP["tr"] == _CURSOR_MAP["bl"]
assert _CURSOR_MAP["l"] == _CURSOR_MAP["r"]
assert _CURSOR_MAP["t"] == _CURSOR_MAP["b"]
assert _CURSOR_MAP["l"] != _CURSOR_MAP["t"]
print("2) _CURSOR_MAP mapping OK")

# 3) _copy_color 复制格式
ov._mouse = QPointF(2, 2)                  # 鼠标在红点
ov._copy_color(shift=False)
from PyQt6.QtGui import QGuiApplication
assert QGuiApplication.clipboard().text() == "#FF0000", \
    QGuiApplication.clipboard().text()
ov._copy_color(shift=True)
assert QGuiApplication.clipboard().text() == "rgb(255,0,0)", \
    QGuiApplication.clipboard().text()
assert ov._toast_text.startswith("已复制")
print("3) _copy_color HEX/RGB + toast OK")

# 4) RecordFrame 提示窗口
rf = RecordFrame(QRect(10, 10, 100, 80))
assert rf.geometry() == QRect(10, 10, 100, 80)
from PyQt6.QtCore import Qt
assert rf.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
assert rf.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
print("4) RecordFrame geometry + click-through + translucent OK")

# 5) 取色提示常驻文字非空
assert _COLOR_HINT
print("5) color hint const OK")

print("ALL ROUND-6 PASS")
