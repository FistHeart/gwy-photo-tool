"""裁切画布：固定宽高比裁切框，支持拖动移动、八向缩放、滚轮调整大小。"""

from __future__ import annotations

from typing import Optional, Tuple

from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

ACCENT = QColor("#2563eb")
ACCENT_SOFT = QColor(37, 99, 235, 60)
DIM = QColor(15, 23, 42, 148)
FACE_COLOR = QColor("#16a34a")

HANDLE_HIT = 11.0
CORNER_SIZE = 13
MIN_CROP_PX = 40.0


def pil_to_pixmap(img: Image.Image) -> QPixmap:
    if img.mode != "RGB":
        img = img.convert("RGB")
    data = img.tobytes("raw", "RGB")
    qimg = QImage(data, img.width, img.height, img.width * 3, QImage.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


class CropCanvas(QWidget):
    """展示底图并维护一个宽高比锁定的裁切框（坐标为源图像素）。"""

    cropChanged = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._img: Optional[Image.Image] = None
        self._pix: Optional[QPixmap] = None
        self._face: Optional[Tuple[int, int, int, int]] = None
        self._crop = QRectF()
        self._aspect = 480 / 640
        self._view = QRectF()
        self._scale = 1.0
        self._drag_mode: Optional[str] = None
        self._press_rect = QRectF()
        self._press_pos = QPointF()
        self._hover: Optional[str] = None
        self.setMouseTracking(True)
        self.setMinimumSize(340, 460)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    # ------------------------------------------------------------------ 公共接口
    def has_image(self) -> bool:
        return self._pix is not None

    def set_image(self, img: Image.Image, face: Optional[Tuple[int, int, int, int]] = None) -> None:
        self._img = img
        self._pix = pil_to_pixmap(img)
        self._face = face
        self.update()

    def image_size(self) -> Tuple[int, int]:
        return self._img.size if self._img else (0, 0)

    def set_aspect(self, aspect: float) -> None:
        if abs(aspect - self._aspect) < 1e-6:
            return
        self._aspect = aspect
        if self._img is None:
            return
        r = QRectF(self._crop)
        cx, cy = r.center().x(), r.center().y()
        w = r.width()
        h = w / aspect
        self._set_crop(QRectF(cx - w / 2, cy - h / 2, w, h))

    def aspect(self) -> float:
        return self._aspect

    def crop_box(self) -> Tuple[float, float, float, float]:
        r = self._crop
        return (r.x(), r.y(), r.width(), r.height())

    def crop_pixels(self) -> Tuple[int, int]:
        return (int(round(self._crop.width())), int(round(self._crop.height())))

    def set_crop(self, rect: QRectF) -> None:
        self._set_crop(rect)

    # ------------------------------------------------------------------ 坐标换算
    def _update_view(self) -> None:
        if self._pix is None:
            return
        iw, ih = self._pix.width(), self._pix.height()
        pad = 26.0
        avail_w = max(50.0, self.width() - 2 * pad)
        avail_h = max(50.0, self.height() - 2 * pad)
        s = min(avail_w / iw, avail_h / ih)
        self._scale = s
        w, h = iw * s, ih * s
        self._view = QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _img_to_view(self, x: float, y: float) -> QPointF:
        return QPointF(self._view.x() + x * self._scale, self._view.y() + y * self._scale)

    def _rect_to_view(self, r: QRectF) -> QRectF:
        tl = self._img_to_view(r.x(), r.y())
        return QRectF(tl.x(), tl.y(), r.width() * self._scale, r.height() * self._scale)

    def _view_to_img(self, p: QPointF) -> QPointF:
        if self._scale <= 0:
            return QPointF()
        return QPointF((p.x() - self._view.x()) / self._scale, (p.y() - self._view.y()) / self._scale)

    # ------------------------------------------------------------------ 裁切框
    def _set_crop(self, rect: QRectF) -> None:
        if self._img is None:
            return
        iw, ih = self._img.size
        r = QRectF(rect)

        # 最小尺寸
        if r.width() < MIN_CROP_PX:
            r.setWidth(MIN_CROP_PX)
        r.setHeight(r.width() / self._aspect)
        if r.height() < MIN_CROP_PX:
            r.setHeight(MIN_CROP_PX)
            r.setWidth(r.height() * self._aspect)

        # 不超过图片
        if r.width() > iw:
            r.setWidth(iw)
            r.setHeight(r.width() / self._aspect)
        if r.height() > ih:
            r.setHeight(ih)
            r.setWidth(r.height() * self._aspect)
        if r.width() > iw:
            r.setWidth(iw)
        if r.height() > ih:
            r.setHeight(ih)

        # 平移入界
        if r.x() < 0:
            r.moveLeft(0)
        if r.y() < 0:
            r.moveTop(0)
        if r.x() + r.width() > iw:
            r.moveLeft(iw - r.width())
        if r.y() + r.height() > ih:
            r.moveTop(ih - r.height())

        self._crop = r
        self.update()
        self.cropChanged.emit()

    # ------------------------------------------------------------------ 手柄
    def _handle_points(self) -> dict:
        v = self._rect_to_view(self._crop)
        return {
            "tl": v.topLeft(),
            "tr": v.topRight(),
            "bl": v.bottomLeft(),
            "br": v.bottomRight(),
            "t": QPointF(v.center().x(), v.top()),
            "b": QPointF(v.center().x(), v.bottom()),
            "l": QPointF(v.left(), v.center().y()),
            "r": QPointF(v.right(), v.center().y()),
        }

    def _hit(self, pos: QPointF) -> Optional[str]:
        if not self.has_image():
            return None
        self._update_view()
        for name, p in self._handle_points().items():
            if abs(pos.x() - p.x()) <= HANDLE_HIT and abs(pos.y() - p.y()) <= HANDLE_HIT:
                return name
        if self._crop and self._rect_to_view(self._crop).contains(pos):
            return "move"
        return None

    # ------------------------------------------------------------------ 事件
    def mousePressEvent(self, e) -> None:
        if not self.has_image() or e.button() != Qt.LeftButton:
            return
        self._update_view()
        hit = self._hit(e.position())
        if hit is None:
            return
        self._drag_mode = hit
        self._press_rect = QRectF(self._crop)
        self._press_pos = self._view_to_img(e.position())

    def mouseMoveEvent(self, e) -> None:
        if not self.has_image():
            return
        self._update_view()
        pos = e.position()
        if self._drag_mode is None:
            hover = self._hit(pos)
            if hover != self._hover:
                self._hover = hover
                self.setCursor(self._cursor_for(hover))
            return

        p = self._view_to_img(pos)
        if self._drag_mode == "move":
            offset = self._press_pos - self._press_rect.topLeft()
            self._set_crop(QRectF(p - offset, self._press_rect.size()))
            return
        self._set_crop(self._resized_rect(self._drag_mode, p))

    def mouseReleaseEvent(self, e) -> None:
        self._drag_mode = None

    def leaveEvent(self, e) -> None:
        self._hover = None
        self.setCursor(Qt.ArrowCursor)

    def wheelEvent(self, e) -> None:
        if not self.has_image():
            return
        d = e.angleDelta().y()
        if not d:
            return
        self._update_view()
        f = 1.06 ** (d / 120.0)
        r = QRectF(self._crop)
        p = self._view_to_img(e.position())
        rx = (p.x() - r.x()) / max(r.width(), 1.0)
        ry = (p.y() - r.y()) / max(r.height(), 1.0)
        nw = r.width() * f
        nh = nw / self._aspect
        self._set_crop(QRectF(p.x() - nw * rx, p.y() - nh * ry, nw, nh))

    def _resized_rect(self, handle: str, p: QPointF) -> QRectF:
        r = self._press_rect
        a = self._aspect
        if handle in ("tl", "tr", "bl", "br"):
            ax = r.right() if "l" in handle else r.left()
            ay = r.bottom() if "t" in handle else r.top()
            w = abs(p.x() - ax)
            h = abs(p.y() - ay)
            if h * a > w:
                w = h * a
            h = w / a
            x = ax - w if "l" in handle else ax
            y = ay - h if "t" in handle else ay
            return QRectF(x, y, w, h)
        if handle in ("l", "r"):
            ax = r.right() if handle == "l" else r.left()
            w = abs(p.x() - ax)
            h = w / a
            cy = r.center().y()
            x = ax - w if handle == "l" else ax
            return QRectF(x, cy - h / 2, w, h)
        ay = r.bottom() if handle == "t" else r.top()
        h = abs(p.y() - ay)
        w = h * a
        cx = r.center().x()
        y = ay - h if handle == "t" else ay
        return QRectF(cx - w / 2, y, w, h)

    @staticmethod
    def _cursor_for(name: Optional[str]):
        return {
            "tl": Qt.SizeFDiagCursor,
            "br": Qt.SizeFDiagCursor,
            "tr": Qt.SizeBDiagCursor,
            "bl": Qt.SizeBDiagCursor,
            "l": Qt.SizeHorCursor,
            "r": Qt.SizeHorCursor,
            "t": Qt.SizeVerCursor,
            "b": Qt.SizeVerCursor,
            "move": Qt.SizeAllCursor,
        }.get(name, Qt.ArrowCursor)

    # ------------------------------------------------------------------ 绘制
    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.fillRect(self.rect(), QColor("#eef1f6"))

        if self._pix is None:
            p.setPen(QColor("#94a3b8"))
            f = QFont()
            f.setPointSize(11)
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter, "拖入照片，或点击「打开照片」\n支持 JPG / PNG / BMP / WEBP")
            return

        self._update_view()
        if self._crop.isNull():
            return

        p.drawPixmap(self._view, self._pix, QRectF(self._pix.rect()))

        crop_view = self._rect_to_view(self._crop)

        # 裁切框外压暗
        full = self._view
        p.save()
        p.setClipRect(full)
        path_regions = [
            QRectF(full.left(), full.top(), full.width(), crop_view.top() - full.top()),
            QRectF(full.left(), crop_view.bottom(), full.width(), full.bottom() - crop_view.bottom()),
            QRectF(full.left(), crop_view.top(), crop_view.left() - full.left(), crop_view.height()),
            QRectF(crop_view.right(), crop_view.top(), full.right() - crop_view.right(), crop_view.height()),
        ]
        for rg in path_regions:
            if rg.width() > 0 and rg.height() > 0:
                p.fillRect(rg, DIM)
        p.restore()

        # 人脸提示框
        if self._face:
            fx, fy, fw, fh = self._face
            face_view = self._rect_to_view(QRectF(fx, fy, fw, fh))
            pen = QPen(FACE_COLOR, 1.2, Qt.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(face_view, 4, 4)

        # 三分构图线
        pen = QPen(QColor(255, 255, 255, 90), 1)
        p.setPen(pen)
        for i in (1, 2):
            x = crop_view.left() + crop_view.width() * i / 3
            y = crop_view.top() + crop_view.height() * i / 3
            p.drawLine(QPointF(x, crop_view.top()), QPointF(x, crop_view.bottom()))
            p.drawLine(QPointF(crop_view.left(), y), QPointF(crop_view.right(), y))

        # 裁切框
        p.setPen(QPen(QColor(255, 255, 255, 235), 2))
        p.setBrush(Qt.NoBrush)
        p.drawRect(crop_view)

        # 手柄
        p.setPen(QPen(ACCENT, 1.6))
        p.setBrush(QColor("#ffffff"))
        pts = self._handle_points()
        for name in ("tl", "tr", "bl", "br"):
            pt = pts[name]
            p.drawRoundedRect(
                QRectF(pt.x() - CORNER_SIZE / 2, pt.y() - CORNER_SIZE / 2, CORNER_SIZE, CORNER_SIZE), 3, 3
            )
        for name in ("t", "b", "l", "r"):
            pt = pts[name]
            p.drawEllipse(pt, 4.5, 4.5)
