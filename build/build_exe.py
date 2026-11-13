"""一键打包 Windows exe。

用法：
    python build/build_exe.py              # 单文件 exe（推荐分发）
    python build/build_exe.py --onedir     # 目录版（杀软误报时的备用形态）

产物：
    dist/报名照处理器.exe
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
ASSETS = SRC / "photo_tool" / "assets"
APP_NAME = "GWYPhotoTool"
CN_NAME = "报名照处理器"

EXCLUDES = [
    "tkinter",
    "unittest",
    "pydoc",
    "doctest",
    "matplotlib",
    "pandas",
    "scipy",
    "IPython",
    "pytest",
    "setuptools",
    "pip",
    "PySide6.QtNetwork",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtMultimedia",
    "PySide6.QtWebEngineCore",
    "PySide6.QtDBus",
]


def main() -> int:
    onedir = "--onedir" in sys.argv

    icon = ASSETS / "icon.ico"
    if not icon.exists():
        subprocess.run([sys.executable, str(ROOT / "build" / "make_icon.py")], check=True)

    for d in ("dist", ".pyi-build"):
        p = ROOT / d
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onefile" if not onedir else "--onedir",
        "--name",
        APP_NAME,
        "--icon",
        str(icon),
        "--add-data",
        f"{ASSETS}{';' if sys.platform == 'win32' else ':'}photo_tool/assets",
        "--paths",
        str(SRC),
        "--workpath",
        str(ROOT / ".pyi-build"),
        "--specpath",
        str(ROOT / ".pyi-build"),
        "--distpath",
        str(ROOT / "dist"),
    ]
    for m in EXCLUDES:
        cmd += ["--exclude-module", m]
    cmd.append(str(SRC / "app.py"))

    print(">>", " ".join(cmd[:12]), "...")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("打包失败")
        return result.returncode

    built = ROOT / "dist" / f"{APP_NAME}.exe"
    target = ROOT / "dist" / f"{CN_NAME}.exe"
    if built.exists():
        shutil.copyfile(built, target)
        size_mb = target.stat().st_size / (1024 * 1024)
        print(f"\n✓ 打包完成：{target}  ({size_mb:.1f} MB)")
    else:
        print("未找到产物，请检查上面的日志")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
