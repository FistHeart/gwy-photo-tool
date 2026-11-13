"""资源路径与常量。打包成 exe 后资源位于 sys._MEIPASS 下。"""

from __future__ import annotations

import sys
from pathlib import Path


def assets_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "photo_tool" / "assets"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[1] / "assets"


def asset(name: str) -> Path:
    return assets_dir() / name


APP_NAME = "报名照处理器"
APP_VERSION = "1.0.0"
DEFAULT_OUTPUT_NAME = "报名照片.jpg"

SUPPORTED_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff")
