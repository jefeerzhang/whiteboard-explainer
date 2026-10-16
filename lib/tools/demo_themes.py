#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""demo_themes.py — 一张图看完所有主题

同一段内容（一个"复利"小图解）在 5 套主题下各画一遍，横向拼成对比图。
用途：改主题表之后跑一次，肉眼确认配色与底色是否符合预期；
也用作向用户展示"到底能变成什么样"。

用法：
    python lib/tools/demo_themes.py --out out/themes.png
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "lib"))

import board_widgets as BW   # noqa: E402
import theme as TH           # noqa: E402

CW, CH = 420, 560            # 单格尺寸


def draw_scene(tag: str) -> Image.Image:
    """画一格：标题 + 人物 + 阶梯 + 语义符号 + 对话气泡。"""
    BW.set_canvas(CW, CH)
    img, d = BW.canvas()
    BW.title(d, tag, y=44, size=28)

    # 人物（线条色随主题）
    BW.person(d, 96, 330, 132)
    # 对话气泡（纯圆角框，避免尖角几何纠缠），文字压在框里
    d.rounded_rectangle([168, 190, 356, 244], radius=20,
                        fill=BW.WHITE, outline=BW.C("ink"), width=5)
    BW.text(d, 262, 217, "讲一下", 22, BW.C("ink"), True)

    # 阶梯（填充色随主题）
    BW.stairs(d, 320, 430, 3, xs=190, xe=CW - 36)

    # 语义符号：答案 / 正确 / 警示
    BW.star(d, 250, 486, 26)
    BW.check(d, 316, 486, 18)
    BW.bang(d, 366, 476, 34)

    # 文字（验证文字色随主题）
    BW.text(d, CW // 2, CH - 22, "同一段代码，不同底色", 17, BW.C("muted"))
    return img


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out/themes.png")
    ap.add_argument("--scale", type=int, default=2, help="放大倍数")
    args = ap.parse_args()

    keys = TH.names()
    cols = len(keys)
    gap = 16
    sheet = Image.new("RGB", (cols * CW + (cols + 1) * gap, CH + gap * 2), "#DDDDDD")
    for i, key in enumerate(keys):
        BW.set_theme(key)
        cell = draw_scene(TH.THEMES[key]["label"])
        sheet.paste(cell, (gap + i * (CW + gap), gap))
    if args.scale > 1:
        sheet = sheet.resize((sheet.width * args.scale, sheet.height * args.scale), Image.LANCZOS)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print(f"写出 {out}（{sheet.width}×{sheet.height}）")
    print("顺序：" + " | ".join(f"{k}={TH.THEMES[k]['paper']}" for k in keys))
    return 0


if __name__ == "__main__":
    sys.exit(main())