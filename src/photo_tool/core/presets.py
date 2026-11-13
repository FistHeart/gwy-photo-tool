"""规格档位：输出尺寸与体积的硬性约束定义。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


@dataclass(frozen=True)
class Spec:
    """一套完整的输出规格。

    width / height 为目标输出尺寸（必须自身落在允许区间内）。
    min_kb / max_kb 为文件体积的硬下限与硬上限。
    band_lo_kb / band_hi_kb 为"舒适区"，优先把体积控制在该区间内，
    避免文件顶到 200KB 上限或在某些系统上被判为过大。
    """

    key: str
    label: str
    width: int
    height: int
    min_w: int = 400
    max_w: int = 600
    min_h: int = 600
    max_h: int = 800
    min_kb: int = 35
    max_kb: int = 200
    band_lo_kb: int = 60
    band_hi_kb: int = 120

    # ------------------------------------------------------------------ 派生属性
    @property
    def ratio(self) -> float:
        """宽高比（宽 / 高）。"""
        return self.width / self.height

    def contains(self, w: int, h: int) -> bool:
        return self.min_w <= w <= self.max_w and self.min_h <= h <= self.max_h

    def candidate_sizes(self) -> List[Tuple[int, int]]:
        """返回可尝试的输出尺寸，首位为目标尺寸。

        尺寸按体积需要向上/向下调整时使用，始终保持目标宽高比，
        且每个候选都严格落在允许像素区间内。
        """
        r = self.ratio
        out: List[Tuple[int, int]] = [(self.width, self.height)]

        # 更小的候选（体积超标时用）
        for w, h in ((round(self.min_h * r), self.min_h), (self.min_w, round(self.min_w / r))):
            if self.contains(w, h) and (w, h) not in out:
                out.append((w, h))
                break

        # 更大的候选（体积达不到下限时用）
        for w, h in ((round(self.max_h * r), self.max_h), (self.max_w, round(self.max_w / r))):
            if self.contains(w, h) and (w, h) not in out:
                out.append((w, h))
                break

        return out

    def describe(self) -> str:
        return (
            f"目标 {self.width}×{self.height}px ｜ "
            f"允许 {self.min_w}-{self.max_w}×{self.min_h}-{self.max_h}px ｜ "
            f"{self.min_kb}-{self.max_kb}KB"
        )


# 默认档位 —— 用户指定：400-600 × 600-800 px，35-200 KB
CUSTOM_SPEC = Spec(
    key="custom",
    label="报名照 480×640（400-600 × 600-800 / 35-200KB）",
    width=480,
    height=640,
)

# 国考官方口径（说明书：宽不低于 295、高不低于 413）
GWY_SPEC = Spec(
    key="gwy",
    label="国考（≥295×413 / 10-200KB）",
    width=413,
    height=579,
    min_w=295,
    max_w=600,
    min_h=413,
    max_h=800,
    min_kb=10,
    max_kb=200,
    band_lo_kb=20,
    band_hi_kb=80,
)

# 一寸照 295×413
ONE_INCH_SPEC = Spec(
    key="one_inch",
    label="一寸 295×413",
    width=295,
    height=413,
    min_w=260,
    max_w=400,
    min_h=380,
    max_h=560,
    min_kb=10,
    max_kb=200,
    band_lo_kb=20,
    band_hi_kb=70,
)

# 二寸照 413×579
TWO_INCH_SPEC = Spec(
    key="two_inch",
    label="二寸 413×579",
    width=413,
    height=579,
    min_w=380,
    max_w=500,
    min_h=530,
    max_h=700,
    min_kb=10,
    max_kb=200,
    band_lo_kb=25,
    band_hi_kb=90,
)

PRESETS: List[Spec] = [CUSTOM_SPEC, GWY_SPEC, ONE_INCH_SPEC, TWO_INCH_SPEC]
DEFAULT_SPEC = CUSTOM_SPEC


def spec_by_key(key: str) -> Spec:
    for s in PRESETS:
        if s.key == key:
            return s
    return DEFAULT_SPEC


def validate(w: int, h: int, size_bytes: int, spec: Spec) -> List[str]:
    """返回不合规项列表，空列表表示全部通过。"""
    problems: List[str] = []
    if not (spec.min_w <= w <= spec.max_w):
        problems.append(f"宽度 {w}px 不在 {spec.min_w}-{spec.max_w}px 之间")
    if not (spec.min_h <= h <= spec.max_h):
        problems.append(f"高度 {h}px 不在 {spec.min_h}-{spec.max_h}px 之间")
    kb = size_bytes / 1024.0
    if not (spec.min_kb <= kb <= spec.max_kb):
        problems.append(f"体积 {kb:.1f}KB 不在 {spec.min_kb}-{spec.max_kb}KB 之间")
    return problems
