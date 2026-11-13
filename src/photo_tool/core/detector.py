"""人脸检测与证件照构图建议。

优先使用 OpenCV Haar 级联（模型随程序分发，纯本地、无网络）。
检测失败或 OpenCV 不可用时一律返回 None，由上层退化为居中裁切框，
绝不阻塞用户操作。
"""

from __future__ import annotations

from typing import Optional, Tuple

from PIL import Image

from .resources import asset

FaceBox = Tuple[int, int, int, int]  # x, y, w, h（源图像素）

_cascade = None
_cascade_tried = False


def _get_cascade():
    global _cascade, _cascade_tried
    if _cascade_tried:
        return _cascade
    _cascade_tried = True
    try:
        import cv2

        xml = asset("haarcascade_frontalface_alt2.xml")
        if xml.exists():
            c = cv2.CascadeClassifier(str(xml))
            if not c.empty():
                _cascade = c
    except Exception:
        _cascade = None
    return _cascade


def detect_face(img: Image.Image) -> Optional[FaceBox]:
    """返回画面中最大的人脸框（源图坐标），失败返回 None。"""
    cascade = _get_cascade()
    if cascade is None:
        return None
    try:
        import cv2
        import numpy as np
    except Exception:
        return None

    try:
        rgb = np.asarray(img.convert("RGB"))
        h, w = rgb.shape[:2]
        scale = 1.0
        if max(w, h) > 1000:  # 降采样加速
            scale = 1000.0 / max(w, h)
            small = cv2.resize(rgb, (max(1, int(w * scale)), max(1, int(h * scale))))
        else:
            small = rgb

        gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
        gray = cv2.equalizeHist(gray)

        min_side = max(40, int(min(gray.shape[:2]) * 0.12))
        faces = cascade.detectMultiScale(
            gray, scaleFactor=1.08, minNeighbors=5, minSize=(min_side, min_side)
        )
        if len(faces) == 0:
            faces = cascade.detectMultiScale(
                gray, scaleFactor=1.05, minNeighbors=2, minSize=(30, 30)
            )
        if len(faces) == 0:
            return None

        x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
        inv = 1.0 / scale
        return (
            int(x * inv),
            int(y * inv),
            int(fw * inv),
            int(fh * inv),
        )
    except Exception:
        return None


def clamp_rect(x: float, y: float, w: float, h: float, iw: int, ih: int, aspect: float) -> Tuple[float, float, float, float]:
    """把裁切框夹进图片内部，必要时等比缩小。"""
    w = min(w, iw)
    h = w / aspect
    if h > ih:
        h = ih
        w = h * aspect
    x = max(0.0, min(x, iw - w))
    y = max(0.0, min(y, ih - h))
    return x, y, w, h


def suggest_crop(
    img: Image.Image, face: Optional[FaceBox], aspect: float
) -> Tuple[float, float, float, float]:
    """根据人脸位置推导证件照构图裁切框（宽高比 aspect = 宽/高）。

    构图规则（国内证件照通行做法）：
      * 头顶到下巴约占画面高度 60-65%
      * 眼睛大致位于画面高度 38-42% 处
      * 人物水平居中
    """
    iw, ih = img.size

    if face is None:
        # 无检测结果：取图片中部 92% 高度的居中框
        h = ih * 0.92
        w = h * aspect
        if w > iw:
            w = iw
            h = w / aspect
        return clamp_rect((iw - w) / 2, (ih - h) / 2, w, h, iw, ih, aspect)

    fx, fy, fw, fh = face
    cx = fx + fw / 2.0

    head_h = fh * 1.62                 # 发顶 → 下巴的估算高度
    crop_h = head_h / 0.63             # 头高占画面 63%
    crop_w = crop_h * aspect
    eye_y = fy + fh * 0.40             # 眼睛在脸框内的位置
    top = eye_y - crop_h * 0.40        # 眼睛落在画面 40% 处
    left = cx - crop_w / 2.0

    # 太小的图允许裁切框超出一点，但仍然夹回图内
    return clamp_rect(left, top, crop_w, crop_h, iw, ih, aspect)


def centered_crop(img: Image.Image, aspect: float, fill: float = 0.92) -> Tuple[float, float, float, float]:
    iw, ih = img.size
    h = ih * fill
    w = h * aspect
    if w > iw:
        w = iw
        h = w / aspect
    return clamp_rect((iw - w) / 2, (ih - h) / 2, w, h, iw, ih, aspect)
