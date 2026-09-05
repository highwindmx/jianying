"""入口：python -m jianying 或 uv run jianying"""
from __future__ import annotations

import os
import sys

# 必须在 QApplication 创建前设置：截图工具坐标链（mss → 覆盖层 → 选区）
# 全部按 1:1 物理像素工作，禁用 Qt DPI 缩放避免混合 DPI 双屏错位
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
os.environ.setdefault("QT_SCALE_FACTOR", "1")

# 模块级持有：QApplication/JianyingApp 不可被 GC，否则托盘与热键静默失效
_APP = None
_JY = None


def _install_qt_msg_hook() -> None:
    """Qt 消息钩子。

    `QFont::setPointSize: Point size <= 0 (-1)` 是 Qt 在某些字体解析路径上的
    **无害警告**（Qt 内部会自行把 -1 钳到 1，不影响渲染）。我们在字体链路已全部
    用整数 pointSize 并加全局钳制（见 _install_font_guard），故此处直接抑制该条，
    避免污染控制台；其余 Qt 警告仍照常打印便于排查。
    """
    from PyQt6.QtCore import qInstallMessageHandler

    def handler(msg_type, context, message):
        if "setPointSize" in message:
            return   # 已知无害，抑制
        if message.strip():
            print(f"[Qt] {message}", file=sys.stderr, flush=True)

    qInstallMessageHandler(handler)


def _install_font_guard() -> None:
    """全局兜底：任何把 <=0 的点值传给 QFont 的调用（含 PyQt 内部）一律钳到 1。

    双保险——即使未来某处字体代码漏设，也不会再向 Qt 透传 -1 触发警告。
    返回是否成功打补丁（失败也不影响主流程）。
    """
    try:
        from PyQt6.QtGui import QFont

        _ps = QFont.setPointSize
        _psf = QFont.setPointSizeF

        def _g_ps(self, s):
            return _ps(self, 1 if s <= 0 else s)

        def _g_psf(self, s):
            return _psf(self, 1.0 if s <= 0 else s)

        QFont.setPointSize = _g_ps
        QFont.setPointSizeF = _g_psf
    except Exception:
        pass   # 打补丁失败不应阻断启动


def main() -> None:
    # 版本自检：打包后 `jianying --version` 可作为依赖收集是否完整的冒烟
    if "--version" in sys.argv:
        try:
            from importlib.metadata import version as _meta_ver
            ver = _meta_ver("jianying")
        except Exception:
            ver = "0.1.0"
        print(f"jianying {ver}")
        return

    # 冒烟模式：--test-grab 只测 mss 截屏并保存，不启动 GUI
    if "--test-grab" in sys.argv:
        _test_grab()
        return

    # 诊断模式：--test-dpi 对比 Qt 逻辑坐标 vs mss 物理坐标
    if "--test-dpi" in sys.argv:
        _test_dpi()
        return

    from PyQt6.QtWidgets import QApplication

    _install_qt_msg_hook()
    _install_font_guard()
    global _APP, _JY
    _APP = QApplication(sys.argv)
    _APP.setApplicationName("剪影")
    from jianying.icon import qt_icon
    _APP.setWindowIcon(qt_icon())
    _APP.setQuitOnLastWindowClosed(False)  # 托盘常驻：关窗不退出

    from jianying.app import JianyingApp

    _JY = JianyingApp()
    sys.exit(_APP.exec())


def _test_grab() -> None:
    """纯 mss 截屏冒烟（不依赖 Qt 屏幕会话，可在无 GUI 环境验证）。"""
    from pathlib import Path

    import mss
    from PyQt6.QtGui import QImage

    with mss.MSS() as sct:
        print("monitors:", sct.monitors)
        mon = sct.monitors[0]
        raw = sct.grab(mon)

    w, h = raw.size
    img = QImage(raw.bgra, w, h, w * 4, QImage.Format.Format_ARGB32).copy()
    out = Path("test_grab.png").resolve()
    img.save(str(out))
    print(f"virtual desktop: {w}x{h}")
    print(f"saved -> {out}")


_QAPP = None


def _test_dpi() -> None:
    """对比 Qt 逻辑坐标系与 mss 物理坐标系，定位覆盖层错位根因。"""
    from PyQt6.QtGui import QGuiApplication

    global _QAPP
    _QAPP = QGuiApplication(sys.argv)  # 持有引用，销毁后屏幕枚举失效
    print("=== Qt（逻辑坐标）===")
    for s in QGuiApplication.screens():
        print(f"  {s.name()}: geometry={s.geometry()} dpr={s.devicePixelRatio()} "
              f"physSize={s.size()} physGeo={s.geometry().x()},{s.geometry().y()} "
              f"virtual={s.virtualGeometry()}")
    ps = QGuiApplication.primaryScreen()
    print(f"  primary dpr = {ps.devicePixelRatio()}")

    print("=== mss（物理像素）===")
    import mss

    with mss.MSS() as sct:
        for i, m in enumerate(sct.monitors):
            print(f"  monitor[{i}]: left={m['left']} top={m['top']} "
                  f"w={m['width']} h={m['height']}")
    print("=== 判定 ===")
    qt_total_w = ps.virtualGeometry().width()
    mss_total_w = 0
    with mss.MSS() as sct:
        mss_total_w = sct.monitors[0]["width"]
    ratio = mss_total_w / qt_total_w if qt_total_w else 0
    print(f"  物理宽/逻辑宽 = {mss_total_w}/{qt_total_w} = {ratio:.3f}")
    if abs(ratio - ps.devicePixelRatio()) < 0.01:
        print("  ✓ 一致：DPR 换算无问题，覆盖层应与桌面严格对齐")
    else:
        print(f"  ✗ 不一致：存在混合 DPI（屏间缩放不同），"
              f"统一按主屏 dpr={ps.devicePixelRatio()} 换算会错位")


if __name__ == "__main__":
    main()
