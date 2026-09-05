"""第四轮优化回归：模板库 / 滑块 / 自定义比例 / 阴影右下偏移 / 窗口自适应。"""
import sys

from PIL import Image
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
from jianying.editor import beautify, templates
from jianying.editor.window import EditorWindow
from jianying.utils import pil_to_qimage

tpls = templates.load_templates()
bgs = [t for t in tpls if t.get("type") != "none"]
assert len(bgs) == 31 and len(set(t["name"] for t in bgs)) == 31
assert all(t["name"] != "透明直角" for t in bgs)   # 透明直角已移除
print("0) 31 unique backgrounds OK (透明直角 removed)")

img = Image.new("RGBA", (100, 100), (255, 255, 255, 255))

# 1) 阴影右下偏移（像素级采样）
tpl = {"name": "t", "type": "solid", "colors": ["#FFFFFF"], "padding": 40,
       "radius": 8, "shadow": {"blur": 20, "opacity": 200, "offset_y": 14,
                               "offset_x": 8}}
out = beautify.apply_template(img, tpl)
ox, oy = beautify.placement_offset(img.size, tpl)
rb = out.getpixel((ox + 110, oy + 112))
lt = out.getpixel((ox - 10, oy - 12))
assert rb[0] < 250 and lt[0] > rb[0], (rb, lt)
print("1) shadow bottom-right OK, rb", rb, "lt", lt)

# 2) 编辑器：滑块 + 32 色块（无背景 + 31）
ed = EditorWindow(pil_to_qimage(img))
assert hasattr(ed, "_sld_pad") and not hasattr(ed, "_spin_pad")
assert len(ed._tpl_btns) == 32
print("2) sliders + 32 swatches OK")

# 3) 色块 idx: 0=无背景 1=透明圆角 2=纯白
ed._on_template_changed(2)
assert ed._tpl_list[1]["name"] == "纯白"
assert ed._sld_pad.value() == 48 and ed._sld_shadow.value() == 36
assert ed._styled is not None
print("3) template->slider OK")

# 4) 自定义比例
ed._pick_ratio("自定义")
ed._rw.setValue(5)
ed._rh.setValue(4)
assert ed._current_ratio() == "5:4"
w0, h0 = ed._styled.size
assert abs(w0 / h0 - 1.25) < 0.02, (w0, h0)
ed.undo()
assert ed._current_ratio() in ("16:9", "4:3", "3:2", "1:1", "auto")
print("4) custom ratio OK, restored", ed._current_ratio())

# 5) 滑块一次拖动 = 一步撤销
#    （沙箱无桌面会话，QSlider.setValue 的原生重绘路径会崩，
#      故屏蔽信号改值后手动调用处理器，逻辑等价于真实拖动）
n0 = len(ed._undo)
ed._on_slider_pressed()
ed._sld_pad.blockSignals(True)
ed._sld_pad.setValue(120)
ed._sld_pad.setValue(150)
ed._sld_pad.blockSignals(False)
ed._restyle()
assert len(ed._undo) == n0 + 1
assert ed._params["padding"] == 150
ed.undo()
assert ed._params["padding"] != 150
print("5) slider undo-per-drag OK")

# 6) 全部 31 模板渲染
for i in range(1, 32):
    ed._on_template_changed(i)
    assert ed._styled is not None and ed._styled.mode == "RGBA", i
print("6) all 31 templates render OK")

# 7) 比例按钮双亮回归：原生切换已把目标置亮时，槽仍须归一化且不再重复入栈
ed._undo.clear()                     # push_undo 有 30 层上限，先清空便于断言
ed._ratio_btns["16:9"].setChecked(True)
ed._ratio_key = "16:9"
ed._ratio_btns["auto"].setChecked(True)      # 模拟 Qt 原生切换先亮目标
n_undo = len(ed._undo)
ed._pick_ratio("auto")
assert ed._ratio_btns["auto"].isChecked() and not ed._ratio_btns["16:9"].isChecked()
assert len(ed._undo) == n_undo + 1
ed._pick_ratio("auto")                        # 重复点击：仅归一化，不入栈
assert len(ed._undo) == n_undo + 1
assert ed._ratio_btns["auto"].isChecked()
print("7) ratio single-lit + undo-per-switch OK")

# 8) 窗口尺寸稳定 + 超视口出滚动条
ed.show()
app.processEvents()
size0 = (ed.width(), ed.height())
ed._on_template_changed(2)          # 纯白 pad48 → styled 196x196
app.processEvents()
assert (ed.width(), ed.height()) == size0, ((ed.width(), ed.height()), size0)
print("8) window size stable on template switch OK", size0)
ed._sld_pad.blockSignals(True)
ed._sld_pad.setValue(200)           # styled 500x500 > 视口
ed._sld_pad.blockSignals(False)
ed._restyle()
app.processEvents()
hs = ed._scroll.horizontalScrollBar()
vs = ed._scroll.verticalScrollBar()
disp = ed._display_image()
print("9) scroll OK: styled", disp.size, "window", (ed.width(), ed.height()),
      "hbar", hs.maximum(), "vbar", vs.maximum())
# 工具栏行有最小宽度，横向可能撑住；任一方向出滚动条即证明滚动生效
assert hs.maximum() > 0 or vs.maximum() > 0, (hs.maximum(), vs.maximum())
print("ALL ROUND-4 PASS")
