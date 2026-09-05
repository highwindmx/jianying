"""通用工具：颜色转换、剪贴板图片、QImage/PIL 互转。"""
from __future__ import annotations

from PIL import Image
from PyQt6.QtCore import QBuffer, QIODevice
from PyQt6.QtGui import QColor, QImage, QPixmap


def qimage_to_pil(img: QImage) -> Image.Image:
    """QImage → PIL RGBA（深拷贝，避免共享底层缓冲）。"""
    if img is None or img.isNull():
        raise ValueError("qimage_to_pil: 收到 null QImage（截图裁剪失败）")
    img = img.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = img.width(), img.height()
    buf = bytes(img.constBits().asarray(img.sizeInBytes()))
    return Image.frombytes("RGBA", (w, h), buf)


def pil_to_qimage(img: Image.Image) -> QImage:
    """PIL RGBA → QImage（拷贝数据，安全持有）。"""
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    w, h = img.size
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, w, h, w * 4, QImage.Format.Format_RGBA8888)
    return qimg.copy()  # 脱离 data 生命周期


def pil_to_qpixmap(img: Image.Image) -> QPixmap:
    return QPixmap.fromImage(pil_to_qimage(img))


def qpixmap_to_pil(pm: QPixmap) -> Image.Image:
    return qimage_to_pil(pm.toImage().copy())


def copy_image_to_clipboard(img: Image.Image) -> bool:
    """把 PIL 图片写入系统剪贴板（图片格式）。"""
    from PyQt6.QtWidgets import QApplication

    cb = QApplication.clipboard()
    qimg = pil_to_qimage(img)
    if qimg.isNull():
        return False
    cb.setImage(qimg)
    return True


def copy_text_to_clipboard(text: str) -> None:
    from PyQt6.QtWidgets import QApplication

    QApplication.clipboard().setText(text)


def qimage_png_bytes(img: QImage) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def hex_color(c) -> str:
    """QColor / (r,g,b) → '#RRGGBB'。"""
    if isinstance(c, QColor):
        return f"#{c.red():02X}{c.green():02X}{c.blue():02X}"
    r, g, b = c[0], c[1], c[2]
    return f"#{r:02X}{g:02X}{b:02X}"
