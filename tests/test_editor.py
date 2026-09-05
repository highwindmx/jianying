"""编辑器构造与操作冒烟（offscreen）。

运行：QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe tests/test_editor.py
"""
import sys

from PIL import Image
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)

from jianying.editor import beautify
from jianying.editor.window import EditorWindow
from jianying.utils import pil_to_qimage

pil = Image.new("RGBA", (400, 300), (220, 230, 240, 255))
ed = EditorWindow(pil_to_qimage(pil))
print("1) construct OK", ed._canvas.size())

from PyQt6.QtCore import QPointF

# 矩形 / 箭头 / 画笔 / 马赛克 / 椭圆
ed._tool = "rect"
ed.commit_shape(QPointF(20, 20), QPointF(120, 90))
ed._tool = "arrow"
ed.commit_shape(QPointF(150, 40), QPointF(250, 80))
ed._tool = "pen"
ed._painted_paths = [QPointF(10, 200), QPointF(50, 210), QPointF(90, 205)]
ed.commit_shape(QPointF(10, 200), QPointF(90, 205))
ed._tool = "mosaic"
ed.commit_shape(QPointF(280, 180), QPointF(360, 260))
ed._tool = "ellipse"
ed.commit_shape(QPointF(140, 120), QPointF(220, 170))
print("2) shapes OK, undo depth =", len(ed._undo))

ed.undo()
ed.undo()
print("3) undo OK, base =", ed._base.size)

# 美化（绕开对话框直接应用模板）
from jianying.editor import templates

for t in templates.load_templates():
    out = beautify.apply_template(ed._base, t)
    assert out.mode == "RGBA"
print("4) beautify x all templates OK")

# 复制到剪贴板
ed._copy()
print("5) clipboard OK")
print("EDITOR SMOKE PASS")
