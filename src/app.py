"""程序入口。

正常双击 = 打开图形界面。
另提供两个仅供开发/CI 使用的隐藏参数（不影响普通使用）：
    --selftest [--report 文件]   无界面跑一遍核心算法，输出合规自检报告
    --smoke 图片 --shot 文件      无显示器环境下渲染界面并截图
"""

from __future__ import annotations

import os
import sys
import traceback

# 允许 `python src/app.py` 直接运行
_SRC = os.path.dirname(os.path.abspath(__file__))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from photo_tool.core.resources import APP_NAME, APP_VERSION  # noqa: E402


def _arg(argv, name: str, default=None):
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return argv[i + 1]
    return default


# --------------------------------------------------------------------------- selftest
def run_selftest(report_path: str) -> int:
    from PIL import Image, ImageDraw, ImageFilter

    from photo_tool.core import processor
    from photo_tool.core.detector import centered_crop
    from photo_tool.core.presets import PRESETS

    lines = [f"{APP_NAME} v{APP_VERSION} — 核心算法自检", ""]
    failures = []

    def sample(w: int, h: int, flat: bool = False) -> Image.Image:
        if flat:
            return Image.new("RGB", (w, h), (238, 242, 247))
        base = Image.linear_gradient("L").resize((w, h)).convert("RGB")
        noise = Image.effect_noise((w, h), 34).convert("RGB")
        img = Image.blend(base, noise, 0.35)
        d = ImageDraw.Draw(img)
        d.ellipse((w * 0.3, h * 0.18, w * 0.7, h * 0.62), fill=(226, 196, 172))
        d.ellipse((w * 0.4, h * 0.3, w * 0.45, h * 0.34), fill=(40, 40, 40))
        d.ellipse((w * 0.55, h * 0.3, w * 0.60, h * 0.34), fill=(40, 40, 40))
        d.rectangle((0, h * 0.78, w, h), fill=(32, 56, 120))
        return img.filter(ImageFilter.GaussianBlur(0.6))

    cases = [
        ("大图 4000×6000", sample(4000, 6000)),
        ("中等 1200×1600", sample(1200, 1600)),
        ("小图 600×800", sample(600, 800)),
        ("极简纯色 900×1200", sample(900, 1200, flat=True)),
    ]

    for spec in PRESETS:
        for name, img in cases:
            try:
                box = centered_crop(img, spec.ratio)
                res = processor.process(img, box, spec)
                kb = res.size_kb
                problems = []
                if not (spec.min_w <= res.width <= spec.max_w):
                    problems.append("宽超范围")
                if not (spec.min_h <= res.height <= spec.max_h):
                    problems.append("高超范围")
                if not (spec.min_kb <= kb <= spec.max_kb):
                    problems.append("体积超范围")
                tag = "PASS" if not problems else "FAIL " + ",".join(problems)
                if problems:
                    failures.append(f"{spec.key}/{name}: {problems}")
                lines.append(
                    f"[{tag}] {spec.key:<9} {name:<16} → {res.width}×{res.height}px "
                    f"{kb:6.1f}KB q={res.quality}"
                    + (f"  ({'; '.join(res.warnings)})" if res.warnings else "")
                )
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{spec.key}/{name}: {exc}")
                lines.append(f"[FAIL] {spec.key:<9} {name:<16} → {exc}")

    # 体积不足的极端场景：纯白小图
    try:
        flat = Image.new("RGB", (400, 400), (255, 255, 255))
        res = processor.process(flat, (0, 0, 400, 400), PRESETS[0])
        ok = PRESETS[0].min_kb <= res.size_kb <= PRESETS[0].max_kb
        lines.append(f"[{'PASS' if ok else 'FAIL'}] extreme 纯白 400×400 → {res.size_kb:.1f}KB")
        if not ok:
            failures.append("纯白图体积不达标")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"[WARN] extreme 纯白 400×400 → {exc}")
        failures.append(f"纯白图: {exc}")

    lines.append("")
    lines.append("结论：" + ("全部通过 ✅" if not failures else f"{len(failures)} 项未通过 ❌"))
    text = "\n".join(lines)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(text)
    try:
        print(text)
    except Exception:
        pass
    return 0 if not failures else 1


# --------------------------------------------------------------------------- smoke
def run_smoke(image: str | None, shot: str, offscreen: bool = False) -> int:
    if offscreen:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from photo_tool.ui.main_window import MainWindow

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setFont(QFont("Microsoft YaHei UI", 9))
    win = MainWindow()
    win.resize(1120, 760)
    if image and os.path.exists(image):
        win._load(image)  # noqa: SLF001
    win.show()
    app.processEvents()
    win.grab().save(shot)
    lines = [f"smoke ok → {shot}"]
    with open(shot + ".txt", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return 0


# --------------------------------------------------------------------------- main
def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)

    if "--selftest" in argv:
        report = _arg(argv, "--report", os.path.join(os.getcwd(), "selftest_report.txt"))
        try:
            return run_selftest(report)
        except Exception:
            with open(report, "w", encoding="utf-8") as f:
                f.write(traceback.format_exc())
            return 1

    if "--smoke" in argv:
        return run_smoke(
            _arg(argv, "--image"),
            _arg(argv, "--shot", os.path.join(os.getcwd(), "smoke.png")),
            offscreen="--offscreen" in argv,
        )

    from PySide6.QtGui import QFont, QIcon
    from PySide6.QtWidgets import QApplication

    from photo_tool.core.resources import asset
    from photo_tool.ui.main_window import MainWindow

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setFont(QFont("Microsoft YaHei UI", 9))
    icon = asset("icon.ico")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
