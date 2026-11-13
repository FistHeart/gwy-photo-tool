"""主窗口：左侧裁切画布，右侧规格与合规自检面板。"""

from __future__ import annotations

import os
import tempfile
from typing import Optional, Tuple

from PIL import Image, ImageOps
from PySide6.QtCore import QRectF, Qt, QThread, Signal
from PySide6.QtGui import QAction, QIcon, QImage, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..core import processor
from ..core.detector import centered_crop, detect_face, suggest_crop
from ..core.presets import DEFAULT_SPEC, PRESETS, Spec
from ..core.resources import APP_NAME, APP_VERSION, DEFAULT_OUTPUT_NAME, SUPPORTED_EXTS, asset
from .crop_canvas import CropCanvas

GREEN = "#16a34a"
AMBER = "#d97706"
RED = "#dc2626"
SLATE = "#475569"

RESULT_OK = (
    "color:#166534; background:#f0fdf4; border:1px solid #bbf7d0;"
    "border-radius:8px; padding:10px; font-size:12px;"
)
RESULT_WARN = (
    "color:#92400e; background:#fffbeb; border:1px solid #fde68a;"
    "border-radius:8px; padding:10px; font-size:12px;"
)

STYLE = """
QWidget { color: #0f172a; }
QMainWindow, #root { background: #f7f8fa; }
#header { background: #ffffff; border-bottom: 1px solid #e5e8ef; }
#title { font-size: 15px; font-weight: 600; }
#subtitle { color: #7c8798; font-size: 11px; }
#panel { background: #ffffff; border-left: 1px solid #e5e8ef; }
#sectionTitle { color: #64748b; font-size: 11px; font-weight: 600; letter-spacing: 1px; }
#hint { color: #7c8798; font-size: 11px; background: #ffffff; border-top: 1px solid #e5e8ef; }
#specInfo { color: #475569; font-size: 11px; }
QPushButton { background: #ffffff; border: 1px solid #d7dce5; border-radius: 7px;
              padding: 6px 12px; font-size: 12px; }
QPushButton:hover { background: #f1f5f9; }
QPushButton:pressed { background: #e2e8f0; }
QPushButton:disabled { color: #a8b2c1; background: #f8fafc; }
QPushButton#primary { background: #2563eb; border: 1px solid #2563eb; color: #ffffff;
                      font-weight: 600; }
QPushButton#primary:hover { background: #1d4ed8; }
QPushButton#primary:disabled { background: #93b4f6; border-color: #93b4f6; }
QComboBox { background: #ffffff; border: 1px solid #d7dce5; border-radius: 7px;
            padding: 6px 8px; font-size: 12px; }
QComboBox::drop-down { border: none; width: 18px; }
QStatusBar { background: #ffffff; color: #7c8798; font-size: 11px; }
"""


class ExportWorker(QThread):
    ok = Signal(object)
    fail = Signal(str)

    def __init__(self, img: Image.Image, box: Tuple[float, float, float, float], spec: Spec) -> None:
        super().__init__()
        self._img = img
        self._box = box
        self._spec = spec

    def run(self) -> None:  # pragma: no cover - 线程内执行
        try:
            self.ok.emit(processor.process(self._img, self._box, self._spec))
        except Exception as exc:  # noqa: BLE001
            self.fail.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.spec: Spec = DEFAULT_SPEC
        self._img: Optional[Image.Image] = None
        self._face: Optional[Tuple[int, int, int, int]] = None
        self._src_path: Optional[str] = None
        self._out_path: Optional[str] = None
        self._actual_kb: Optional[float] = None
        self._worker: Optional[ExportWorker] = None

        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(1120, 760)
        self.setMinimumSize(900, 620)
        icon_path = asset("icon.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._build_ui()
        self.setAcceptDrops(True)
        for seq, slot in (
            ("Ctrl+O", self._open_file),
            ("Ctrl+V", self._paste_clipboard),
            ("Ctrl+S", self._export),
        ):
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(slot)
        self._refresh_status()

    # ------------------------------------------------------------------ 界面
    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- 左侧
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(0)

        header = QFrame()
        header.setObjectName("header")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(18, 12, 18, 12)

        titles = QVBoxLayout()
        titles.setSpacing(1)
        t = QLabel(APP_NAME)
        t.setObjectName("title")
        s = QLabel("裁切构图 → 自动锁定像素与体积 → 导出可直接上传")
        s.setObjectName("subtitle")
        titles.addWidget(t)
        titles.addWidget(s)
        hl.addLayout(titles)
        hl.addStretch(1)

        self.btn_open = QPushButton("打开照片")
        self.btn_open.setObjectName("primary")
        self.btn_open.clicked.connect(self._open_file)
        self.btn_rotate = QPushButton("旋转 90°")
        self.btn_rotate.clicked.connect(self._rotate)
        self.btn_flip = QPushButton("水平翻转")
        self.btn_flip.clicked.connect(self._flip)
        self.btn_reset = QPushButton("重置裁切")
        self.btn_reset.clicked.connect(self._reset_crop)
        for b in (self.btn_rotate, self.btn_flip, self.btn_reset):
            b.setEnabled(False)
        hl.addWidget(self.btn_open)
        hl.addSpacing(6)
        hl.addWidget(self.btn_rotate)
        hl.addWidget(self.btn_flip)
        hl.addWidget(self.btn_reset)
        left_lay.addWidget(header)

        self.canvas = CropCanvas()
        self.canvas.cropChanged.connect(self._refresh_status)
        left_lay.addWidget(self.canvas, 1)

        hint = QLabel(
            "　拖拽四角或边中点调整裁切框　·　拖框内移动　·　滚轮缩放框　·　Ctrl+V 粘贴　·　Ctrl+S 导出"
        )
        hint.setObjectName("hint")
        hint.setFixedHeight(30)
        hint.setAlignment(Qt.AlignVCenter)
        left_lay.addWidget(hint)
        outer.addWidget(left, 1)

        # ---- 右侧面板
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setFixedWidth(330)
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(20, 18, 20, 18)
        pl.setSpacing(10)

        sec1 = QLabel("输出规格")
        sec1.setObjectName("sectionTitle")
        pl.addWidget(sec1)

        self.combo = QComboBox()
        for s in PRESETS:
            self.combo.addItem(s.label, s.key)
        self.combo.currentIndexChanged.connect(self._on_spec_changed)
        pl.addWidget(self.combo)

        self.lbl_spec = QLabel("")
        self.lbl_spec.setObjectName("specInfo")
        self.lbl_spec.setWordWrap(True)
        pl.addWidget(self.lbl_spec)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color:#e5e8ef;")
        pl.addWidget(line)

        sec2 = QLabel("合规自检")
        sec2.setObjectName("sectionTitle")
        pl.addWidget(sec2)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(9)
        self.status_labels = {}
        rows = [("size", "尺寸"), ("kb", "体积"), ("ratio", "比例"), ("sharp", "清晰度")]
        for i, (key, name) in enumerate(rows):
            n = QLabel(name)
            n.setStyleSheet(f"color:{SLATE}; font-size:12px;")
            v = QLabel("—")
            v.setStyleSheet("font-size:12px;")
            v.setWordWrap(True)
            v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(n, i, 0)
            grid.addWidget(v, i, 1)
            self.status_labels[key] = v
        grid.setColumnStretch(1, 1)
        pl.addLayout(grid)

        pl.addStretch(1)

        self.btn_export = QPushButton("导出报名照")
        self.btn_export.setObjectName("primary")
        self.btn_export.setFixedHeight(44)
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self._export)
        pl.addWidget(self.btn_export)

        self.lbl_result = QLabel("")
        self.lbl_result.setWordWrap(True)
        self.lbl_result.setVisible(False)
        self.lbl_result.setStyleSheet(RESULT_OK)
        pl.addWidget(self.lbl_result)

        self.btn_folder = QPushButton("打开输出文件夹")
        self.btn_folder.setVisible(False)
        self.btn_folder.clicked.connect(self._open_folder)
        pl.addWidget(self.btn_folder)

        outer.addWidget(panel)
        self.setCentralWidget(root)
        self.setStyleSheet(STYLE)
        self.statusBar().showMessage("就绪　·　拖入照片即可开始")

    # ------------------------------------------------------------------ 载入
    def _open_file(self) -> None:
        exts = " ".join(f"*{e}" for e in SUPPORTED_EXTS)
        path, _ = QFileDialog.getOpenFileName(self, "选择照片", "", f"图片文件 ({exts})")
        if path:
            self._load(path)

    def _load(self, path: str) -> None:
        try:
            img = processor.load_image(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "打不开这张照片", f"无法读取：{path}\n\n{exc}")
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._face = detect_face(img)
        finally:
            QApplication.restoreOverrideCursor()

        self._img = img
        self._src_path = path
        self._out_path = None
        self._actual_kb = None
        self.lbl_result.setVisible(False)
        self.btn_folder.setVisible(False)

        self.canvas.set_image(img, self._face)
        self.canvas.set_aspect(self.spec.ratio)
        self.canvas.set_crop(QRectF(*suggest_crop(img, self._face, self.spec.ratio)))

        for b in (self.btn_rotate, self.btn_flip, self.btn_reset, self.btn_export):
            b.setEnabled(True)

        face_txt = "已识别到人脸，已按证件照构图推荐裁切框" if self._face else "未识别人脸，已按居中构图推荐（可手动调整）"
        self.statusBar().showMessage(f"已载入 {os.path.basename(path)}　·　{img.width}×{img.height}px　·　{face_txt}")
        self._refresh_status()

    def _paste_clipboard(self) -> None:
        cb = QApplication.clipboard()
        urls = [u for u in (cb.mimeData().urls() if cb.mimeData() else []) if u.isLocalFile()]
        for u in urls:
            if u.toLocalFile().lower().endswith(SUPPORTED_EXTS):
                self._load(u.toLocalFile())
                return
        qi = cb.image()
        if qi.isNull():
            self.statusBar().showMessage("剪贴板里没有图片")
            return
        qi = qi.convertToFormat(QImage.Format_RGB888)
        w, h, bpl = qi.width(), qi.height(), qi.bytesPerLine()
        pil = Image.frombuffer("RGB", (w, h), bytes(qi.constBits()), "raw", "RGB", bpl, 1)
        self._load_from_image(pil, "剪贴板图片")

    def _load_from_image(self, img: Image.Image, name: str) -> None:
        tmp = os.path.join(tempfile.gettempdir(), "photo_tool_paste.jpg")
        try:
            img.save(tmp, "JPEG", quality=95)
            self._load(tmp)
        except Exception:
            self._img = img
            self._src_path = None
            self.canvas.set_image(img, None)
            self.canvas.set_aspect(self.spec.ratio)
            self.canvas.set_crop(QRectF(*centered_crop(img, self.spec.ratio)))
            for b in (self.btn_rotate, self.btn_flip, self.btn_reset, self.btn_export):
                b.setEnabled(True)
            self.statusBar().showMessage(f"已载入{name}")
            self._refresh_status()

    # ------------------------------------------------------------------ 编辑
    def _rotate(self) -> None:
        if self._img is None:
            return
        self._img = self._img.rotate(-90, expand=True)
        self._face = detect_face(self._img)
        self.canvas.set_image(self._img, self._face)
        self.canvas.set_aspect(self.spec.ratio)
        self.canvas.set_crop(QRectF(*suggest_crop(self._img, self._face, self.spec.ratio)))
        self._refresh_status()

    def _flip(self) -> None:
        if self._img is None:
            return
        self._img = ImageOps.mirror(self._img)
        self._face = detect_face(self._img)
        self.canvas.set_image(self._img, self._face)
        self.canvas.set_aspect(self.spec.ratio)
        self.canvas.set_crop(QRectF(*suggest_crop(self._img, self._face, self.spec.ratio)))
        self._refresh_status()

    def _reset_crop(self) -> None:
        if self._img is None:
            return
        self.canvas.set_crop(QRectF(*suggest_crop(self._img, self._face, self.spec.ratio)))

    def _on_spec_changed(self, index: int) -> None:
        self.spec = PRESETS[index]
        self.canvas.set_aspect(self.spec.ratio)
        self._actual_kb = None
        self._refresh_status()
        if self._img is not None:
            self.canvas.set_crop(QRectF(*suggest_crop(self._img, self._face, self.spec.ratio)))

    # ------------------------------------------------------------------ 状态
    def _set_row(self, key: str, text: str, color: str) -> None:
        lbl = self.status_labels[key]
        lbl.setText(text)
        lbl.setStyleSheet(f"font-size:12px; color:{color};")

    def _refresh_status(self) -> None:
        spec = self.spec
        self.lbl_spec.setText(spec.describe())
        self._set_row("size", f"{spec.width} × {spec.height} px", GREEN)
        self._set_row("ratio", f"{spec.ratio:.3f} : 1", GREEN)

        if self._actual_kb is not None:
            self._set_row("kb", f"{self._actual_kb:.1f} KB", GREEN)
        else:
            self._set_row("kb", f"导出时锁定 {spec.min_kb}-{spec.max_kb} KB", SLATE)

        if self._img is None:
            self._set_row("sharp", "—", SLATE)
            return

        cw, ch = self.canvas.crop_pixels()
        if cw >= spec.width and ch >= spec.height:
            self._set_row("sharp", f"原始 {cw}×{ch} px 充足", GREEN)
        else:
            ratio = spec.width / max(cw, 1)
            self._set_row("sharp", f"{cw}×{ch} px，放大 {ratio:.1f}×", AMBER)

    # ------------------------------------------------------------------ 导出
    def _export(self) -> None:
        if self._img is None:
            QMessageBox.information(self, "还没有照片", "请先打开或拖入一张照片。")
            return
        if self._worker is not None and self._worker.isRunning():
            return

        base_dir = os.path.dirname(self._src_path) if self._src_path else os.path.expanduser("~/Desktop")
        default = os.path.join(base_dir, DEFAULT_OUTPUT_NAME)
        path, _ = QFileDialog.getSaveFileName(self, "保存报名照", default, "JPEG 图片 (*.jpg)")
        if not path:
            return
        if not path.lower().endswith((".jpg", ".jpeg")):
            path += ".jpg"

        self.btn_export.setEnabled(False)
        self.btn_export.setText("处理中…")
        QApplication.setOverrideCursor(Qt.WaitCursor)

        self._worker = ExportWorker(self._img, self.canvas.crop_box(), self.spec)
        self._worker.ok.connect(lambda res: self._on_export_ok(res, path))
        self._worker.fail.connect(self._on_export_fail)
        self._worker.start()

    def _reset_export_button(self) -> None:
        QApplication.restoreOverrideCursor()
        self.btn_export.setEnabled(self._img is not None)
        self.btn_export.setText("导出报名照")

    def _on_export_ok(self, res, path: str) -> None:
        try:
            processor.save_bytes(res.data, path)
        except Exception as exc:  # noqa: BLE001
            self._on_export_fail(f"写入文件失败：{exc}")
            return
        self._reset_export_button()

        self._out_path = path
        self._actual_kb = res.size_kb
        self._refresh_status()

        msg = (
            f"已导出 {os.path.basename(path)}\n"
            f"{res.width}×{res.height}px　·　{res.size_kb:.1f} KB　·　JPEG q={res.quality}\n"
            f"三项指标全部合规 ✅"
        )
        if res.warnings:
            msg += "\n\n提示：" + "；".join(res.warnings)
            self.lbl_result.setStyleSheet(RESULT_WARN)
        else:
            self.lbl_result.setStyleSheet(RESULT_OK)
        self.lbl_result.setText(msg)
        self.lbl_result.setVisible(True)
        self.btn_folder.setVisible(True)
        self.statusBar().showMessage(f"导出成功：{path}")

    def _on_export_fail(self, message: str) -> None:
        self._reset_export_button()
        QMessageBox.critical(self, "导出失败", message)

    def _open_folder(self) -> None:
        if not self._out_path:
            return
        folder = os.path.dirname(self._out_path)
        try:
            os.startfile(folder)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            QMessageBox.information(self, "提示", f"无法打开文件夹：{exc}\n路径：{folder}")

    # ------------------------------------------------------------------ 拖拽
    def dragEnterEvent(self, e) -> None:
        if self._urls_ok(e.mimeData()):
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        for path in [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]:
            if path.lower().endswith(SUPPORTED_EXTS):
                self._load(path)
                e.acceptProposedAction()
                return

    @staticmethod
    def _urls_ok(mime) -> bool:
        if mime is None or not mime.hasUrls():
            return False
        return any(
            u.isLocalFile() and u.toLocalFile().lower().endswith(SUPPORTED_EXTS) for u in mime.urls()
        )
