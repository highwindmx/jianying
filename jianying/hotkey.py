"""全局热键（pynput GlobalHotKeys，后台线程回调 → Qt signal 跨线程转发）。"""
from __future__ import annotations

from pynput import keyboard
from PyQt6.QtCore import QObject, pyqtSignal

from jianying import config


class HotkeyManager(QObject):
    capture_triggered = pyqtSignal()      # 区域截图
    fullscreen_triggered = pyqtSignal()   # 全屏截图
    pin_last_triggered = pyqtSignal()     # 贴图上一张
    scroll_triggered = pyqtSignal()       # 滚动截图

    def __init__(self, parent=None):
        super().__init__(parent)
        mapping = {
            config.HOTKEY_CAPTURE: lambda: self.capture_triggered.emit(),
            config.HOTKEY_FULLSCREEN: lambda: self.fullscreen_triggered.emit(),
            config.HOTKEY_PIN_LAST: lambda: self.pin_last_triggered.emit(),
            config.HOTKEY_SCROLL: lambda: self.scroll_triggered.emit(),
        }
        self._listener = keyboard.GlobalHotKeys(mapping)
        self._listener.daemon = True
        self._listener.start()

    def stop(self) -> None:
        self._listener.stop()
