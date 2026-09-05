"""背景模板库：内置 31 个背景 + assets/templates/*.json 用户自定义。"""
from __future__ import annotations

import json

from jianying import config

TEMPLATE_DIR = config.ASSETS_DIR / "templates"


def _tpl(name: str, type_: str, colors: list[str] | None = None,
         angle: int = 135, padding: int = 48, radius: int = 16,
         blur: int = 40, opacity: int = 110) -> dict:
    t: dict = {"name": name, "type": type_, "padding": padding, "radius": radius}
    if colors:
        t["colors"] = colors
    if type_ == "gradient":
        t["angle"] = angle
    if blur:
        t["shadow"] = {"blur": blur, "opacity": opacity, "offset_y": 14}
    return t


# 渐变背景 ×22
_GRADIENTS: list[tuple[str, str, str, int]] = [
    ("海洋", "#2193b0", "#6dd5ed", 135),
    ("落日", "#f12711", "#f5af19", 135),
    ("极光", "#7f00ff", "#e100ff", 135),
    ("森林", "#134e5e", "#71b280", 135),
    ("午夜蓝", "#0f2027", "#2c5364", 135),
    ("桃气", "#ff9a9e", "#fecfef", 135),
    ("暮色", "#355c7d", "#c06c84", 135),
    ("青柠", "#d4fc79", "#96e6a1", 120),
    ("琥珀", "#f6d365", "#fda085", 135),
    ("蓝粉", "#4facfe", "#f093fb", 135),
    ("靛夜", "#2b5876", "#4e4376", 135),
    ("珊瑚", "#ff5f6d", "#ffc371", 135),
    ("薄荷", "#43e97b", "#38f9d7", 120),
    ("深海", "#4b6cb7", "#182848", 135),
    ("星紫", "#8e2de2", "#4a00e0", 135),
    ("青空", "#1c92d2", "#f2fcfe", 120),
    ("蜜桃", "#ee9ca7", "#ffdde1", 135),
    ("松石", "#136a8a", "#267871", 135),
    ("麦浪", "#eacda3", "#d6ae7b", 135),
    ("火烈鸟", "#f093fb", "#f5576c", 135),
    ("石墨", "#232526", "#414345", 135),
    ("金橙", "#f7971e", "#ffd200", 120),
]

# 纯色背景 ×8
_SOLIDS: list[tuple[str, str]] = [
    ("纯白", "#FFFFFF"),
    ("奶油", "#fdf6e3"),
    ("浅灰", "#EEF1F4"),
    ("雾蓝", "#D6E4F0"),
    ("樱粉", "#FDE8E9"),
    ("薄荷白", "#E3F6EF"),
    ("深空", "#1E2430"),
    ("曜石", "#101418"),
]

# 透明背景 ×1
_TRANSPARENT: list[tuple[str, int, int]] = [
    ("透明圆角", 24, 18),
]


def _backgrounds() -> list[dict]:
    out: list[dict] = []
    for name, pad, radius in _TRANSPARENT:
        out.append(_tpl(name, "transparent", padding=pad, radius=radius, blur=0))
    for name, color in _SOLIDS:
        out.append(_tpl(name, "solid", [color],
                        blur=36, opacity=90 if name in ("纯白", "奶油") else 110))
    for name, c1, c2, ang in _GRADIENTS:
        out.append(_tpl(name, "gradient", [c1, c2], angle=ang))
    return out


BUILTIN: list[dict] = [
    {"name": "无背景", "type": "none", "padding": 0, "radius": 0},
    *_backgrounds(),   # 1 透明 + 8 纯色 + 22 渐变 = 31 个背景
]


def load_templates() -> list[dict]:
    """内置模板 + 用户 JSON（同名以内置为准）。"""
    result = list(BUILTIN)
    names = {t["name"] for t in result}
    if TEMPLATE_DIR.exists():
        for f in sorted(TEMPLATE_DIR.glob("*.json")):
            try:
                tpl = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(tpl, dict) and tpl.get("name") and tpl.get("type"):
                    if tpl["name"] not in names:
                        result.append(tpl)
                        names.add(tpl["name"])
            except (json.JSONDecodeError, OSError):
                continue
    return result
