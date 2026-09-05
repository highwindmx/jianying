"""Pillow 美化引擎：圆角 / 阴影 / 纯色 / 渐变 / 透明背景。

模板结构（JSON）:
{
  "name": "海洋",
  "type": "gradient",            # none | solid | gradient | transparent
  "colors": ["#2193b0", "#6dd5ed"],
  "angle": 135,                  # 渐变角度，0=上→下，90=左→右
  "padding": 48,                 # 截图四周留白 px
  "radius": 16,                  # 截图圆角半径 px
  "shadow": {"blur": 40, "opacity": 110, "offset_y": 14}   # 可选
}
"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFilter

import numpy as np

PIL_RESAMPLE = Image.Resampling.LANCZOS


def _hex_to_rgb(s: str) -> tuple[int, int, int]:
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius=radius, fill=255)
    return m


def _linear_gradient(size: tuple[int, int], c1, c2, angle: float) -> Image.Image:
    """线性渐变。angle: 0=上→下, 90=左→右, 135=左上→右下。"""
    w, h = size
    theta = np.deg2rad(angle)
    dx, dy = np.sin(theta), np.cos(theta)
    # 各像素在渐变轴上的投影归一化到 0..1
    xs = np.linspace(0, 1, w, dtype=np.float32) * dx
    ys = np.linspace(0, 1, h, dtype=np.float32) * dy
    t = ys[:, None] + xs[None, :]
    t = (t - t.min()) / max(t.max() - t.min(), 1e-6)

    a = np.array(c1, dtype=np.float32)
    b = np.array(c2, dtype=np.float32)
    rgb = a[None, None, :] * (1 - t[..., None]) + b[None, None, :] * t[..., None]
    # rgb shape: (h, w, 3)
    img = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")
    return img.convert("RGBA")


def _make_shadow(img: Image.Image, blur: int, opacity: int,
                 offset_x: int, offset_y: int, margin: int) -> Image.Image:
    """生成带外沿边距的投影层（RGBA，黑色模糊，向右下偏移）。

    返回 (img + 2*margin) 尺寸图层；调用方以 (ox-margin, oy-margin) 合成。
    """
    W, H = img.width + margin * 2, img.height + margin * 2
    canvas = Image.new("RGBA", (W + blur * 2, H + blur * 2), (0, 0, 0, 0))
    black = Image.new("RGBA", img.size, (0, 0, 0, opacity))
    # 黑色矩形按 offset 偏移后用截图 alpha 蒙版贴入（保留圆角轮廓），再整体模糊
    canvas.paste(black, (margin + blur + offset_x, margin + blur + offset_y),
                 img.split()[3])
    canvas = canvas.filter(ImageFilter.GaussianBlur(blur))
    return canvas.crop((blur, blur, blur + W, blur + H))


def _parse_ratio(r) -> float | None:
    """"16:9" → 1.777；"auto"/None → None。"""
    if not r or str(r).strip().lower() in ("auto", "none", ""):
        return None
    try:
        a, b = str(r).split(":")
        return float(a) / float(b)
    except (ValueError, ZeroDivisionError):
        return None


def placement_offset(img_size: tuple[int, int], tpl: dict) -> tuple[int, int]:
    """截图在美化画布中的左上角偏移（供编辑器坐标映射）。"""
    w, h = img_size
    padding = int(tpl.get("padding", 48))
    W = w + padding * 2
    H = h + padding * 2
    target = _parse_ratio(tpl.get("ratio"))
    if target:
        if W / H < target:
            W = round(H * target)
        else:
            H = round(W / target)
    return ((W - w) // 2, (H - h) // 2)


def apply_template(img: Image.Image, tpl: dict) -> Image.Image:
    """按模板处理截图。输入输出均为 RGBA。type=none 时原样返回。

    tpl 可含 "ratio": "auto"|"16:9"|"4:3"|"3:2"|"1:1" —— 最终画布比例。
    """
    img = img.convert("RGBA")
    t = tpl.get("type", "none")
    if t == "none":
        return img

    padding = int(tpl.get("padding", 48))
    radius = int(tpl.get("radius", 16))
    shadow_cfg = tpl.get("shadow")

    # 1) 截图圆角
    rounded = Image.new("RGBA", img.size, (0, 0, 0, 0))
    rounded.paste(img, (0, 0), _rounded_mask(img.size, radius))

    # 2) 画布尺寸（含比例约束）
    W = img.width + padding * 2
    H = img.height + padding * 2
    target = _parse_ratio(tpl.get("ratio"))
    if target:
        if W / H < target:
            W = round(H * target)
        else:
            H = round(W / target)
    ox = (W - img.width) // 2
    oy = (H - img.height) // 2

    # 3) 背景
    if t == "transparent":
        canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        canvas.alpha_composite(rounded, (ox, oy))
        return canvas

    if t == "solid":
        colors = tpl.get("colors", ["#FFFFFF"])
        bg = Image.new("RGBA", (W, H), _hex_to_rgb(colors[0]) + (255,))
    elif t == "gradient":
        colors = tpl.get("colors", ["#2193b0", "#6dd5ed"])
        if len(colors) == 1:
            colors = colors * 2
        bg = _linear_gradient((W, H), _hex_to_rgb(colors[0]), _hex_to_rgb(colors[1]),
                              float(tpl.get("angle", 135)))
    else:
        raise ValueError(f"unknown template type: {t}")

    # 4) 阴影（贴在背景上、截图下方，默认向右下偏移）
    if shadow_cfg:
        blur = int(shadow_cfg.get("blur", 40))
        offset_y = int(shadow_cfg.get("offset_y", max(10, blur // 3)))
        offset_x = int(shadow_cfg.get("offset_x", max(6, offset_y // 2)))
        margin = blur * 2 + max(offset_x, offset_y)
        shadow = _make_shadow(
            rounded,
            blur=blur,
            opacity=int(shadow_cfg.get("opacity", 110)),
            offset_x=offset_x,
            offset_y=offset_y,
            margin=margin,
        )
        bg.alpha_composite(shadow, (ox - margin, oy - margin))

    bg.alpha_composite(rounded, (ox, oy))
    return bg
