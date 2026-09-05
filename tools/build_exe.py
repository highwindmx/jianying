"""PyInstaller 打包脚本（构建工具，放 tools/ 子目录）。

用法：
    uv run python tools/build_exe.py            # onedir：dist/jianying/jianying.exe（启动快）
    uv run python tools/build_exe.py --onefile  # 单文件：dist/jianying.exe（分发方便，启动略慢）
    uv run python tools/build_exe.py --distpath dist3   # 自定义输出目录（dist 被占用时用）

说明：
- --windowed：GUI 应用，不弹黑框控制台
- --add-data assets：内置背景模板目录（用户也可在 exe 同级放 assets/ 覆盖）
- --icon：exe 文件图标
- hidden-imports：补齐延迟导入的模块（录像/滚动/OCR）与可能漏收集的第三方包
"""
from __future__ import annotations

import sys
from pathlib import Path

import PyInstaller.__main__ as pyi

HERE = Path(__file__).resolve().parent.parent  # 项目根
ASSETS = HERE / "assets"
ICON = ASSETS / "icons" / "jianying.ico"
ENTRY = HERE / "jianying" / "__main__.py"

onefile = "--onefile" in sys.argv
mode = "--onefile" if onefile else "--onedir"

# --distpath <dir>：输出目录（默认 dist）。dist 被资源管理器/exe 占用导致
# PyInstaller 无法清理重建时，换一个全新目录即可。
distpath = "dist"
if "--distpath" in sys.argv:
    distpath = sys.argv[sys.argv.index("--distpath") + 1]

opts = [
    str(ENTRY),
    "--name", "jianying",
    "--windowed",                 # GUI 应用，不弹控制台
    "--noconfirm",
    "--clean",
    "--distpath", distpath,
    "--workpath", f"build_{Path(distpath).name}",
    "--hidden-import", "jianying.capture.recorder",
    "--hidden-import", "jianying.capture.scroll",
    "--hidden-import", "jianying.ocr",
    "--hidden-import", "cv2",
    "--hidden-import", "mss",
    "--hidden-import", "pynput",
    "--hidden-import", "pynput.keyboard._win32",
    "--hidden-import", "pynput.mouse._win32",
    "--hidden-import", "pystray",
    "--hidden-import", "PIL",
]
if ICON.exists():
    opts += ["--icon", str(ICON)]
if ASSETS.exists():
    # Windows 平台用 ';' 分隔源与目标
    opts += ["--add-data", f"{ASSETS};assets"]
opts.append(mode)

if __name__ == "__main__":
    print(f"[build] mode={mode} entry={ENTRY} distpath={distpath}")
    pyi.run(opts)
    print(f"\n[build] done. 产物在 {distpath}/")
