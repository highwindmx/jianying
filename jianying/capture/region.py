"""区域框选覆盖窗口（Snipaste 风格冻结桌面 + 框选 + 放大镜 + 取色 + 窗口猜测）。

坐标系约定：
- 窗口/鼠标：Qt 逻辑坐标（虚拟桌面，origin 可能为负）
- 截图像素：物理像素（mss/QImage 原始数据）
"""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QImage,
    QPainter,
    QPen,
)
from PyQt6.QtWidgets import QWidget

from jianying import config
from jianying.capture.grabber import ScreenGrab

try:
    import cv2
    import numpy as np
    HAS_OPENCV = True
except ImportError:  # pragma: no cover
    HAS_OPENCV = False

HANDLE = 4          # 手柄半径（逻辑 px）
BORDER = 2
MIN_SIZE = 8

# 边框 8 区 → 缩放光标
_CURSOR_MAP = {
    "tl": Qt.CursorShape.SizeFDiagCursor,
    "br": Qt.CursorShape.SizeFDiagCursor,
    "tr": Qt.CursorShape.SizeBDiagCursor,
    "bl": Qt.CursorShape.SizeBDiagCursor,
    "l":  Qt.CursorShape.SizeHorCursor,
    "r":  Qt.CursorShape.SizeHorCursor,
    "t":  Qt.CursorShape.SizeVerCursor,
    "b":  Qt.CursorShape.SizeVerCursor,
}
# 取色提示常驻文字
_COLOR_HINT = "按 C 复制颜色代码(HEX) · 按 Shift+C 复制 RGB 值"


class RegionOverlay(QWidget):
    """全屏冻结覆盖层。captured(物理QImage) / cancelled。"""

    captured = pyqtSignal(QImage, str)   # (物理裁剪图, 动作: edit/copy/save/scroll)
    cancelled = pyqtSignal()
    record_requested = pyqtSignal(QRect)   # 录像：物理像素选区

    def __init__(self, grab: ScreenGrab, parent=None):
        super().__init__(parent)
        self._grab = grab
        self._pm = grab.pixmap
        self._dpr = grab.dpr
        self._rect = QRectF()          # 选区（逻辑坐标）
        self._mode = "idle"            # idle / drag / move / resize
        self._drag_start = QPointF()
        self._resize_edge: str = ""
        self._move_offset = QPointF()
        self._mouse = QPointF()
        self._guess_rects: list[tuple[int, int, int, int]] = []  # 物理像素
        self._guess_enabled = config.GUESS_ENABLED and HAS_OPENCV
        self._hover_follow = True           # 未按下鼠标前悬停自动吸附窗口
        self._toolbar: "_RegionToolbar | None" = None
        self._toast_text = ""                    # C 键复制颜色的瞬时提示
        self._toast_timer: QTimer | None = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setGeometry(grab.virtual_rect)

        if self._guess_enabled:
            self._build_guess_rects()

    # ---------- 窗口 ----------
    def launch(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self.setMouseTracking(True)
        self.show_toolbar()                 # 工具条随覆盖层即出（模式选择）

    # ---------- 窗口猜测 ----------
    def _build_guess_rects(self) -> None:
        img = self._grab.image
        w, h = img.width(), img.height()
        buf = bytes(img.constBits().asarray(img.sizeInBytes()))
        arr = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)
        gray = cv2.cvtColor(arr, cv2.COLOR_BGRA2GRAY)
        edges = cv2.Canny(gray, 40, 140)
        edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
        contours, _ = cv2.findContours(
            edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE
        )
        total = w * h
        rects = []
        for c in contours:
            x, y, cw, ch = cv2.boundingRect(c)
            if cw >= 24 and ch >= 24 and cw * ch < total * 0.96:
                rects.append((x, y, cw, ch))
        # 面积升序：优先命中更小的窗口/控件
        rects.sort(key=lambda r: r[2] * r[3])
        self._guess_rects = rects

    def _guess_window(self, phys: QPoint) -> QRect | None:
        for x, y, cw, ch in self._guess_rects:
            if x <= phys.x() <= x + cw and y <= phys.y() <= y + ch:
                tl = self._grab.physical_to_logical(x, y)
                br = self._grab.physical_to_logical(x + cw, y + ch)
                return QRect(tl, br)
        return None

    # ---------- 鼠标 ----------
    def mousePressEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self._hover_follow = False          # 开始交互后停止悬停跟随
        pos = e.position()
        edge = self._handle_at(pos)
        if not self._rect.isNull() and edge:
            self._mode = "resize"
            self._resize_edge = edge
        elif not self._rect.isNull() and self._rect.contains(pos):
            self._mode = "move"
            self._move_offset = pos - self._rect.topLeft()
        else:
            self._mode = "drag"
            self._rect = QRectF(pos, pos)
            self._drag_start = pos
        self.hide_toolbar()
        self.update()

    def mouseMoveEvent(self, e) -> None:
        pos = e.position()
        self._mouse = pos
        if self._mode == "drag":
            self._rect = QRectF(self._drag_start, pos).normalized()
        elif self._mode == "move":
            self._rect.moveTopLeft(pos - self._move_offset)
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        elif self._mode == "resize":
            self._apply_resize(pos)
            self.setCursor(_CURSOR_MAP.get(
                self._resize_edge, Qt.CursorShape.CrossCursor))
        elif self._guess_enabled and self._hover_follow:
            # 悬停自动吸附：仅在尚未开始框选时跟随
            g = self._guess_window(self._grab.to_physical(pos.toPoint()))
            if g is not None:
                self._rect = QRectF(g)
        if self._mode == "idle":
            self._update_cursor(pos)
        self.update()

    def _update_cursor(self, pos: QPointF) -> None:
        """整圈边框 → 对应缩放光标；选区内 → 移动光标；其余 → 十字。"""
        if self._rect.isNull():
            self.setCursor(Qt.CursorShape.CrossCursor)
            return
        cur = _CURSOR_MAP.get(self._handle_at(pos))
        if cur is None:
            cur = (Qt.CursorShape.SizeAllCursor if self._rect.contains(pos)
                   else Qt.CursorShape.CrossCursor)
        self.setCursor(cur)

    def mouseReleaseEvent(self, e) -> None:
        if self._mode in ("drag", "move", "resize"):
            self._mode = "idle"
            if not self._rect.isNull() and self._rect.width() >= MIN_SIZE:
                self.show_toolbar()
        self.update()

    # ---------- 浮动工具栏 ----------
    def _has_selection(self) -> bool:
        return (not self._rect.isNull()
                and self._rect.width() >= MIN_SIZE
                and self._rect.height() >= MIN_SIZE)

    def show_toolbar(self) -> None:
        if self._toolbar is None:
            self._toolbar = _RegionToolbar(self)
        tb = self._toolbar
        tb.adjustSize()
        if self._has_selection():
            r = self._rect
            margin = 8
            x = r.left()
            y = r.bottom() + margin
            if y + tb.height() > self.height() - 4:      # 下方放不下 → 上方
                y = r.top() - tb.height() - margin
            y = max(4, y)
            x = min(max(4, x), self.width() - tb.width() - 4)
        else:
            # 无选区：停靠屏幕底部中央，提示先框选
            x = (self.width() - tb.width()) / 2
            y = self.height() - tb.height() - 24
        tb.move(int(x), int(y))
        tb.set_hint_visible(not self._has_selection())
        tb.show()
        tb.raise_()

    def hide_toolbar(self) -> None:
        if self._toolbar is not None and self._toolbar.isVisible():
            self._toolbar.hide()

    def mouseDoubleClickEvent(self, e) -> None:
        self.confirm()

    def _handle_at(self, pos: QPointF) -> str:
        """返回鼠标所在边框区域：tl/tr/bl/br/t/b/l/r 或空串。"""
        if self._rect.isNull():
            return ""
        r = self._rect
        band = 7                      # 边框命中带（逻辑 px），覆盖整圈
        on_l = abs(pos.x() - r.left()) <= band
        on_r = abs(pos.x() - r.right()) <= band
        on_t = abs(pos.y() - r.top()) <= band
        on_b = abs(pos.y() - r.bottom()) <= band
        if on_l and on_t:
            return "tl"
        if on_r and on_t:
            return "tr"
        if on_l and on_b:
            return "bl"
        if on_r and on_b:
            return "br"
        if on_l:
            return "l"
        if on_r:
            return "r"
        if on_t:
            return "t"
        if on_b:
            return "b"
        return ""

    def _apply_resize(self, pos: QPointF) -> None:
        r = self._rect
        left, top = r.left(), r.top()
        right, bottom = r.right(), r.bottom()
        edge = self._resize_edge
        if "l" in edge:
            left = pos.x()
        if "r" in edge:
            right = pos.x()
        if "t" in edge:
            top = pos.y()
        if "b" in edge:
            bottom = pos.y()
        self._rect = QRectF(QPointF(left, top), QPointF(right, bottom)).normalized()

    # ---------- 键盘 ----------
    def keyPressEvent(self, e) -> None:
        key = e.key()
        if key == Qt.Key.Key_Escape:
            self.cancelled.emit()
            self.close()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.confirm()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            step = 10 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            dx = dy = 0
            if key == Qt.Key.Key_Left:
                dx = -step
            elif key == Qt.Key.Key_Right:
                dx = step
            elif key == Qt.Key.Key_Up:
                dy = -step
            else:
                dy = step
            if not self._rect.isNull():
                self._rect.translate(dx, dy)
                self.update()
        elif key == Qt.Key.Key_Tab:  # Tab: 吸附到猜测窗口
            if self._guess_enabled:
                g = self._guess_window(self._grab.to_physical(self._mouse.toPoint()))
                if g is not None:
                    self._rect = QRectF(g)
                    self.update()
        elif key == Qt.Key.Key_C:  # C 复制HEX / ⇧C 复制RGB
            self._copy_color(
                shift=bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier))

    # ---------- 确认 ----------
    def confirm(self, action: str = "edit") -> None:
        if self._rect.isNull() or self._rect.width() < MIN_SIZE or self._rect.height() < MIN_SIZE:
            return
        # 逻辑坐标 → 物理像素，强制归一化 + 完整 clamp 到图像范围
        # （QImage.copy 对负宽高/不相交 rect 会静默返回 null QImage）
        p1 = self._grab.to_physical(self._rect.topLeft().toPoint())
        p2 = self._grab.to_physical(self._rect.bottomRight().toPoint())
        x1, x2 = sorted((p1.x(), p2.x()))
        y1, y2 = sorted((p1.y(), p2.y()))
        x1, y1 = max(0, x1), max(0, y1)
        x2 = min(self._grab.image.width(), x2)
        y2 = min(self._grab.image.height(), y2)
        self._result_rect = QRect(QPoint(x1, y1), QPoint(x2, y2)).normalized()
        if self._result_rect.width() < MIN_SIZE or self._result_rect.height() < MIN_SIZE:
            return
        crop = self._grab.image.copy(self._result_rect)
        if crop.isNull():
            return  # 理论不可达：rect 已保证有效
        self.captured.emit(crop, action)
        self.hide_toolbar()
        self.close()

    def start_record(self) -> None:
        """录像：把选区换算成物理像素矩形后发出（须先关闭覆盖层，否则会录进去）。"""
        if not self._has_selection():
            return
        p1 = self._grab.to_physical(self._rect.topLeft().toPoint())
        p2 = self._grab.to_physical(self._rect.bottomRight().toPoint())
        x1, x2 = sorted((p1.x(), p2.x()))
        y1, y2 = sorted((p1.y(), p2.y()))
        x1, y1 = max(0, x1), max(0, y1)
        x2 = min(self._grab.image.width(), x2)
        y2 = min(self._grab.image.height(), y2)
        rect = QRect(QPoint(x1, y1), QPoint(x2, y2)).normalized()
        if rect.width() < MIN_SIZE or rect.height() < MIN_SIZE:
            return
        self._result_rect = rect
        self.hide_toolbar()
        self.close()
        self.record_requested.emit(rect)

    @property
    def result_rect(self) -> QRect:
        """最近一次确认的选区（物理像素坐标），供滚动截图等复用。"""
        return getattr(self, "_result_rect", QRect())

    # ---------- 取色复制 ----------
    def _copy_color(self, shift: bool) -> None:
        """C 复制 #RRGGBB；⇧C 复制 rgb(r,g,b)，并给瞬时提示。"""
        phys = self._grab.to_physical(self._mouse.toPoint())
        iw, ih = self._grab.image.width(), self._grab.image.height()
        px = min(max(phys.x(), 0), iw - 1)
        py = min(max(phys.y(), 0), ih - 1)
        c = QColor(self._grab.image.pixel(px, py))
        text = (f"rgb({c.red()},{c.green()},{c.blue()})"
                if shift else f"#{c.red():02X}{c.green():02X}{c.blue():02X}")
        from jianying.utils import copy_text_to_clipboard
        copy_text_to_clipboard(text)
        self._toast(f"已复制颜色代码（RGB）：{text}"
                    if shift else f"已复制颜色代码（HEX）：{text}")

    def _toast(self, text: str) -> None:
        self._toast_text = text
        self.update()
        if self._toast_timer is None:
            self._toast_timer = QTimer(self)
            self._toast_timer.setSingleShot(True)
            self._toast_timer.timeout.connect(self._clear_toast)
        self._toast_timer.start(1400)

    def _clear_toast(self) -> None:
        self._toast_text = ""
        self.update()

    # ---------- 绘制 ----------
    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.drawPixmap(0, 0, self._pm)

        r = self._rect
        # 暗罩：选区外四块
        if not r.isNull():
            mask = QColor(0, 0, 0, 110)
            vw, vh = self.width(), self.height()
            p.fillRect(QRectF(0, 0, vw, r.top()), mask)
            p.fillRect(QRectF(0, r.bottom(), vw, vh - r.bottom()), mask)
            p.fillRect(QRectF(0, r.top(), r.left(), r.height()), mask)
            p.fillRect(QRectF(r.right(), r.top(), vw - r.right(), r.height()), mask)

            # 边框 + 手柄
            pen = QPen(QColor("#00A8FF"), BORDER)
            p.setPen(pen)
            p.drawRect(r)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#FFFFFF"))
            for pt in self._handle_points():
                p.drawEllipse(pt, HANDLE, HANDLE)

            # 尺寸提示
            label = f"{round(r.width())} × {round(r.height())}"
            self._draw_label(p, r.topLeft() + QPointF(0, -26), label)
        else:
            tip = "拖拽框选 · Tab 吸附窗口 · Esc 退出"
            self._draw_label(p, QPointF(self.width() / 2 - 120, 20), tip)

        # 放大镜
        self._draw_magnifier(p)

        # C 键复制颜色的瞬时提示（底部居中）
        if self._toast_text:
            self._draw_label(
                p, QPointF(self.width() / 2 - 80, self.height() - 86),
                self._toast_text)

        p.end()

    def _handle_points(self):
        r = self._rect
        yield r.topLeft()
        yield r.topRight()
        yield r.bottomLeft()
        yield r.bottomRight()
        yield QPointF(r.center().x(), r.top())
        yield QPointF(r.center().x(), r.bottom())
        yield QPointF(r.left(), r.center().y())
        yield QPointF(r.right(), r.center().y())

    def _draw_label(self, p: QPainter, top_left: QPointF, text: str) -> int:
        f = QFont()
        f.setPointSize(10)
        f.setBold(True)
        p.setFont(f)
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(text) + 16
        h = fm.height() + 6
        y = max(4, top_left.y())
        bg = QRectF(top_left.x(), y, w, h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 20, 20, 200))
        p.drawRoundedRect(bg, 4, 4)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(bg, Qt.AlignmentFlag.AlignCenter, text)
        return h

    def _draw_magnifier(self, p: QPainter) -> None:
        n = config.MAGNIFIER_SIZE
        zoom = config.MAGNIFIER_ZOOM
        size = n * zoom  # 逻辑 px

        phys = self._grab.to_physical(self._mouse.toPoint())
        iw, ih = self._grab.image.width(), self._grab.image.height()
        half = n // 2
        cell_colors = []
        for gy in range(n):
            row = []
            for gx in range(n):
                px = min(max(phys.x() - half + gx, 0), iw - 1)
                py = min(max(phys.y() - half + gy, 0), ih - 1)
                c = self._grab.image.pixel(px, py)
                row.append(QColor(c))
            cell_colors.append(row)

        # 位置：鼠标右下，越界翻转
        vx, vy = self._mouse.x(), self._mouse.y()
        x = vx + 18
        y = vy + 18
        if x + size + 8 > self.width():
            x = vx - size - 18
        if y + size + 34 > self.height():
            y = vy - size - 18 - 34

        border = 2
        p.setPen(QPen(QColor("#FFFFFF"), border))
        p.setBrush(QColor("#000000"))
        p.drawRect(QRectF(x - border, y - border, size + border * 2, size + border * 2))
        for gy in range(n):
            for gx in range(n):
                p.fillRect(QRectF(x + gx * zoom, y + gy * zoom, zoom, zoom),
                           cell_colors[gy][gx])

        # 中心十字 + 中心像素 HEX
        cx, cy = x + half * zoom + zoom / 2, y + half * zoom + zoom / 2
        center = cell_colors[half][half]
        p.setPen(QPen(QColor("#FF3B30"), 1))
        p.drawLine(QPointF(cx - zoom / 2, cy), QPointF(cx + zoom / 2, cy))
        p.drawLine(QPointF(cx, cy - zoom / 2), QPointF(cx, cy + zoom / 2))

        hex_text = f"{center.red():02X}{center.green():02X}{center.blue():02X}"
        rgb_text = f"({center.red()},{center.green()},{center.blue()})"
        label = f"#{hex_text} {rgb_text}"
        h1 = self._draw_label(p, QPointF(x, y + size + 4), label)

        # 常驻取色快捷键提示（在颜色标签下方）
        hf = QFont()
        hf.setPointSize(9)
        p.setFont(hf)
        fm = p.fontMetrics()
        h2 = fm.height() + 4
        hw = fm.horizontalAdvance(_COLOR_HINT) + 12
        hb = QRectF(x, y + size + 4 + h1 + 2, hw, h2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 20, 20, 200))
        p.drawRoundedRect(hb, 4, 4)
        p.setPen(QColor(150, 200, 255))
        p.drawText(hb, Qt.AlignmentFlag.AlignCenter, _COLOR_HINT)

    # 鼠标离开窗口也保持（覆盖层全屏不会离开）


class _RegionToolbar(QWidget):
    """覆盖层工具条：框选前提示框选，框选后选择模式（截图/复制/保存/滚动/录像）。可拖动。"""

    def __init__(self, overlay: RegionOverlay):
        super().__init__(overlay)
        self._overlay = overlay
        self._drag_offset = None

        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setCursor(Qt.CursorShape.ArrowCursor)

        from PyQt6.QtWidgets import QHBoxLayout, QLabel, QToolButton

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 6, 4)
        lay.setSpacing(2)

        self._hint = QLabel("请先拖拽框选区域 ↓")
        self._hint.setStyleSheet("color:#9fd4ff;font-size:12px;padding-right:6px;")
        lay.addWidget(self._hint)

        # (文字, 提示, 动作)。None 动作 = 取消
        for text, tip, action in (
            ("复制剪贴板", "复制选区原图到剪贴板", "copy"),
            ("保存到本地", "保存选区原图到文件", "save"),
            ("滚动截图", "滚动截图（长图拼接）", "scroll"),
            ("屏幕录像", "录制选区屏幕为视频", "record"),
            ("截图编辑", "截图 → 进入编辑器 (Enter)", "edit"),
            ("取消截图", "取消 (Esc)", None),
        ):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setFixedHeight(28)
            if action:
                b.clicked.connect(lambda _=False, a=action: self._act(a))
            else:
                b.clicked.connect(self._cancel)
            lay.addWidget(b)
        self.setStyleSheet(
            "QToolButton{background:rgba(30,30,30,220);color:white;"
            "border:none;border-radius:4px;font-size:12px;padding:0 8px;}"
            "QToolButton:hover{background:#00A8FF;}"
            "_RegionToolbar{background:rgba(20,20,20,230);border-radius:6px;}")

    def _act(self, action: str) -> None:
        if not self._overlay._has_selection():
            self._hint.setText("⚠ 先拖拽框选一个区域")
            self._hint.setStyleSheet("color:#ffb340;font-size:12px;padding-right:6px;")
            return
        if action == "record":
            self._overlay.start_record()   # 录像需要选区（录制该区域）
            return
        self._overlay.confirm(action)

    def set_hint_visible(self, visible: bool) -> None:
        self._hint.setVisible(visible)

    def _cancel(self) -> None:
        self._overlay.hide_toolbar()
        self._overlay.cancelled.emit()
        self._overlay.close()

    # —— 拖动 ——
    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e) -> None:
        if self._drag_offset is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, _) -> None:
        self._drag_offset = None
