"""系统托盘（pystray，独立线程；图标程序化生成，无外部资源依赖）。"""
from __future__ import annotations

import threading

import pystray
from PIL import Image
from PyQt6.QtCore import QObject, pyqtSignal

from jianying.icon import make_icon


def _make_icon_image(size: int = 64) -> Image.Image:
    """「剪影」图标：彩虹渐变圆角底 + 白色「剪」字。"""
    return make_icon(size)


class TrayIcon(QObject):
    capture_clicked = pyqtSignal()
    fullscreen_clicked = pyqtSignal()
    pin_last_clicked = pyqtSignal()
    scroll_clicked = pyqtSignal()
    quit_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._icon = pystray.Icon(
            "jianying",
            icon=_make_icon_image(),
            title="剪影 · 截图美化",
            menu=pystray.Menu(
                pystray.MenuItem("📷 截图 (Ctrl+Shift+A)",
                                 lambda *_: self.capture_clicked.emit(), default=True),
                pystray.MenuItem("🖥 全屏截图 (Ctrl+Shift+F)",
                                 lambda *_: self.fullscreen_clicked.emit()),
                pystray.MenuItem("📌 贴图上一张 (Ctrl+Shift+S)",
                                 lambda *_: self.pin_last_clicked.emit()),
                pystray.MenuItem("📜 滚动截图 (Ctrl+Shift+D)",
                                 lambda *_: self.scroll_clicked.emit()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", lambda *_: self.quit_clicked.emit()),
            ),
        )
        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._icon.stop()
