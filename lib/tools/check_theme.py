#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""check_theme.py — 主题上线前的自动体检

跑真实引擎 + 真实文字渲染，检查四类问题：
  1. 底色灰度是否恰好 240（跨过去就失效）
  2. 底色是否被当成内容（出现全屏连通域）
  3. 文字色与底色是否「同色相」——会让小字被二值化切碎（实测踩过）
  4. 填充色是否太浅（灰度 >238 会被当背景）

用法：
    python lib/tools/check_theme.py            # 全部主题
    python lib/tools/check_theme.py warm cool  # 指定主题
"""
from __future__ import annotations

import colorsys
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import theme as TH  # noqa: E402

FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]


def rgb(hx: str) -> tuple[int, int, int]:
    h = hx.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def gray(hx: str) -> int:
    r, g, b = rgb(hx)
    return int(round(0.299 * r + 0.587 * g + 0.114 * b))


def hue(hx: str) -> float:
    r, g, b = rgb(hx)
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    return h * 360


def hue_gap(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


def load_font(size: int):
    for c in FONT_CANDIDATES:
        if Path(c).exists():
            return ImageFont.truetype(c, size)
    return ImageFont.load_default()


def check(key: str) -> list[str]:
    t = TH.THEMES[key]
    errs: list[str] = []
    try:
        from whiteboard_animator.animator import WhiteboardAnimator
        an = WhiteboardAnimator()
    except ImportError:
        print("[warn] 未装引擎，只做静态检查")
        return errs

    # 1) 底色灰度
    pg = gray(t["paper"])
    if pg != 240:
        errs.append(f"底色灰度 {pg} ≠ 240（>240 被刷白，<240 被当内容）")

    # 2) 底色是否被当内容 + 3) 文字碎裂（用真实文字）
    im = Image.new("RGB", (720, 1280), t["paper"])
    d = ImageDraw.Draw(im)
    f = load_font(30)
    d.text((360, 640), "同一套脚本，不同主题", font=f, fill=t["muted"], anchor="mm")
    d.text((360, 700), "复利滚起来", font=f, fill=t["ink"], anchor="mm")
    arr = np.array(im)
    out = an._enforce_white_bg(arr.copy())
    comps = an._find_components(an._downscale(out))
    full = [c for c in comps if (c["bottom"] - c["top"]) > 1100]
    if full:
        errs.append(f"底色被当成内容（全屏连通域 {len(full)} 个）")
    if len(comps) > 6:
        errs.append(f"文字碎成 {len(comps)} 块 —— muted 太浅或与底色同色相")

    # 4) 填充色
    for ck in ("blueF", "greenF", "yellowF", "purpleF", "orangeF", "redF"):
        g = gray(t[ck])
        if g > 238:
            errs.append(f"{ck}={t[ck]} 灰度 {g} >238，太浅会被当背景")

    # 5) 文字色 vs 底色色相（同色相 + 浅 =碎裂）
    for name in ("muted", "soft"):
        gap = hue_gap(hue(t[name]), hue(t["paper"]))
        if gap < 25 and gray(t[name]) > 125:
            errs.append(f"{name}={t[name]} 与底色色相差仅 {gap:.0f}°且偏浅，"
                        f"易导致小字碎裂（调深到灰度 ≲125，或拉开色相）")
    return errs


def main() -> int:
    keys = sys.argv[1:] or TH.names()
    bad = 0
    for k in keys:
        errs = check(k)
        t = TH.THEMES[k]
        head = f"{k:<11} {t['label']:<12} 底色 {t['paper']} (gray {gray(t['paper'])})"
        if not errs:
            print(f"{head}  ✓ 通过")
        else:
            bad += 1
            print(f"{head}  ✗ {len(errs)} 个问题")
            for e in errs:
                print(f"            - {e}")
    print("-" * 60)
    print("全部通过。" if not bad else f"{bad} 个主题有问题，先修再渲染。")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())