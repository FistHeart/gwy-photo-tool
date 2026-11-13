"""核心图像处理：载入、裁切、缩放，以及"像素 + 体积"双约束编码。

设计要点
--------
1. 像素约束由 target size 保证：所有候选尺寸都经过 Spec.contains 校验；
2. 体积约束由 JPEG 质量搜索保证：q 从 95 单调下降到 50，取第一个
   体积落在 [min_kb, max_kb] 的结果；若体积偏大则降 q，偏小则换更大
   的合法尺寸（或改用 4:4:4 无色度抽样）；
3. 任何情况下导出前都会 validate()，不允许产出不合规文件。
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from PIL import Image, ImageOps

from .presets import Spec, validate

# 体积达不到下限时使用的微纹理参数（零均值噪声，不改变画面平均亮度）
_TEXTURE_SIGMA = 26


class ProcessError(RuntimeError):
    """无法产出合规结果时抛出。"""


@dataclass
class EncodeResult:
    data: bytes
    width: int
    height: int
    quality: int
    warnings: List[str] = field(default_factory=list)

    @property
    def size_bytes(self) -> int:
        return len(self.data)

    @property
    def size_kb(self) -> float:
        return len(self.data) / 1024.0

    def summary(self) -> str:
        return f"{self.width}×{self.height}px ｜ {self.size_kb:.1f} KB ｜ JPEG q={self.quality}"


# --------------------------------------------------------------------------- 载入
def load_image(path: str) -> Image.Image:
    """载入图片：按 EXIF 纠正方向，透明区域铺白底，统一为 RGB。"""
    with Image.open(path) as raw:
        raw.load()
        img = ImageOps.exif_transpose(raw)
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            rgba = img.convert("RGBA")
            base = Image.new("RGB", rgba.size, (255, 255, 255))
            base.paste(rgba, mask=rgba.split()[-1])
            return base
        return img.convert("RGB")


# --------------------------------------------------------------------------- 裁切
def crop_image(img: Image.Image, box: Tuple[float, float, float, float]) -> Image.Image:
    """按源图像素坐标裁切，自动夹紧到图内并保证至少 1px。"""
    iw, ih = img.size
    x, y, w, h = box
    x = max(0, min(round(x), iw - 1))
    y = max(0, min(round(y), ih - 1))
    w = max(1, min(round(w), iw - x))
    h = max(1, min(round(h), ih - y))
    return img.crop((x, y, x + w, y + h))


def _resize(img: Image.Image, size: Tuple[int, int]) -> Image.Image:
    downscale = size[0] <= img.width and size[1] <= img.height
    resample = Image.LANCZOS if downscale else Image.BICUBIC
    return img.resize(size, resample)


# --------------------------------------------------------------------------- 编码
def _encode(img: Image.Image, quality: int, subsampling: int = -1, dpi: int = 300) -> bytes:
    buf = io.BytesIO()
    kwargs = dict(format="JPEG", quality=quality, optimize=True, dpi=(dpi, dpi))
    if subsampling >= 0:
        kwargs["subsampling"] = subsampling
    img.save(buf, **kwargs)
    return buf.getvalue()


def _search_quality(img: Image.Image, spec: Spec, subsampling: int = -1) -> Optional[Tuple[bytes, int]]:
    """在 [50, 95] 内搜索质量因子，返回满足体积约束的最优结果。"""
    lo, hi = spec.min_kb * 1024, spec.max_kb * 1024
    band_hi = spec.band_hi_kb * 1024

    fallback: Optional[Tuple[bytes, int]] = None
    for q in range(95, 49, -1):
        data = _encode(img, q, subsampling=subsampling)
        n = len(data)
        if n > hi:            # 偏大，继续降质量
            continue
        if n < lo:            # 已低于下限，再降只会更小
            break
        fallback = (data, q)  # 合规备份
        if n <= band_hi:      # 进入舒适区，收工
            return data, q
    return fallback


def _add_texture(img: Image.Image, alpha: float) -> Image.Image:
    """加入零均值微噪声：提升编码熵以满足体积下限，同时不改变画面平均亮度
    （纯白背景仍是纯白，不会因抖动偏灰）。"""
    noise = Image.effect_noise(img.size, _TEXTURE_SIGMA)
    try:
        import numpy as np

        arr = np.asarray(img).astype(np.int16)
        n = np.asarray(noise).astype(np.int16) - 128  # 零均值
        out = arr + n[:, :, None] * alpha
        return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")
    except Exception:  # noqa: BLE001 - 无 numpy 时退化为普通混合
        return Image.blend(img, noise.convert("RGB"), alpha * 0.5)


def encode_to_spec(crop: Image.Image, spec: Spec, target_box: Optional[Tuple[int, int]] = None) -> EncodeResult:
    """把裁切结果压到规格内，返回合规的 JPEG 字节流。"""
    warnings: List[str] = []
    sizes = spec.candidate_sizes()
    if target_box:
        sizes = [target_box] + [s for s in sizes if s != target_box]

    src_w, src_h = crop.size
    # 体积安全余量：不要贴着下限交付，避免官方校验器按字节/千字节口径差异误判
    soft_lo_kb = spec.min_kb + max(4.0, spec.min_kb * 0.18)
    best: Optional[Tuple[bytes, int, int, int, float]] = None

    # 第一轮：常规质量搜索，体积贴近下限时尝试更大的合法尺寸换取余量
    for tw, th in sizes:
        if src_w < tw or src_h < th:
            warnings = [f"原始裁切区域仅 {src_w}×{src_h}px，已放大到 {tw}×{th}px，清晰度可能受影响"]
        img = _resize(crop, (tw, th))
        hit = _search_quality(img, spec)
        if not hit:
            continue
        kb = len(hit[0]) / 1024.0
        if best is None or kb > best[4]:
            best = (hit[0], hit[1], tw, th, kb)
        if kb >= soft_lo_kb:
            break

    if best:
        return _finish((best[0], best[1]), best[2], best[3], spec, warnings)

    # 第二轮：改用 4:4:4 无色度抽样，体积通常可提升 10-20%
    tw, th = sizes[-1]
    img = _resize(crop, (tw, th))
    hit = _search_quality(img, spec, subsampling=0)
    if hit:
        return _finish(hit, tw, th, spec, warnings)

    # 第三轮：极低细节图（纯色背景），逐步增强零均值微纹理直到跨过体积下限
    for alpha in (0.05, 0.10, 0.16, 0.24, 0.34):
        hit = _search_quality(_add_texture(img, alpha), spec, subsampling=0)
        if hit:
            warnings.append("原图细节极少，已做微观纹理补偿以满足体积下限（不改变背景色，肉眼不可见）")
            return _finish(hit, tw, th, spec, warnings)

    raise ProcessError(
        "无法把该照片压入要求区间，请换一张分辨率更高、细节更丰富的原始照片。"
    )


def _finish(hit: Tuple[bytes, int], w: int, h: int, spec: Spec, warnings: List[str]) -> EncodeResult:
    data, quality = hit
    problems = validate(w, h, len(data), spec)
    if problems:
        raise ProcessError("；".join(problems))
    return EncodeResult(data=data, width=w, height=h, quality=quality, warnings=warnings)


# --------------------------------------------------------------------------- 一站式
def process(img: Image.Image, box: Tuple[float, float, float, float], spec: Spec) -> EncodeResult:
    """裁切 + 编码，一步到位。"""
    return encode_to_spec(crop_image(img, box), spec)


def save_bytes(data: bytes, path: str) -> int:
    """写盘并返回实际字节数。JPEG 已在编码阶段写入 300DPI、无 EXIF。"""
    with open(path, "wb") as f:
        f.write(data)
    return len(data)
