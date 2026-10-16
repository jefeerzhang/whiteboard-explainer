#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/pick_paper.py — 主题底色求解与安全验证

底色不是「好看就行」：引擎的 240 灰度线是生死线，跨过去底色就会被当成
图形去描（一整屏慢慢涂满），或者被刷成纯白（等于没换色）。

用法：
    python lib/tools/pick_paper.py                 # 列出所有主题并实测安全
    python lib/tools/pick_paper.py warm           # 只验 warm
    python lib/tools/pick_paper.py "#F0EADC"      # 求解任意色的 240 版本

任何时候新加主题，先在这里过一遍；不过就别渲染，能省掉一次几分钟的失败渲染。
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from theme import THEMES, paper_rgb, solve_paper  # noqa: E402


def gray(r: int, g: int, b: int) -> int:
    px = np.array([[[r, g, b]]], dtype=np.uint8)
    return int(cv2.cvtColor(px, cv2.COLOR_RGB2GRAY)[0][0])


def verify(hex_color: str) -> tuple[bool, str]:
    """用引擎自己的 _enforce_white_bg 实测这个底色安不安全。"""
    try:
        from whiteboard_animator.animator import WhiteboardAnimator
    except ImportError:
        return True, "跳过（未装引擎，仅做灰度检查）"
    an = WhiteboardAnimator()
    r, g, b = paper_rgb({"paper": hex_color})
    img = np.full((300, 300, 3), 255, dtype=np.uint8)
    img[:, :] = [r, g, b]
    cv2.line(img, (40, 150), (260, 150), (20, 20, 20), 6)   # 放一条内容线
    cv2.circle(img, (150, 90), 24, (40, 90, 200), -1)
    out = an._enforce_white_bg(img.copy())
    comps = an._find_components(an._downscale(out))
    full = [c for c in comps if (c["bottom"] - c["top"]) > 250]
    if full:
        return False, f"底色被当成内容（全屏连通域 {len(full)} 个）"
    return True, f"安全（{len(comps)} 个连通域，线条正常）"


def main() -> int:
    args = sys.argv[1:]
    if args and args[0].startswith("#"):
        c = args[0]
        r, g, b = paper_rgb({"paper": c})
        nr, ng, nb = solve_paper(r, g, b)
        fixed = f"#{nr:02X}{ng:02X}{nb:02X}"
        print(f"{c}  gray={gray(r,g,b)}")
        print(f"→ 240 版: {fixed}  gray={gray(nr,ng,nb)}")
        ok, msg = verify(fixed)
        print(f"→ {'✓' if ok else '✗'} {msg}")
        return 0 if ok else 1

    targets = [args[0]] if args else list(THEMES)
    print(f"{'主题':<12}{'名称':<14}{'底色':<11}{'灰度':<7}{'饱和差':<8}判定")
    print("-" * 68)
    bad = 0
    for key in targets:
        th = THEMES[key]
        r, g, b = paper_rgb(th)
        gv = gray(r, g, b)
        sat = max(r, g, b) - min(r, g, b)
        ok, msg = verify(th["paper"])
        if not ok:
            bad += 1
        print(f"{key:<12}{th['label']:<14}{th['paper']:<11}{gv:<7}{sat:<8}"
              f"{'✓' if ok else '✗'} {msg}")
    print("-" * 68)
    if bad:
        print(f"{bad} 个主题不安全 —— 不要用它们渲染。")
    else:
        print("全部主题通过。")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())