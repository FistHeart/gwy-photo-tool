"""生成应用图标 assets/icon.ico（无需外部美术资源，纯代码绘制）。"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw

SIZE = 512


def draw_icon() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))

    # 背景：蓝色圆角方块 + 竖向渐变
    bg = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    grad = Image.new("RGB", (1, SIZE))
    top, bottom = (59, 130, 246), (29, 78, 216)
    for y in range(SIZE):
        t = y / (SIZE - 1)
        grad.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    grad = grad.resize((SIZE, SIZE))
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle((8, 8, SIZE - 8, SIZE - 8), radius=112, fill=255)
    bg.paste(grad, (0, 0), mask)
    img.alpha_composite(bg)

    d = ImageDraw.Draw(img)

    # 白色相纸（3:4）
    pw, ph = 236, 300
    px, py = (SIZE - pw) // 2, (SIZE - ph) // 2 - 16
    d.rounded_rectangle((px, py, px + pw, py + ph), radius=22, fill=(255, 255, 255, 255))

    # 相纸内的人像剪影
    cx = px + pw / 2
    d.ellipse((cx - 52, py + 62, cx + 52, py + 166), fill=(59, 130, 246, 255))
    d.rounded_rectangle((cx - 82, py + 186, cx + 82, py + 268), radius=44, fill=(59, 130, 246, 255))

    # 右下角"合规"对勾徽章
    bx, by, r = SIZE - 118, SIZE - 118, 74
    d.ellipse((bx - r, by - r, bx + r, by + r), fill=(22, 163, 74, 255), outline=(255, 255, 255, 255), width=12)
    d.line([(bx - 34, by + 2), (bx - 8, by + 30), (bx + 38, by - 28)], fill=(255, 255, 255, 255), width=17, joint="curve")

    return img


def main() -> None:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = os.path.join(here, "src", "photo_tool", "assets")
    os.makedirs(out_dir, exist_ok=True)

    icon = draw_icon()
    ico_path = os.path.join(out_dir, "icon.ico")
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    icon.save(ico_path, format="ICO", sizes=sizes)
    icon.resize((256, 256), Image.LANCZOS).save(os.path.join(out_dir, "icon.png"))
    print("icon →", ico_path)


if __name__ == "__main__":
    main()
