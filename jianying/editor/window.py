"""截图编辑器：标注（画笔/箭头/矩形/椭圆/文字/马赛克）+ 右侧美化栏 + 导出。

坐标系约定：编辑器内部状态一律使用"画布坐标"= 当前显示图（美化后 styled
或原图 base）的未缩放像素坐标；鼠标事件进来的控件坐标需除以 _zoom 换算。
标注提交到 _base 时再减去美化偏移 _offset。
"""
from __future__ import annotations

import copy

from PIL import Image, ImageDraw
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (QColor, QFont, QFontDatabase, QFontMetrics, QImage,
                         QPainter, QPen, QPixmap)
from PyQt6.QtWidgets import (
    QApplication,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from jianying import config
from jianying.editor import beautify, templates
from jianying.ocr import MineruWorker
from jianying.utils import pil_to_qimage, pil_to_qpixmap, qimage_to_pil

TOOLS = ["pen", "arrow", "rect", "ellipse", "text", "mosaic", "poly", "rpoly"]
TOOL_LABELS = {"pen": "✏ 画笔", "arrow": "➹ 箭头", "rect": "▭ 矩形",
               "ellipse": "◯ 椭圆", "text": "T 文字", "mosaic": "▦ 马赛克",
               "poly": "⬠ 多边形", "rpoly": "⬡ 正多边形"}
# 工具按钮在网格工具栏中的位置 (row, col)：
# 椭圆在画笔下、箭头下拉在箭头下、自由多边形在矩形下、
# 正多边形在矩形右侧（边数选择在其下）、马赛克在文字下、
# 放大/缩小在文字与马赛克右侧（上下分布）、重做在撤销下
TOOL_POS = {"pen": (0, 3), "arrow": (0, 4), "rect": (0, 5), "rpoly": (0, 6),
            "text": (0, 7), "ellipse": (1, 3), "poly": (1, 5),
            "mosaic": (1, 7)}
ZOOM_MIN, ZOOM_MAX, ZOOM_STEP = 0.25, 8.0, 1.25
ARROW_HEADS = [("尖头", "sharp"), ("圆头", "round"), ("无头", "none")]
RATIOS = ["auto", "16:9", "4:3", "3:2", "1:1"]

STATE_IDLE, STATE_DRAW = 0, 1


class EditorWindow(QWidget):
    """编辑器窗口。pin_requested(QImage) → 贴图。"""

    pin_requested = pyqtSignal(QImage)

    def __init__(self, image: QImage, parent=None):
        super().__init__(parent)
        self.setWindowTitle("剪影 · 编辑")
        from jianying.icon import qt_icon
        self.setWindowIcon(qt_icon())
        base = qimage_to_pil(image)
        if base.getextrema()[3][1] == 0:  # 全透明异常数据 → 垫白底
            white = Image.new("RGBA", base.size, (255, 255, 255, 255))
            base = Image.alpha_composite(white, base)
        self._base = base                        # PIL RGBA 标注底图
        self._styled: Image.Image | None = None  # 美化后显示/导出图
        self._params: dict | None = None         # 当前美化参数
        self._offset = (0, 0)                    # base 在 styled 中的偏移
        self._undo: list = []                    # [(base_copy, params_snapshot)]
        self._tool = "pen"
        self._arrow_head = "sharp"
        self._color = QColor("#E8483F")
        self._width = 4
        self._state = STATE_IDLE
        self._start = QPointF()
        self._end = QPointF()
        self._painted_paths: list = []
        self._mosaic_cache: dict = {}
        self._poly_points: list = []             # 多边形顶点（画布坐标）
        self._poly_sides = 6                     # 正多边形边数
        self._zoom = 1.0                         # 画布显示缩放（1.0 = 原尺寸）
        self._ratio_key = "auto"                 # 当前比例按钮（避免按钮状态反推）
        self._redo: list = []                    # 重做栈 [(base_copy, params)]

        self._tpl_list = [t for t in templates.load_templates()
                          if t.get("type") != "none"]  # "无背景"由下拉框第 0 项承担
        self._build_ui()
        self._restyle()
        scr = self.screen().availableGeometry()
        disp = self._display_image()
        self.resize(min(scr.width() - 40, disp.width + 40),
                    min(scr.height() - 60, disp.height + 130))

    # ---------------- UI ----------------
    def _build_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        # ---- 左：工具栏 + 画布 ----
        left = QVBoxLayout()
        left.setSpacing(6)

        grid = QGridLayout()
        grid.setSpacing(4)

        def tb(text: str, tip: str, cb, checkable=False) -> QToolButton:
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setCheckable(checkable)
            b.clicked.connect(cb)
            return b

        # 第 0 列：复制 / 保存（上下）
        grid.addWidget(tb("⧉ 复制", "复制到剪贴板", self._copy), 0, 0)
        grid.addWidget(tb("💾 保存", "保存到文件", self._save), 1, 0)
        # 第 1 列：贴图 / OCR（上下）
        grid.addWidget(tb("📌 贴图", "固定到屏幕", self._pin), 0, 1)
        grid.addWidget(tb("🔍 OCR", "MinerU 文字识别", self._run_ocr), 1, 1)
        # 第 2 列：颜色 / 粗细（上下）
        self._btn_color = tb("●", "标注颜色", self._pick_color)
        self._update_color_btn()
        grid.addWidget(self._btn_color, 0, 2)
        self._spin = QSpinBox()
        self._spin.setRange(1, 40)
        self._spin.setValue(self._width)
        self._spin.valueChanged.connect(lambda v: setattr(self, "_width", v))
        grid.addWidget(self._spin, 1, 2)

        # 工具区：一行工具按钮，第二行放箭头头型（arrow 下方）与多边形（rect 下方）
        self._tool_buttons: dict[str, QToolButton] = {}
        for t in TOOLS:
            b = QToolButton()
            b.setText(TOOL_LABELS[t])
            b.setToolTip(TOOL_LABELS[t])
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, tool=t: self._pick_tool(tool))
            b.setStyleSheet("QToolButton:checked {background:#00A8FF;color:white;}")
            self._tool_buttons[t] = b
            r, c = TOOL_POS[t]
            grid.addWidget(b, r, c)

        self._arrow_cb = QComboBox()
        for label, _key in ARROW_HEADS:
            self._arrow_cb.addItem(label)
        self._arrow_cb.currentIndexChanged.connect(
            lambda i: setattr(self, "_arrow_head", ARROW_HEADS[i][1]))
        grid.addWidget(self._arrow_cb, 1, 4)

        # 正多边形边数选择（⬡ 正下方）
        self._sides_spin = QSpinBox()
        self._sides_spin.setRange(3, 16)
        self._sides_spin.setValue(self._poly_sides)
        self._sides_spin.setToolTip("正多边形边数 (3-16)")
        self._sides_spin.valueChanged.connect(
            lambda v: setattr(self, "_poly_sides", v))
        grid.addWidget(self._sides_spin, 1, 6)

        # 视图缩放（文字/马赛克右侧，上下分布）
        self._btn_zoom_in = tb("＋ 放大", "放大视图 (Ctrl+=)",
                               lambda: self._zoom_by(ZOOM_STEP))
        self._btn_zoom_out = tb("－ 缩小", "缩小视图 (Ctrl+-)",
                                lambda: self._zoom_by(1 / ZOOM_STEP))
        grid.addWidget(self._btn_zoom_in, 0, 8)
        grid.addWidget(self._btn_zoom_out, 1, 8)

        # 撤销 / 重做（上下）
        grid.addWidget(tb("↩ 撤销", "撤销上一步 (Ctrl+Z)", self.undo), 0, 9)
        grid.addWidget(tb("↷ 重做", "重做 (Ctrl+Y)", self.redo), 1, 9)
        grid.setColumnStretch(10, 1)  # 右侧留白，按钮整体靠左
        left.addLayout(grid)

        self._canvas_widget = _Canvas(self)
        self._scroll = QScrollArea()
        self._scroll.setWidget(self._canvas_widget)
        self._scroll.setWidgetResizable(False)
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter
                                  | Qt.AlignmentFlag.AlignVCenter)
        self._scroll.setStyleSheet(
            "QScrollArea{border:none;background:#2b2b2b;}"
            # 显式样式避免深底上滚动条不可见
            "QScrollBar:vertical{background:#2f2f2f;width:12px;margin:0;}"
            "QScrollBar::handle:vertical{background:#6b7280;min-height:30px;"
            "border-radius:6px;}"
            "QScrollBar::handle:vertical:hover{background:#00A8FF;}"
            "QScrollBar:horizontal{background:#2f2f2f;height:12px;margin:0;}"
            "QScrollBar::handle:horizontal{background:#6b7280;min-width:30px;"
            "border-radius:6px;}"
            "QScrollBar::handle:horizontal:hover{background:#00A8FF;}"
            "QScrollBar::add-line,QScrollBar::sub-line{height:0;width:0;}"
            "QScrollBar::add-page,QScrollBar::sub-page{background:transparent;}")
        left.addWidget(self._scroll, 1)
        self._pick_tool("pen")  # 默认工具；必须在 _canvas_widget 创建后调用
        self._update_zoom_tips()

        outer.addLayout(left, 1)

        # ---- 右：美化栏 ----
        self._sidebar = self._build_sidebar()
        outer.addWidget(self._sidebar)

    def _build_sidebar(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("sidebar")
        panel.setMaximumWidth(324)
        # 样式只作用于 #sidebar 本体与指定控件，避免 QWidget{} 通配把
        # QSpinBox 内部行编辑也描边/加背景导致上下按钮点不到
        panel.setStyleSheet(
            "QWidget#sidebar{background:#f4f6f8;border:1px solid #dde3e8;"
            "border-radius:6px;}"
            "QWidget#sidebar QLabel{border:none;background:transparent;}"
            "QWidget#sidebar QSpinBox{background:white;border:1px solid #ccd3da;"
            "border-radius:4px;padding:2px 22px 2px 6px;}"
            "QWidget#sidebar QSpinBox::up-button,QSpinBox::down-button"
            "{width:18px;border:none;background:#e3e8ee;}"
            "QWidget#sidebar QSpinBox::up-button:hover,QSpinBox::down-button:hover"
            "{background:#00A8FF;}"
            "QWidget#sidebar QComboBox{background:white;border:1px solid #ccd3da;"
            "border-radius:4px;padding:2px 6px;}"
            "QWidget#sidebar QSlider::groove:horizontal{height:4px;background:#d3dae1;"
            "border-radius:2px;}"
            "QWidget#sidebar QSlider::handle:horizontal{width:14px;margin:-6px 0;"
            "border-radius:7px;background:#00A8FF;}"
            "QWidget#sidebar QSlider::sub-page:horizontal{background:#9fd8ff;"
            "border-radius:2px;}")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)

        title = QLabel("✨ 美化背景")
        title.setStyleSheet("font-weight:bold;font-size:13px;")
        lay.addWidget(title)

        lay.addWidget(QLabel("背景模板（点按选择）"))
        self._tpl_index = 0
        self._tpl_btns: list[QToolButton] = []
        sw = QScrollArea()
        sw.setWidgetResizable(True)
        sw.setFrameShape(QFrame.Shape.NoFrame)
        sw.setMaximumHeight(300)   # 33 块 ≈ 9 行，超高内部滚动
        sw.setStyleSheet("QScrollArea{background:transparent;}")
        sw_grid = QWidget()
        sw_lay = QGridLayout(sw_grid)
        sw_lay.setContentsMargins(0, 0, 0, 0)
        sw_lay.setSpacing(4)
        specs = [("无背景", None)] + [(t["name"], t) for t in self._tpl_list]
        for i, (name, tpl) in enumerate(specs):
            b = QToolButton()
            b.setCheckable(True)
            b.setFixedSize(70, 30)
            b.setToolTip(name)
            b.setStyleSheet(_swatch_qss(tpl))
            b.clicked.connect(lambda _=False, idx=i: self._on_template_changed(idx))
            self._tpl_btns.append(b)
            sw_lay.addWidget(b, i // 4, i % 4)   # 4 个一行
        self._tpl_btns[0].setChecked(True)  # 默认无背景
        sw.setWidget(sw_grid)
        lay.addWidget(sw)

        lay.addWidget(QLabel("画面比例"))
        self._ratio_btns: dict[str, QToolButton] = {}
        rb = QWidget()
        rb_lay = QHBoxLayout(rb)
        rb_lay.setContentsMargins(0, 0, 0, 0)
        rb_lay.setSpacing(4)
        for r in RATIOS + ["自定义"]:
            b = QToolButton()
            b.setText(r)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, key=r: self._pick_ratio(key))
            self._ratio_btns[r] = b
            rb_lay.addWidget(b)
        self._ratio_btns["auto"].setChecked(True)  # 默认 auto
        lay.addWidget(rb)

        # 自定义比例行（选"自定义"时显示）：宽 : 高
        self._custom_ratio_row = QWidget()
        cr_lay = QHBoxLayout(self._custom_ratio_row)
        cr_lay.setContentsMargins(0, 0, 0, 0)
        cr_lay.setSpacing(4)
        self._rw = QSpinBox()
        self._rw.setRange(1, 64)
        self._rw.setValue(16)
        self._rh = QSpinBox()
        self._rh.setRange(1, 64)
        self._rh.setValue(10)
        for s in (self._rw, self._rh):
            s.valueChanged.connect(self._on_param_changed)
            cr_lay.addWidget(s)
        cr_lay.addWidget(QLabel("(宽:高)"))
        cr_lay.addStretch(1)
        self._custom_ratio_row.setVisible(False)
        lay.addWidget(self._custom_ratio_row)

        def slider(label: str, lo: int, hi: int, default: int) -> QSlider:
            head = QHBoxLayout()
            head.addWidget(QLabel(label))
            head.addStretch(1)
            val = QLabel(str(default))
            val.setStyleSheet("color:#556;")
            head.addWidget(val)
            lay.addLayout(head)
            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(lo, hi)
            s.setValue(default)
            s.valueChanged.connect(lambda v: val.setText(str(v)))
            s.sliderPressed.connect(self._on_slider_pressed)
            s.valueChanged.connect(lambda _: self._restyle())
            lay.addWidget(s)
            return s

        self._sld_pad = slider("留白 padding (px)", 0, 300, 48)
        self._sld_radius = slider("圆角 radius (px)", 0, 120, 16)
        self._sld_shadow = slider("阴影模糊 (0=无阴影)", 0, 80, 40)
        self._sld_shadow_op = slider("阴影浓度", 0, 255, 110)
        lay.addStretch(1)
        tip = QLabel("选模板后带入默认值，可再拖滑块微调；\n标注始终画在截图本体上。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#667;font-size:11px;")
        lay.addWidget(tip)
        return panel

    # ---------------- 美化参数 ----------------
    def _on_template_changed(self, idx: int) -> None:
        """点按模板色块：选中态 + 带入模板默认值（保持当前比例）。"""
        if idx != self._tpl_index:
            self.push_undo()   # 参数类操作同样一步一撤
        self._tpl_index = idx
        for i, b in enumerate(self._tpl_btns):
            b.setChecked(i == idx)
        if idx <= 0:
            self._restyle()
            return
        tpl = self._tpl_list[idx - 1]
        shadow = tpl.get("shadow") or {}
        for s, v in ((self._sld_pad, tpl.get("padding", 48)),
                     (self._sld_radius, tpl.get("radius", 16)),
                     (self._sld_shadow, shadow.get("blur", 0)),   # 无 shadow 键 = 无阴影
                     (self._sld_shadow_op, shadow.get("opacity", 110))):
            s.blockSignals(True)
            s.setValue(int(v))
            s.blockSignals(False)
        self._restyle()

    def _on_slider_pressed(self) -> None:
        """滑块开始拖动：入撤销栈一次（拖动过程只重渲染不入栈）。"""
        self.push_undo()

    def _on_param_changed(self) -> None:
        """右栏数值微调（自定义比例/边数等）：入撤销栈后重渲染。"""
        self.push_undo()
        self._restyle()

    def _pick_ratio(self, key: str) -> None:
        # QToolButton 点击会先"原生切换"自身选中态再触发本槽，
        # 不能用按钮状态推断旧比例（点击 auto 时 auto 已亮、且扫描序居首，
        # 会误判"未变化"提前返回，导致新旧两个按钮同时亮）——用 _ratio_key 判定。
        changed = key != self._ratio_key
        if changed:
            self.push_undo()       # 比例切换一步一撤
            self._ratio_key = key
        for k, b in self._ratio_btns.items():
            b.setChecked(k == key)   # 无论是否变化都强制归一化选中态
        self._custom_ratio_row.setVisible(key == "自定义")
        if changed:
            self._restyle()

    def _current_ratio(self) -> str:
        if self._ratio_btns.get("自定义", None) and \
                self._ratio_btns["自定义"].isChecked():
            return f"{self._rw.value()}:{self._rh.value()}"
        for k, b in self._ratio_btns.items():
            if k != "自定义" and b.isChecked():
                return k
        return "auto"

    def _current_params(self) -> dict | None:
        idx = self._tpl_index
        if idx <= 0:
            return None
        tpl = copy.deepcopy(self._tpl_list[idx - 1])
        tpl["padding"] = self._sld_pad.value()
        tpl["radius"] = self._sld_radius.value()
        blur = self._sld_shadow.value()
        if blur <= 0:
            tpl.pop("shadow", None)
        else:
            old = tpl.get("shadow") or {}
            tpl["shadow"] = {"blur": blur,
                             "opacity": self._sld_shadow_op.value(),
                             "offset_y": old.get("offset_y", 14),
                             "offset_x": old.get("offset_x", 8)}
        tpl["ratio"] = self._current_ratio()
        return tpl

    def _restyle(self) -> None:
        self._mosaic_cache.clear()
        self._params = self._current_params()
        if self._params is None:
            self._styled = None
            self._offset = (0, 0)
        else:
            self._styled = beautify.apply_template(self._base, self._params)
            self._offset = beautify.placement_offset(self._base.size, self._params)
        self._refresh_canvas()

    # ---------------- 撤销 ----------------
    def _display_image(self) -> Image.Image:
        return self._styled if self._styled is not None else self._base

    def _refresh_canvas(self) -> None:
        self._mosaic_cache.clear()
        self._canvas = pil_to_qpixmap(self._display_image())
        self._canvas_widget.set_pixmap(self._canvas)
        self._canvas_widget.update()

    # ---------------- 视图缩放 ----------------
    def _zoom_by(self, factor: float) -> None:
        self._set_zoom(self._zoom * factor)

    def _set_zoom(self, z: float) -> None:
        """设置缩放比并保持视口中心不动（放大后不"跳走"）。"""
        z = min(ZOOM_MAX, max(ZOOM_MIN, z))
        if abs(z - self._zoom) < 1e-6:
            return
        vp = self._scroll.viewport()
        hbar, vbar = self._scroll.horizontalScrollBar(), self._scroll.verticalScrollBar()
        cx = (hbar.value() + vp.width() / 2) / self._zoom
        cy = (vbar.value() + vp.height() / 2) / self._zoom

        self._close_text_overlays()   # 缩放后 inline 文本位置失效
        self._zoom = z
        self._refresh_canvas()
        QApplication.processEvents()   # 让滚动条量程按新尺寸刷新
        hbar.setValue(int(cx * z - vp.width() / 2))
        vbar.setValue(int(cy * z - vp.height() / 2))
        self._update_zoom_tips()

    def _update_zoom_tips(self) -> None:
        pct = int(self._zoom * 100)
        self._btn_zoom_in.setToolTip(f"放大视图 (Ctrl+=)　当前 {pct}%")
        self._btn_zoom_out.setToolTip(f"缩小视图 (Ctrl+-)　当前 {pct}%")

    def push_undo(self) -> None:
        self._undo.append((self._base.copy(), copy.deepcopy(self._params)))
        if len(self._undo) > 30:
            self._undo.pop(0)
        self._redo.clear()  # 新操作后重做链失效

    def undo(self) -> None:
        if not self._undo:
            return
        self._redo.append((self._base.copy(), copy.deepcopy(self._params)))
        base, params = self._undo.pop()
        self._base = base
        self._restore_params(params)
        self._restyle()

    def redo(self) -> None:
        if not self._redo:
            return
        self._undo.append((self._base.copy(), copy.deepcopy(self._params)))
        base, params = self._redo.pop()
        self._base = base
        self._restore_params(params)
        self._restyle()

    def _restore_params(self, params: dict | None) -> None:
        """恢复参数快照到控件（屏蔽信号），restyle 时直接采用快照。"""
        self._params = params
        idx = 0
        if params is not None:
            idx = next((i + 1 for i, t in enumerate(self._tpl_list)
                        if t["name"] == params.get("name", "")), 0)
        self._tpl_index = idx
        for i, b in enumerate(self._tpl_btns):
            b.setChecked(i == idx)
        # 比例：预设名直接选按钮；否则按 "W:H" 解析进自定义行
        ratio = (params or {}).get("ratio", "auto")
        is_custom = ratio not in self._ratio_btns
        if is_custom and params is not None and ":" in str(ratio):
            try:
                a, b_ = str(ratio).split(":")
                self._rw.setValue(int(a))
                self._rh.setValue(int(b_))
            except ValueError:
                ratio = "auto"
                is_custom = False
        elif is_custom:
            ratio = "auto"
            is_custom = False
        for k, b in self._ratio_btns.items():
            b.setChecked(k == ratio)
        self._ratio_key = "自定义" if is_custom else ratio
        self._custom_ratio_row.setVisible(is_custom)
        widgets = (self._sld_pad, self._sld_radius,
                   self._sld_shadow, self._sld_shadow_op, self._rw, self._rh)
        for w in widgets:
            w.blockSignals(True)
        try:
            if params is None:
                self._sld_pad.setValue(0)
                self._sld_radius.setValue(0)
                self._sld_shadow.setValue(0)
            else:
                self._sld_pad.setValue(int(params.get("padding", 48)))
                self._sld_radius.setValue(int(params.get("radius", 16)))
                sh = params.get("shadow") or {}
                self._sld_shadow.setValue(int(sh.get("blur", 0)))
                self._sld_shadow_op.setValue(int(sh.get("opacity", 110)))
        finally:
            for w in widgets:
                w.blockSignals(False)

    # ---------------- 工具 ----------------
    def _pick_tool(self, tool: str) -> None:
        self._tool = tool
        self._poly_points = []  # 切换工具即取消未完成的多边形
        for k, b in self._tool_buttons.items():
            b.setChecked(k == tool)
        cursor = Qt.CursorShape.CrossCursor
        if tool == "text":
            cursor = Qt.CursorShape.IBeamCursor
        elif tool == "pen":
            cursor = Qt.CursorShape.PointingHandCursor
        self._canvas_widget.setCursor(cursor)

    def _pick_color(self) -> None:
        c = QColorDialog.getColor(self._color, self, "选择标注颜色")
        if c.isValid():
            self._color = c
            self._update_color_btn()

    def _update_color_btn(self) -> None:
        self._btn_color.setStyleSheet(
            f"QToolButton {{color:{self._color.name()};font-size:18px;}}")

    def keyPressEvent(self, e) -> None:
        ctrl = e.modifiers() & Qt.KeyboardModifier.ControlModifier
        if ctrl and e.key() in (Qt.Key.Key_Equal, Qt.Key.Key_Plus):
            self._zoom_by(ZOOM_STEP)
            return
        if ctrl and e.key() == Qt.Key.Key_Minus:
            self._zoom_by(1 / ZOOM_STEP)
            return
        if ctrl and e.key() == Qt.Key.Key_0:
            self._set_zoom(1.0)      # 复位 100%
            return
        if ctrl and e.key() in (Qt.Key.Key_Z, Qt.Key.Key_Y):
            if e.isAutoRepeat():   # 按住不放不连发，严格一步一撤
                return
            self.undo() if e.key() == Qt.Key.Key_Z else self.redo()
            return
        super().keyPressEvent(e)

    # ---------------- 标注提交 ----------------
    def commit_shape(self, start: QPointF, end: QPointF) -> None:
        """把一次绘制写入底图。start/end 为画布（styled）坐标，减偏移映射回 base。"""
        if self._tool == "text":
            self._begin_text(end)
            return
        self.push_undo()
        img = self._base
        d = ImageDraw.Draw(img)
        color = (self._color.red(), self._color.green(), self._color.blue(), 255)
        w = self._width
        ox, oy = self._offset
        x1, y1 = start.x() - ox, start.y() - oy
        x2, y2 = end.x() - ox, end.y() - oy

        tool = self._tool
        if tool == "pen":
            pts = [(p.x() - ox, p.y() - oy) for p in self._painted_paths]
            if len(pts) >= 2:
                d.line(pts, fill=color, width=w, joint="curve")
            self._painted_paths = []
        elif tool == "arrow":
            _draw_arrow(d, (x1, y1), (x2, y2), color, w, self._arrow_head)
        elif tool == "rect":
            d.rectangle([x1, y1, x2, y2], outline=color, width=w)
        elif tool == "rpoly":
            pts = _rpoly_points(start, end, self._poly_sides)
            pp = [(p.x() - ox, p.y() - oy) for p in pts]
            d.line(pp + [pp[0]], fill=color, width=w, joint="curve")
        elif tool == "ellipse":
            d.ellipse([x1, y1, x2, y2], outline=color, width=w)
        elif tool == "mosaic":
            box = (int(min(x1, x2)), int(min(y1, y2)),
                   int(max(x1, x2)), int(max(y1, y2)))
            if box[2] - box[0] > 2 and box[3] - box[1] > 2:
                _pixelate(img, box, config.MOSAIC_BLOCK)
        self._restyle()

    def commit_poly(self) -> None:
        """提交多边形（≥3 个顶点），闭合描边；Esc/切工具取消。"""
        pts = self._poly_points
        self._poly_points = []
        self._canvas_widget.update()
        if len(pts) < 3:
            return
        self.push_undo()
        d = ImageDraw.Draw(self._base)
        color = (self._color.red(), self._color.green(), self._color.blue(), 255)
        ox, oy = self._offset
        pp = [(p.x() - ox, p.y() - oy) for p in pts]
        d.line(pp + [pp[0]], fill=color, width=self._width, joint="curve")
        self._restyle()

    # ---------------- 马赛克实时预览 ----------------
    def mosaic_preview(self, box: QRectF):
        """返回 (QPixmap, 左上角画布坐标) 或 None。box 为画布坐标。"""
        src = self._display_image()
        x1 = max(0, int(box.left()))
        y1 = max(0, int(box.top()))
        x2 = min(src.width, int(box.right()))
        y2 = min(src.height, int(box.bottom()))
        if x2 - x1 < 3 or y2 - y1 < 3:
            return None
        key = (x1, y1, x2, y2)
        if key in self._mosaic_cache:
            return self._mosaic_cache[key]
        crop = src.crop((x1, y1, x2, y2))
        _pixelate(crop, (0, 0, crop.width, crop.height), config.MOSAIC_BLOCK)
        pm = (pil_to_qpixmap(crop), QPointF(x1, y1))
        if len(self._mosaic_cache) > 40:
            self._mosaic_cache.clear()
        self._mosaic_cache[key] = pm
        return pm

    # ---------------- 文字 inline 编辑 ----------------
    def _begin_text(self, pos: QPointF) -> None:
        """在画布点击处放置 inline 文本框（含字体/大小/粗斜体浮动条）。

        pos 为画布(未缩放)坐标：提交时直接减偏移写回底图；
        文本框/工具条是画布的子控件，几何位置需乘缩放比换算成控件坐标。
        """
        canvas = self._canvas_widget
        z = self._zoom
        self._close_text_overlays()
        bar = _TextBar(canvas, self)
        overlay = _TextOverlay(canvas, self, pos, bar)
        bar.set_overlay(overlay)
        ov_w = 360
        ov_h = int(max(48, self._text_px * z * 2 + 18))
        x = int(max(2, min(pos.x() * z, canvas.width() - ov_w - 4)))
        y = int(max(2, pos.y() * z))
        overlay.setGeometry(x, y, ov_w, ov_h)
        bar.adjustSize()
        bar.move(x, max(2, y - bar.height() - 4))
        bar.show()
        overlay.show()
        overlay.setFocus()

    def _close_text_overlays(self) -> None:
        canvas = self._canvas_widget
        for child in list(canvas.children()):
            if isinstance(child, (_TextOverlay, _TextBar)):
                child.deleteLater()

    def commit_text(self, pos: QPointF, text: str, font: QFont, px: int) -> None:
        """用 QPainter 把文字画入底图（完整字体族/粗斜支持）。pos 为画布坐标。"""
        self.push_undo()
        qimg = pil_to_qimage(self._base)
        p = QPainter(qimg)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        f = QFont(font)
        # 用整数 pointSize（而非 pixelSize / pointSizeF）：整数 pt 是 Qt 最规范的
        # 字号路径，pointSize() 恒为正，可避免 QTextEdit/IME 内部把 -1 透传给
        # QFont::setPointSize 触发 "Point size <= 0" 警告。
        # DPI 缩放已禁用（逻辑 DPI=96），pt = round(px*72/96) 渲染结果与 px 精确一致。
        f.setPointSize(int(round(max(6, px) * 72.0 / 96.0)))
        p.setFont(f)
        p.setPen(QColor(self._color))
        fm = QFontMetrics(f)
        lh = fm.height()
        ox, oy = self._offset
        x = pos.x() - ox
        y = pos.y() - oy
        for i, line in enumerate(text.split("\n")):
            if line:
                p.drawText(QPointF(x, y + i * lh + fm.ascent()), line)
        p.end()
        self._base = qimage_to_pil(qimg)
        self._restyle()

    @property
    def _text_px(self) -> int:
        # 默认字号：随图宽在 16~48px 间取，避免离谱的初值
        return max(16, min(48, self._width // 12))

    # ---------------- OCR ----------------
    def _run_ocr(self) -> None:
        if not config.MINERU_API_TOKEN:
            QMessageBox.information(
                self, "未配置 OCR",
                "请在项目根目录 .env 中设置 MINERU_API_TOKEN（MinerU 平台申请）后重启。")
            return
        import tempfile
        from pathlib import Path

        tmp = Path(tempfile.gettempdir()) / "jianying_ocr.png"
        self._display_image().save(tmp)
        self._ocr_worker = MineruWorker(tmp)
        self._ocr_worker.finished_text.connect(self._ocr_done)
        self._ocr_worker.failed.connect(self._ocr_fail)
        self._ocr_worker.start()

    def _ocr_done(self, text: str) -> None:
        from jianying.utils import copy_text_to_clipboard

        dlg = QMessageBox(self)
        dlg.setWindowTitle("OCR 结果")
        dlg.setText(text[:2000] + ("…" if len(text) > 2000 else ""))
        dlg.setStandardButtons(QMessageBox.StandardButton.Ok)
        dlg.exec()
        copy_text_to_clipboard(text)

    def _ocr_fail(self, msg: str) -> None:
        QMessageBox.warning(self, "OCR 失败", msg)

    # ---------------- 导出 ----------------
    def _pin(self) -> None:
        self.pin_requested.emit(pil_to_qpixmap(self._display_image()).toImage())

    def _copy(self) -> None:
        from jianying.utils import copy_image_to_clipboard

        copy_image_to_clipboard(self._display_image())

    def _save(self) -> None:
        import time

        config.ensure_save_dir()
        default_name = f"shot_{time.strftime('%Y%m%d_%H%M%S')}.{config.SAVE_FORMAT}"
        path, _ = QFileDialog.getSaveFileName(
            self, "保存截图", str(config.SAVE_DIR / default_name),
            "PNG (*.png);;JPEG (*.jpg);;WebP (*.webp)")
        if not path:
            return
        img = self._display_image()
        if path.lower().endswith((".jpg", ".jpeg")):
            img = img.convert("RGB")
        img.save(path, quality=config.EXPORT_QUALITY)


# ---------------- inline 文字组件 ----------------
class _TextBar(QWidget):
    """文字浮动工具条：字体族 / 大小 / 粗体 / 斜体 / 确认提示。"""

    def __init__(self, canvas: QWidget, editor: EditorWindow):
        super().__init__(canvas)
        self.setObjectName("textbar")
        self._editor = editor
        self._overlay: _TextOverlay | None = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 3, 6, 3)
        lay.setSpacing(4)

        self._font_cb = QComboBox()
        fams = QFontDatabase.families()
        self._font_cb.addItems(fams)
        prefer = [f for f in ("Microsoft YaHei", "微软雅黑", "PingFang SC", "SimHei")
                  if f in fams]
        if prefer:
            self._font_cb.setCurrentText(prefer[0])
        self._font_cb.setMaximumWidth(150)
        self._font_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        lay.addWidget(self._font_cb)

        self._size = QSpinBox()
        self._size.setRange(8, 128)
        self._size.setValue(editor._text_px)
        self._size.setFixedHeight(26)
        self._size.setCursor(Qt.CursorShape.ArrowCursor)  # 上下按钮可明确点击
        lay.addWidget(self._size)

        self._b_btn = QToolButton()
        self._b_btn.setText("B")
        self._b_btn.setCheckable(True)
        self._b_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        lay.addWidget(self._b_btn)
        self._i_btn = QToolButton()
        self._i_btn.setText("I")
        self._i_btn.setCheckable(True)
        self._i_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        lay.addWidget(self._i_btn)

        tip = QLabel("Enter 确认 · Esc 取消 · Shift+Enter 换行")
        lay.addWidget(tip)

        # 样式只作用于 #textbar 本体与指定控件；QWidget{} 通配会污染
        # QSpinBox 内部子控件，导致上下按钮被遮住点不到
        self.setStyleSheet(
            "QWidget#textbar{background:rgba(30,30,30,235);border-radius:6px;}"
            "QWidget#textbar QLabel{color:#ddd;border:none;background:transparent;}"
            "QWidget#textbar QComboBox{background:#3a3a3a;color:#ffffff;border:none;"
            "border-radius:3px;padding:2px 6px;}"
            "QComboBox QAbstractItemView{background:#3a3a3a;color:#ffffff;"
            "selection-background-color:#00A8FF;selection-color:#ffffff;"
            "outline:none;}"
            "QWidget#textbar QSpinBox{background:#3a3a3a;color:#ffffff;border:none;"
            "border-radius:3px;padding:2px 20px 2px 4px;}"
            "QWidget#textbar QSpinBox::up-button,QSpinBox::down-button"
            "{width:17px;border:none;background:#4a4a4a;}"
            "QWidget#textbar QSpinBox::up-button:hover,QSpinBox::down-button:hover"
            "{background:#00A8FF;}"
            "QWidget#textbar QToolButton{background:#3a3a3a;color:#ffffff;"
            "border:none;border-radius:3px;}"
            "QWidget#textbar QToolButton:checked{background:#00A8FF;color:#ffffff;}")

        self._font_cb.currentIndexChanged.connect(self._apply)
        self._size.valueChanged.connect(self._apply)
        self._b_btn.toggled.connect(self._apply)
        self._i_btn.toggled.connect(self._apply)

    def set_overlay(self, overlay: "_TextOverlay") -> None:
        self._overlay = overlay

    def _apply(self, *_) -> None:
        if self._overlay is not None:
            # 字号是底图 px；显示时随画布缩放放大，保证所见即所得
            px = int(self._size.value() * self._editor._zoom)
            self._overlay.refresh_font(self.current_font(), px)

    def current_font(self) -> QFont:
        f = QFont(self._font_cb.currentText())
        if f.pointSize() <= 0:
            f.setPointSize(9)   # 兜底，保持 pointSize 恒为正（整数 pt）
        f.setBold(self._b_btn.isChecked())
        f.setItalic(self._i_btn.isChecked())
        return f


class _TextOverlay(QTextEdit):
    """画布上的 inline 文本框：Enter 提交、Esc 取消、Shift+Enter 换行。"""

    def __init__(self, canvas: QWidget, editor: EditorWindow, pos: QPointF,
                 bar: _TextBar):
        super().__init__(canvas)
        self._editor = editor
        self._canvas = canvas
        self._bar = bar
        self._pos = QPointF(pos)
        self.setPlaceholderText("输入文字…")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(
            f"QTextEdit{{background:rgba(0,168,255,30);border:1px dashed #00A8FF;"
            f"color:{editor._color.name()};}}")
        self.refresh_font(bar.current_font(),
                          int(bar._size.value() * editor._zoom))

    def refresh_font(self, f: QFont, px: int) -> None:
        f2 = QFont(f)
        # 同 commit_text：整数 pt 替代 pixelSize，避免 pointSize=-1 警告
        f2.setPointSize(int(round(max(6, px) * 72.0 / 96.0)))
        self.setFont(f2)
        self.document().setDefaultFont(f2)
        fm = QFontMetrics(f2)
        self.setMinimumHeight(fm.height() + 12)

    def keyPressEvent(self, e) -> None:
        if (e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and not (e.modifiers() & Qt.KeyboardModifier.ShiftModifier)):
            self._commit()
            return
        if e.key() == Qt.Key.Key_Escape:
            self._close()
            return
        super().keyPressEvent(e)

    def _commit(self) -> None:
        text = self.toPlainText()
        if text.strip():
            self._editor.commit_text(self._pos, text,
                                     self._bar.current_font(),
                                     self._bar._size.value())
        self._close()

    def _close(self) -> None:
        self._editor._close_text_overlays()


# ---------------- 画布 ----------------
class _Canvas(QWidget):
    """显示底图 + 进行中的绘制预览 + 马赛克实时预览 + inline 文字组件。"""

    def __init__(self, editor: EditorWindow):
        super().__init__()
        self._editor = editor
        self._pm: QPixmap | None = None
        self._mosaic_prev = None  # (pm, tl) 马赛克实时预览
        self._mouse = QPointF()   # 光标实时位置（多边形预览用）
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # 接收 Esc 取消多边形

    def set_pixmap(self, pm: QPixmap) -> None:
        """存入原尺寸画布；控件尺寸按缩放比放大。"""
        z = self._editor._zoom
        self._pm = pm
        self.setFixedSize(max(1, round(pm.width() * z)),
                          max(1, round(pm.height() * z)))

    def _c(self, pt: QPointF) -> QPointF:
        """控件(缩放后)坐标 → 画布(未缩放)坐标：所有编辑器状态统一用画布坐标。"""
        z = self._editor._zoom
        return QPointF(pt.x() / z, pt.y() / z)

    def mousePressEvent(self, e) -> None:
        ed = self._editor
        if ed._tool == "text":
            if e.button() == Qt.MouseButton.LeftButton:
                ed._begin_text(self._c(e.position()))
            return
        if ed._tool == "poly":
            if e.button() == Qt.MouseButton.LeftButton:
                ed._poly_points.append(self._c(e.position()))
            elif (e.button() == Qt.MouseButton.RightButton
                  and len(ed._poly_points) >= 3):
                ed.commit_poly()   # 右键闭合
            self.update()
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        ed._state = STATE_DRAW
        ed._start = self._c(e.position())
        ed._end = ed._start
        ed._painted_paths = [ed._start]

    def mouseDoubleClickEvent(self, e) -> None:
        if self._editor._tool == "poly" and len(self._editor._poly_points) >= 3:
            self._editor.commit_poly()  # 双击闭合

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape and self._editor._tool == "poly":
            self._editor._poly_points = []  # Esc 取消
            self.update()
            return
        super().keyPressEvent(e)

    def mouseMoveEvent(self, e) -> None:
        ed = self._editor
        self._mouse = self._c(e.position())
        if ed._tool == "poly" and ed._poly_points:
            self.update()   # 多边形预览跟随光标
            return
        if ed._state != STATE_DRAW:
            return
        ed._end = self._c(e.position())
        if ed._tool == "pen":
            ed._painted_paths.append(ed._end)
        elif ed._tool == "mosaic":
            self._mosaic_prev = ed.mosaic_preview(
                QRectF(ed._start, ed._end).normalized())
        self.update()

    def mouseReleaseEvent(self, e) -> None:
        if self._editor._state != STATE_DRAW:
            return
        self._editor._state = STATE_IDLE
        self._editor.commit_shape(self._editor._start, self._c(e.position()))
        self._mosaic_prev = None
        self.update()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        z = self._editor._zoom
        p.scale(z, z)   # 之后全部按画布坐标绘制，线宽/预览随缩放等比放大
        if z < 1:
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self._pm:
            p.drawPixmap(0, 0, self._pm)
        ed = self._editor
        pen = QPen(ed._color, ed._width)
        if ed._tool == "poly" and ed._poly_points:
            # 多边形进行中预览：已落顶点连线 + 末点到光标的橡皮筋
            pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            pts = ed._poly_points
            for i in range(1, len(pts)):
                p.drawLine(pts[i - 1], pts[i])
            if self._mouse.x() or self._mouse.y():
                p.drawLine(pts[-1], self._mouse)
        elif ed._state == STATE_DRAW and ed._tool in ("arrow", "rect",
                                                      "ellipse", "rpoly"):
            p.setPen(pen)
            s, e = ed._start, ed._end
            tool = ed._tool
            if tool == "rect":
                p.drawRect(QRectF(s, e).normalized())
            elif tool == "ellipse":
                p.drawEllipse(QRectF(s, e).normalized())
            elif tool == "rpoly":
                pts = _rpoly_points(s, e, ed._poly_sides)
                for i in range(len(pts)):
                    p.drawLine(pts[i], pts[(i + 1) % len(pts)])
            else:
                p.drawLine(s, e)
        elif ed._state == STATE_DRAW and ed._tool == "pen":
            pen = QPen(ed._color, ed._width,
                       Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                       Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            pts = ed._painted_paths
            for i in range(1, len(pts)):
                p.drawLine(pts[i - 1], pts[i])
        elif ed._state == STATE_DRAW and ed._tool == "mosaic" and self._mosaic_prev:
            pm, tl = self._mosaic_prev
            p.drawPixmap(tl, pm)
        p.end()


# ---------------- 图元绘制辅助 ----------------
def _swatch_qss(tpl: dict | None) -> str:
    """模板色块按钮样式：无背景/透明=棋盘格，纯色=色块，渐变=CSS 渐变。"""
    if tpl is None or tpl.get("type") == "transparent":
        bg = ("qlineargradient(x1:0,y1:0,x2:0,y2:1,"
              "stop:0 #ffffff,stop:0.5 #ffffff,"
              "stop:0.5 #c8ccd0,stop:1 #c8ccd0)")
    elif tpl.get("type") == "solid":
        bg = tpl.get("colors", ["#FFFFFF"])[0]
    else:
        c = tpl.get("colors", ["#2193b0", "#6dd5ed"])
        if len(c) == 1:
            c = c * 2
        bg = f"qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {c[0]},stop:1 {c[1]})"
    return (f"QToolButton{{background:{bg};border:1px solid #b9c2ca;"
            "border-radius:4px;}"
            "QToolButton:checked{border:2px solid #00A8FF;}")


def _rpoly_points(start: QPointF, end: QPointF, n: int) -> list[QPointF]:
    """按包围盒计算正 n 边形顶点（顶点朝上），画布坐标。"""
    import math

    r = QRectF(start, end).normalized()
    cx, cy = r.center().x(), r.center().y()
    rx, ry = r.width() / 2, r.height() / 2
    out = []
    for i in range(max(3, n)):
        ang = -math.pi / 2 + 2 * math.pi * i / max(3, n)
        out.append(QPointF(cx + rx * math.cos(ang), cy + ry * math.sin(ang)))
    return out


def _draw_arrow(d: ImageDraw.ImageDraw, start, end, color, width: int,
                head: str = "sharp") -> None:
    """head: sharp 尖头 / round 圆头 / none 无头。"""
    import math

    x1, y1 = start
    x2, y2 = end
    d.line([x1, y1, x2, y2], fill=color, width=width)
    if head == "none":
        return
    if head == "round":
        r = max(4, width * 2)
        d.ellipse([x2 - r, y2 - r, x2 + r, y2 + r], fill=color)
        return
    ang = math.atan2(y2 - y1, x2 - x1)
    L = max(12, width * 4)
    for da in (math.radians(150), -math.radians(150)):
        px = x2 + L * math.cos(ang + da)
        py = y2 + L * math.sin(ang + da)
        d.line([x2, y2, px, py], fill=color, width=width)


def _pixelate(img, box, block: int) -> None:
    region = img.crop(box)
    w, h = region.size
    small = region.resize((max(1, w // block), max(1, h // block)), Image.Resampling.NEAREST)
    img.paste(small.resize((w, h), Image.Resampling.NEAREST), box)
