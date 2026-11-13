"""核心算法单元测试（仅依赖标准库 unittest）。

运行：
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

from photo_tool.core import processor  # noqa: E402
from photo_tool.core.detector import centered_crop, suggest_crop  # noqa: E402
from photo_tool.core.presets import CUSTOM_SPEC, PRESETS, validate  # noqa: E402


def make_photo(w: int = 1200, h: int = 1600) -> Image.Image:
    base = Image.linear_gradient("L").resize((w, h)).convert("RGB")
    noise = Image.effect_noise((w, h), 40).convert("RGB")
    img = Image.blend(base, noise, 0.4)
    d = ImageDraw.Draw(img)
    d.ellipse((w * 0.32, h * 0.2, w * 0.68, h * 0.6), fill=(229, 200, 176))
    d.rectangle((0, h * 0.8, w, h), fill=(30, 58, 122))
    return img.filter(ImageFilter.GaussianBlur(0.5))


class TestSpec(unittest.TestCase):
    def test_candidate_sizes_stay_in_bounds(self) -> None:
        for spec in PRESETS:
            for w, h in spec.candidate_sizes():
                self.assertTrue(spec.contains(w, h), f"{spec.key} 候选尺寸 {w}×{h} 越界")

    def test_target_size_in_bounds(self) -> None:
        for spec in PRESETS:
            self.assertTrue(spec.contains(spec.width, spec.height), f"{spec.key} 目标尺寸越界")


class TestProcessor(unittest.TestCase):
    def test_all_presets_meet_hard_limits(self) -> None:
        img = make_photo()
        for spec in PRESETS:
            box = centered_crop(img, spec.ratio)
            res = processor.process(img, box, spec)
            self.assertEqual(validate(res.width, res.height, res.size_bytes, spec), [], spec.key)
            self.assertLessEqual(res.size_bytes, spec.max_kb * 1024)
            self.assertGreaterEqual(res.size_bytes, spec.min_kb * 1024)

    def test_custom_spec_exact_requirements(self) -> None:
        """用户三项硬指标：400-600 宽 / 600-800 高 / 35-200KB。"""
        img = make_photo(1600, 2133)
        res = processor.process(img, centered_crop(img, CUSTOM_SPEC.ratio), CUSTOM_SPEC)
        self.assertTrue(400 <= res.width <= 600, res.width)
        self.assertTrue(600 <= res.height <= 800, res.height)
        self.assertTrue(35 * 1024 <= res.size_bytes <= 200 * 1024, res.size_kb)

    def test_flat_image_reaches_size_floor(self) -> None:
        """纯色图（细节极少）也必须跨过体积下限。"""
        flat = Image.new("RGB", (900, 1200), (245, 247, 250))
        res = processor.process(flat, centered_crop(flat, CUSTOM_SPEC.ratio), CUSTOM_SPEC)
        self.assertGreaterEqual(res.size_bytes, CUSTOM_SPEC.min_kb * 1024)
        self.assertLessEqual(res.size_bytes, CUSTOM_SPEC.max_kb * 1024)

    def test_small_source_upscaled_with_warning(self) -> None:
        small = make_photo(420, 560)
        res = processor.process(small, (0, 0, 420, 560), CUSTOM_SPEC)
        self.assertEqual(validate(res.width, res.height, res.size_bytes, CUSTOM_SPEC), [])
        self.assertTrue(res.warnings, "放大处理应给出清晰度提示")

    def test_output_is_valid_jpeg(self) -> None:
        img = make_photo(900, 1200)
        res = processor.process(img, centered_crop(img, CUSTOM_SPEC.ratio), CUSTOM_SPEC)
        self.assertEqual(res.data[:2], b"\xff\xd8")
        self.assertEqual(res.data[-2:], b"\xff\xd9")

    def test_crop_clamped_to_image(self) -> None:
        img = make_photo(800, 800)
        out = processor.crop_image(img, (-500, -500, 3000, 3000))
        self.assertLessEqual(out.width, 800)
        self.assertLessEqual(out.height, 800)


class TestDetector(unittest.TestCase):
    def test_suggestion_without_face_is_inside_image(self) -> None:
        img = make_photo(1000, 1400)
        x, y, w, h = suggest_crop(img, None, 0.75)
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)
        self.assertLessEqual(x + w, 1000 + 0.5)
        self.assertLessEqual(y + h, 1400 + 0.5)
        self.assertAlmostEqual(w / h, 0.75, places=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
