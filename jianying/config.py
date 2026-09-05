"""全局配置：路径、热键、OCR。可被项目根目录 .env 覆盖。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# 项目根 = 包上一级（源码模式）；打包后指向 _internal/jianying 的祖父目录
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


def _assets_dir() -> Path:
    """资源根目录，兼容「源码运行」与「PyInstaller 打包」两种环境。

    - 源码：<项目根>/assets
    - 打包 onedir：优先取 exe 同级 assets（用户可放自定义模板），否则取 _MEIPASS
    - 打包 onefile：_MEIPASS/assets（临时解压目录，只读）
    """
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        local = exe_dir / "assets"
        if local.exists():
            return local
        return Path(getattr(sys, "_MEIPASS", str(exe_dir))) / "assets"
    return ROOT_DIR / "assets"


# 资源根（图标/背景模板目录）
ASSETS_DIR = _assets_dir()

def _env(key: str, default: str) -> str:
    v = os.getenv(key)
    return v if v else default

# ---- 热键（pynput GlobalHotKeys 语法）----
HOTKEY_CAPTURE    = _env("HOTKEY_CAPTURE", "<ctrl>+<shift>+a")
HOTKEY_FULLSCREEN = _env("HOTKEY_FULLSCREEN", "<ctrl>+<shift>+f")
HOTKEY_PIN_LAST   = _env("HOTKEY_PIN_LAST", "<ctrl>+<shift>+s")
HOTKEY_SCROLL     = _env("HOTKEY_SCROLL", "<ctrl>+<shift>+d")

# ---- 保存 ----
SAVE_DIR = Path(_env("SAVE_DIR", str(Path.home() / "Pictures" / "jianying")))
SAVE_FORMAT = _env("SAVE_FORMAT", "png").lower()          # png / jpg / webp
EXPORT_QUALITY = int(_env("EXPORT_QUALITY", "92"))         # jpg/webp 质量

# ---- 截图行为 ----
MOSAIC_BLOCK = int(_env("MOSAIC_BLOCK", "14"))             # 马赛克块大小 px
GUESS_ENABLED = _env("GUESS_ENABLED", "1") == "1"          # 窗口边界自动猜测
MAGNIFIER_SIZE = int(_env("MAGNIFIER_SIZE", "11"))         # 放大镜采样格 n×n
MAGNIFIER_ZOOM = int(_env("MAGNIFIER_ZOOM", "14"))         # 每格放大倍数

# ---- 滚动截图 ----
SCROLL_INTERVAL_MS = int(_env("SCROLL_INTERVAL_MS", "900"))
SCROLL_MAX_FRAMES = int(_env("SCROLL_MAX_FRAMES", "12"))
SCROLL_WHEEL_NOTCHES = int(_env("SCROLL_WHEEL_NOTCHES", "5"))

# ---- 屏幕录像 ----
RECORD_FPS = int(_env("RECORD_FPS", "20"))                # 录制帧率

# ---- MinerU OCR ----
MINERU_API_TOKEN = _env("MINERU_API_TOKEN", "")
MINERU_API_BASE = _env("MINERU_API_BASE", "https://mineru.net/api/v4")


def ensure_save_dir() -> Path:
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    return SAVE_DIR
