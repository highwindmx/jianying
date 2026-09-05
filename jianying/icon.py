"""程序图标：彩虹渐变圆角矩形 + 白色「剪」字。运行时生成，无资源文件依赖。"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

_RAINBOW = [
    (255, 59, 48),    # 红
    (255, 149, 0),    # 橙
    (255, 204, 0),    # 黄
    (52, 199, 89),    # 绿
    (0, 122, 255),    # 蓝
    (88, 86, 214),    # 靛
    (175, 82, 222),   # 紫
]


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for f in ("msyhbd.ttc", "msyh.ttc", "simhei.ttf", "arialbd.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_icon(size: int = 64) -> Image.Image:
    """彩虹渐变圆角矩形 + 居中白色「剪」字（带轻投影）。"""
    s = max(16, int(size))
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    # 彩虹横向渐变
    grad = Image.new("RGBA", (s, s))
    d = ImageDraw.Draw(grad)
    n = len(_RAINBOW)
    for x in range(s):
        t = x / max(1, s - 1) * (n - 1)
        i = min(int(t), n - 2)
        f = t - i
        c1, c2 = _RAINBOW[i], _RAINBOW[i + 1]
        col = tuple(round(a * (1 - f) + b * f) for a, b in zip(c1, c2)) + (255,)
        d.line([(x, 0), (x, s)], fill=col)

    # 圆角裁切
    mask = Image.new("L", (s, s), 0)
    dm = ImageDraw.Draw(mask)
    dm.rounded_rectangle([1, 1, s - 2, s - 2], radius=max(4, s // 5), fill=255)
    img.paste(grad, (0, 0), mask)

    # 白色「剪」字
    d = ImageDraw.Draw(img)
    font = _font(int(s * 0.74))
    bbox = d.textbbox((0, 0), "剪", font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (s - tw) // 2 - bbox[0]
    y = (s - th) // 2 - bbox[1]
    d.text((x + max(1, s // 60), y + max(1, s // 60)), "剪",
           font=font, fill=(0, 0, 0, 90))
    d.text((x, y), "剪", font=font, fill=(255, 255, 255, 255))
    return img


def qt_icon(size: int = 64):
    """QIcon 包装（托盘/窗口共用）。"""
    from PyQt6.QtGui import QIcon

    from jianying.utils import pil_to_qpixmap

    return QIcon(pil_to_qpixmap(make_icon(size)))
