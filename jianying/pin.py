"""截图固定（贴图）窗口：置顶无边框、可拖动、滚轮调透明度、Ctrl+滚轮缩放。"""
from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QPainter, QPixmap
from PyQt6.QtWidgets import QMenu, QWidget


class PinWindow(QWidget):
    def __init__(self, image, parent=None):
        super().__init__(parent)
        self._pm = QPixmap.fromImage(image)
        self._opacity = 1.0
        self._drag_offset = QPoint()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(self._pm.size())
        self.show()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setOpacity(self._opacity)
        p.drawPixmap(0, 0, self._pm)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e) -> None:
        if e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_offset)

    def mouseDoubleClickEvent(self, _) -> None:
        self.close()

    def wheelEvent(self, e) -> None:
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            # Ctrl+滚轮：缩放
            step = 1.1 if e.angleDelta().y() > 0 else 1 / 1.1
            nw = max(80, int(self.width() * step))
            nh = max(80, int(self.height() * step))
            self._pm = self._pm.scaled(nw, nh, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
            self.resize(self._pm.size())
        else:
            # 滚轮：透明度
            self._opacity = min(1.0, max(0.15, self._opacity + (0.06 if e.angleDelta().y() > 0 else -0.06)))
        self.update()

    def contextMenuEvent(self, e) -> None:
        menu = QMenu(self)
        menu.addAction("⧉ 复制", self._copy)
        menu.addAction("💾 保存…", self._save)
        menu.addSeparator()
        menu.addAction("✕ 关闭贴图", self.close)
        menu.exec(e.globalPos())

    def _copy(self) -> None:
        from jianying.utils import copy_image_to_clipboard
        from jianying.utils import qimage_to_pil

        copy_image_to_clipboard(qimage_to_pil(self._pm.toImage()))

    def _save(self) -> None:
        from PyQt6.QtWidgets import QFileDialog

        from jianying import config

        config.ensure_save_dir()
        path, _ = QFileDialog.getSaveFileName(
            self, "保存贴图", str(config.SAVE_DIR / "pin.png"), "PNG (*.png)")
        if path:
            self._pm.save(path)
