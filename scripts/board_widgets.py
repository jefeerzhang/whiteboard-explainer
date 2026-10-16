#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""board_widgets.py — 白板讲解短视频共享绘图组件库（竖屏 720x1280 记号笔风）

从《5分钟商学院》EP1 实战验证的 make_boards.py 泛化而来。项目绘图脚本的标准用法：

    import sys
    sys.path.insert(0, r"D:/story-skill/.workbuddy/skills/whiteboard-explainer/scripts")
    import board_widgets as BW

    BW.set_canvas(720, 1280)
    img, d = BW.canvas()
    BW.title(d, "标题", y=100)
    BW.person(d, 360, 800, 360)
    BW.save(img, "s01", [
        ("title", (40, 50, 680, 160), "旁白逐字稿一。"),
        ("item",  [(100,300,300,500), (420,300,620,500)], "旁白二（多 box 同时画）。"),
        ("deco",  (200, 600, 500, 900), ""),            # 无旁白 = 纯图形，并入空间重叠的窗口
    ])
    ...
    BW.write_plan("plan.build.json", idea="EP 标题")

引擎纪律（违反必返工，详见 references/concept-short-video.md）：
  - box 一律用 (x0, y0, x1, y1) 左上右下像素序（save 内部自动转引擎的 y 优先归一化格式）
  - 不同 region 的元素之间留 >=18px 白缝（锥尖附近更宽）；物理相连必须同 region
  - 脚/底边接触的元素统一 foot = line_y - 10
  - 文字一律落在纯白区域；填充色灰度 <240
  - 同一 region 内元素允许相连（同窗口一起画，无害）
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image, ImageDraw

W, H = 720, 1280

INK = "#171714"
BLUE = "#3B6FE5"
GREEN = "#2E7D32"
ORANGE = "#D97A26"
RED = "#D64545"
GREY = "#8A8A8A"
PURPLE = "#9B6BBF"
WHITE = "#FFFFFF"
YELLOW = "#E8B93C"
BLUE_LT = "#9EC5F0"
GREEN_LT = "#A8D5A0"
YELLOW_LT = "#FFDF8A"
PINK = "#F0A8C0"
ORANGE_LT = "#F5C77A"
LW = 6

SCENES: list[dict] = []


def set_canvas(w: int, h: int) -> None:
    global W, H
    W, H = w, h


def nb(x0: float, y0: float, x1: float, y1: float) -> list[int]:
    """像素 box (x0,y0,x1,y1)=左上右下 -> 归一化 [ymin, xmin, ymax, xmax] 0-1000"""
    assert x1 > x0 and y1 > y0, f"box 坐标疑似写反/为空: {(x0, y0, x1, y1)}"
    return [round(y0 / H * 1000), round(x0 / W * 1000), round(y1 / H * 1000), round(x1 / W * 1000)]


def _font(size: int, bold: bool):
    from make_text_layer import load_font
    return load_font("bold" if bold else "regular", size)


def canvas():
    img = Image.new("RGB", (W, H), WHITE)
    return img, ImageDraw.Draw(img)


def text(d, cx, cy, s, size=34, color=INK, bold=False, anchor="mm"):
    d.text((cx, cy), s, font=_font(size, bold), fill=color, anchor=anchor)


def title(d, s, y=100, size=46, color=INK):
    text(d, W // 2, y, s, size, color, True)


def save(img: Image.Image, sid: str, regions: list[tuple[str, object, str]]) -> None:
    """regions: (label, box 或 [box...], annotation)；box = (x0, y0, x1, y1) 像素左上右下"""
    img.save(BOARDS_DIR / f"{sid}.png")
    regs = []
    for lab, box, ann in regions:
        if isinstance(box, list):
            entry = {"label": lab, "box": [nb(*b) for b in box]}
        else:
            entry = {"label": lab, "box": nb(*box)}
        if ann:
            entry["annotation"] = ann
        regs.append(entry)
    SCENES.append({"id": sid, "image": f"boards/{sid}.png", "regions": regs})
    print(f"{sid}: {len(regs)} regions")


BOARDS_DIR = Path("boards")


def set_out_dir(boards_dir: str | Path = "boards") -> None:
    global BOARDS_DIR
    BOARDS_DIR = Path(boards_dir)
    BOARDS_DIR.mkdir(parents=True, exist_ok=True)


def write_plan(path: str | Path = "plan.build.json", idea: str = "",
               voice: str = "zh-CN-YunxiNeural", gap: float = 0.2,
               audio_dir: str = "audio/narration") -> None:
    spec = {
        "idea": idea, "canvas": [W, H], "voice": voice, "gap": gap,
        "audio_dir": audio_dir, "scenes": SCENES,
    }
    Path(path).write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"写出 {path}（{len(SCENES)} 拍）")


# ---------------------------------------------------------------- 人物与符号
def person(d, cx, foot, h, out=INK, w=LW, head_r=None):
    hr = head_r or h * 0.17
    top = foot - h
    d.ellipse([cx - hr, top, cx + hr, top + 2 * hr], fill=WHITE, outline=out, width=w)
    d.line([cx, top + 2 * hr, cx, foot - h * 0.42], fill=out, width=w)
    d.line([cx - h * 0.22, foot - h * 0.28, cx + h * 0.22, foot - h * 0.28], fill=out, width=w)
    d.line([cx, foot - h * 0.42, cx - h * 0.16, foot], fill=out, width=w)
    d.line([cx, foot - h * 0.42, cx + h * 0.16, foot], fill=out, width=w)


def person_cheer(d, cx, foot, h, out=INK, w=5):
    """一只手臂高举"""
    hr = h * 0.17
    top = foot - h
    d.ellipse([cx - hr, top, cx + hr, top + 2 * hr], fill=WHITE, outline=out, width=w)
    d.line([cx, top + 2 * hr, cx, foot - h * 0.35], fill=out, width=w)
    d.line([cx, foot - h * 0.42, cx - h * 0.20, foot - h * 0.10], fill=out, width=w)
    d.line([cx, foot - h * 0.35, cx + h * 0.27, foot - h * 0.78], fill=out, width=w)
    d.ellipse([cx + h * 0.27 - 13, foot - h * 0.78 - 13, cx + h * 0.27 + 13, foot - h * 0.78 + 13],
              fill=WHITE, outline=out, width=4)
    d.line([cx, foot - h * 0.35, cx - h * 0.16, foot], fill=out, width=w)
    d.line([cx, foot - h * 0.35, cx + h * 0.16, foot], fill=out, width=w)


def person_think(d, cx, foot, h, out=INK, w=5):
    """托腮思考：一手上举到下巴"""
    hr = h * 0.17
    top = foot - h
    d.ellipse([cx - hr, top, cx + hr, top + 2 * hr], fill=WHITE, outline=out, width=w)
    d.line([cx, top + 2 * hr, cx, foot - h * 0.42], fill=out, width=w)
    d.line([cx - h * 0.22, foot - h * 0.28, cx + h * 0.22, foot - h * 0.28], fill=out, width=w)
    d.line([cx + h * 0.12, top + 2 * hr + 4, cx + h * 0.20, foot - h * 0.30], fill=out, width=w)
    d.line([cx, foot - h * 0.42, cx - h * 0.16, foot], fill=out, width=w)
    d.line([cx, foot - h * 0.42, cx + h * 0.16, foot], fill=out, width=w)


def crown(d, cx, cy, w, h, out=ORANGE, lw=LW):
    d.polygon([(cx - w / 2, cy + h / 2), (cx - w / 2, cy - h / 2), (cx - w / 6, cy),
               (cx, cy - h / 2), (cx + w / 6, cy), (cx + w / 2, cy - h / 2), (cx + w / 2, cy + h / 2)],
              fill=YELLOW_LT, outline=out, width=lw)
    d.line([cx - w / 2, cy + h / 2, cx + w / 2, cy + h / 2], fill=out, width=lw)


def qmark(d, cx, cy, r, out=BLUE, lw=16):
    d.arc([cx - r, cy - r * 1.05, cx + r, cy + r * 0.55], 205, 335, fill=out, width=lw)
    d.line([cx + r * 0.52, cy + r * 0.24, cx + r * 0.06, cy + r * 0.92], fill=out, width=lw)
    d.ellipse([cx + r * 0.06 - lw * 0.62, cy + r * 1.02,
               cx + r * 0.06 + lw * 0.62, cy + r * 1.02 + lw * 1.24], fill=out)


def arrow_r(d, p1, p2, out=INK, lw=6):
    d.line([p1, p2], fill=out, width=lw)
    x1, y1 = p1
    x2, y2 = p2
    a = math.atan2(y2 - y1, x2 - x1)
    hh = 24
    d.polygon([(x2, y2),
               (x2 - hh * math.cos(a - 0.42), y2 - hh * math.sin(a - 0.42)),
               (x2 - hh * math.cos(a + 0.42), y2 - hh * math.sin(a + 0.42))], fill=out)


def bang(d, cx, cy, h, out=RED, lw=10):
    d.line([cx, cy - h / 2, cx, cy + h * 0.18], fill=out, width=lw)
    d.ellipse([cx - lw * 0.7, cy + h * 0.28, cx + lw * 0.7, cy + h * 0.28 + lw * 1.4], fill=out)


def star(d, cx, cy, r, fill=YELLOW, out=INK, w=5):
    pts = []
    for i in range(10):
        a = math.radians(-90 + i * 36)
        rr = r if i % 2 == 0 else r * 0.44
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    d.polygon(pts, fill=fill, outline=out, width=w)


def check(d, cx, cy, s=22, color=GREEN, w=8):
    d.line([cx - s * 0.8, cy, cx - s * 0.2, cy + s * 0.6], fill=color, width=w)
    d.line([cx - s * 0.2, cy + s * 0.6, cx + s * 0.9, cy - s * 0.6], fill=color, width=w)


def cross(d, cx, cy, s=22, color=RED, w=8):
    d.line([cx - s * 0.7, cy - s * 0.7, cx + s * 0.7, cy + s * 0.7], fill=color, width=w)
    d.line([cx - s * 0.7, cy + s * 0.7, cx + s * 0.7, cy - s * 0.7], fill=color, width=w)


def handshake(d, cx, cy, w, out=GREEN, lw=7):
    d.line([cx - w, cy - 14, cx - 18, cy + 4], fill=out, width=lw)
    d.line([cx + w, cy - 14, cx + 18, cy + 4], fill=out, width=lw)
    d.rounded_rectangle([cx - 24, cy - 16, cx + 24, cy + 18], radius=12,
                        fill=WHITE, outline=out, width=lw)
    for i in (-10, 0, 10):
        d.line([cx + i, cy - 8, cx + i, cy + 10], fill=out, width=4)


def speech(d, cx, cy, w, h, out=INK, lw=6, dots=3, tail=(0, 0)):
    """对话气泡，tail=(dx,dy) 气泡底部尖角指向"""
    x0, y0, x1, y1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
    d.rounded_rectangle([x0, y0, x1, y1], radius=22, fill=WHITE, outline=out, width=lw)
    tx, ty = tail
    d.polygon([(cx - 16 + tx, y1 - 2), (cx + 16 + tx, y1 - 2), (cx + tx, ty)], fill=WHITE, outline=out)
    d.line([cx - 15 + tx, y1 - 3, cx + 15 + tx, y1 - 3], fill=WHITE, width=5)
    for i in range(dots):
        xx = x0 + w * (i + 1) / (dots + 1)
        d.ellipse([xx - 8, cy - 8, xx + 8, cy + 8], fill=out)


def num_badge(d, cx, cy, n, out=INK, r=24):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=YELLOW_LT, outline=out, width=5)
    text(d, cx, cy - 2, str(n), 28, INK, True)


def flag(d, px, ytop, ybase_flag, out=RED):
    d.line([px, ytop, px, ybase_flag], fill=INK, width=6)
    d.polygon([(px, ytop), (px + 66, ytop + 24), (px, ytop + 48)], fill=out, outline=INK, width=4)


# ---------------------------------------------------------------- 结构图
def pyramid(d, apex, ybase, halfbase, fill=YELLOW_LT, tiers=2):
    ax, ay = apex
    d.polygon([(ax, ay), (ax - halfbase, ybase), (ax + halfbase, ybase)],
              fill=fill, outline=INK, width=6)
    for i in range(1, tiers + 1):
        y = ay + (ybase - ay) * i / (tiers + 1)
        hw = halfbase * (y - ay) / (ybase - ay)
        d.line([ax - hw, y, ax + hw, y], fill=INK, width=4)


def trapezoid(d, ytop, ybase, hw_top, hw_base, cx=None, tier_colors=None):
    cx = W // 2 if cx is None else cx
    d.polygon([(cx - hw_top, ytop), (cx + hw_top, ytop),
               (cx + hw_base, ybase), (cx - hw_base, ybase)],
              fill=WHITE, outline=INK, width=6)
    n = len(tier_colors or [])
    for i in range(n):
        y0 = ytop + (ybase - ytop) * i / n
        y1 = ytop + (ybase - ytop) * (i + 1) / n
        hw0 = hw_top + (hw_base - hw_top) * i / n
        hw1 = hw_top + (hw_base - hw_top) * (i + 1) / n
        d.polygon([(cx - hw0, y0), (cx + hw0, y0), (cx + hw1, y1), (cx - hw1, y1)],
                  fill=tier_colors[i], outline=INK, width=4)


def stairs(d, y_top0, ybase, n, colors=None, gap=8, xs=40, xe=None):
    """n 级阶梯（左低右高），返回每级 (x0,x1,top)。级间留 gap 白缝保证可分窗。"""
    colors = colors or [BLUE_LT, GREEN_LT, YELLOW_LT, PINK] * 2
    xe = (W - 40) if xe is None else xe
    sw = (xe - xs - gap * (n - 1)) / n
    tops = []
    for i in range(n):
        lx = xs + i * (sw + gap)
        top = ybase - 120 - (ybase - y_top0 - 120) * (n - 1 - i) / max(n - 1, 1)
        d.rectangle([lx, top, lx + sw, ybase], fill=colors[i % len(colors)], outline=INK, width=5)
        tops.append((lx, lx + sw, top))
    return tops


def office_building(d, cx, base, bw, bh, fill=BLUE_LT, cols=3, rows=4):
    d.rectangle([cx - bw / 2, base - bh, cx + bw / 2, base], fill=fill, outline=INK, width=6)
    for r in range(rows):
        for c in range(cols):
            wx = cx - bw / 2 + bw * (c + 0.5) / cols
            wy = base - bh + bh * (r + 0.55) / (rows + 0.4)
            d.rectangle([wx - bw * 0.10, wy - bh * 0.075, wx + bw * 0.10, wy + bh * 0.075],
                        fill=WHITE, outline=INK, width=3)
    d.rectangle([cx - bw * 0.12, base - bh * 0.16, cx + bw * 0.12, base], fill=WHITE, outline=INK, width=4)


def shop_front(d, cx, base, sw, sh, awn, sign):
    x0, x1 = cx - sw / 2, cx + sw / 2
    y0 = base - sh
    d.rectangle([x0, y0 + 44, x1, base], fill=WHITE, outline=INK, width=6)
    d.rectangle([x0 - 12, y0 + 16, x1 + 12, y0 + 46], fill=awn, outline=INK, width=5)
    n = 4
    for i in range(n):
        ax = x0 - 12 + (sw + 24) * i / n
        d.arc([ax, y0 + 32, ax + (sw + 24) / n, y0 + 60], 0, 180, fill=INK, width=4)
    d.rectangle([x0 + 10, y0 - 42, x1 - 10, y0 + 12], fill=WHITE, outline=INK, width=5)
    text(d, cx, y0 - 15, sign, 30, INK, True)
    d.rectangle([cx - 24, base - 66, cx + 24, base], fill=ORANGE_LT, outline=INK, width=4)
    d.rectangle([x0 + 14, y0 + 66, x0 + 62, y0 + 118], fill=BLUE_LT, outline=INK, width=4)
    d.rectangle([x1 - 62, y0 + 66, x1 - 14, y0 + 118], fill=BLUE_LT, outline=INK, width=4)


# ---------------------------------------------------------------- 道具
def price_tag(d, cx, cy, tw, th, main, sub, out=ORANGE):
    x0, y0, x1, y1 = cx - tw / 2, cy - th / 2, cx + tw / 2, cy + th / 2
    d.rounded_rectangle([x0, y0, x1, y1], radius=16, fill=WHITE, outline=out, width=6)
    d.ellipse([x0 + 12, y0 + 10, x0 + 32, y0 + 30], fill=WHITE, outline=out, width=4)
    d.line([x0 + 22, y0 + 10, x0 + 10, y0 - 14], fill=out, width=4)
    text(d, cx, cy - (10 if sub else 0), main, 34, RED, True)
    if sub:
        text(d, cx, cy + 30, sub, 20, GREY)


def coin(d, cx, cy, r, out=ORANGE, w=5, mark="¥"):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=YELLOW_LT, outline=out, width=w)
    d.ellipse([cx - r * 0.72, cy - r * 0.72, cx + r * 0.72, cy + r * 0.72], fill=WHITE, outline=out, width=3)
    text(d, cx, cy - 2, mark, int(r * 0.9), ORANGE, True)


def money_stack(d, cx, cy, w, h, n=3, out=ORANGE):
    """一叠钞票"""
    for i in range(n):
        off = i * 8
        d.rectangle([cx - w / 2, cy - h / 2 - off, cx + w / 2, cy + h / 2 - off],
                    fill=GREEN_LT if i % 2 else WHITE, outline=out, width=4)
    d.ellipse([cx - 14, cy - h / 2 - 8 - 14, cx + 14, cy - h / 2 - 8 + 14], fill=YELLOW_LT, outline=out, width=3)


def gift_box(d, cx, cy, s):
    d.rectangle([cx - s / 2, cy - s * 0.3, cx + s / 2, cy + s * 0.62], fill=PINK, outline=INK, width=5)
    d.rectangle([cx - s * 0.58, cy - s * 0.52, cx + s * 0.58, cy - s * 0.26], fill=PINK, outline=INK, width=5)
    d.line([cx, cy - s * 0.26, cx, cy + s * 0.62], fill=ORANGE, width=7)
    d.ellipse([cx - s * 0.34, cy - s * 0.78, cx - s * 0.02, cy - s * 0.46], fill=WHITE, outline=INK, width=4)
    d.ellipse([cx + s * 0.02, cy - s * 0.78, cx + s * 0.34, cy - s * 0.46], fill=WHITE, outline=INK, width=4)


def music_note(d, cx, cy, s, fill=BLUE):
    d.ellipse([cx - s * 0.8, cy - s * 0.55, cx + s * 0.8, cy + s * 0.55], fill=fill, outline=INK, width=4)
    d.line([cx + s * 0.72, cy, cx + s * 0.72, cy - s * 2.6], fill=INK, width=8)
    d.polygon([(cx + s * 0.72, cy - s * 2.6), (cx + s * 0.72, cy - s * 1.7),
               (cx + s * 1.75, cy - s * 2.1), (cx + s * 1.75, cy - s * 2.75)],
              fill=fill, outline=INK, width=3)


def palette(d, cx, cy, rx, ry):
    d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=WHITE, outline=INK, width=6)
    d.ellipse([cx + rx * 0.25, cy - ry * 0.1, cx + rx * 0.6, cy + ry * 0.35], fill=WHITE, outline=INK, width=4)
    for i, col in enumerate([RED, YELLOW, BLUE, GREEN, PURPLE]):
        a = math.radians(140 + i * 45)
        px, py = cx + rx * 0.55 * math.cos(a), cy + ry * 0.55 * math.sin(a)
        d.ellipse([px - 12, py - 12, px + 12, py + 12], fill=col, outline=INK, width=3)
    d.line([cx - rx * 0.1, cy - ry * 2.0, cx + rx * 0.55, cy - ry * 0.45], fill=ORANGE, width=8)
    d.polygon([(cx + rx * 0.55, cy - ry * 0.45), (cx + rx * 0.38, cy - ry * 0.62),
               (cx + rx * 0.72, cy - ry * 0.62)], fill=INK)


def easel(d, cx, ytop_frame, fw, fh, foot_y):
    x0, y0 = cx - fw / 2, ytop_frame
    x1, y1 = cx + fw / 2, ytop_frame + fh
    d.rectangle([x0, y0, x1, y1], fill=WHITE, outline=INK, width=6)
    d.polygon([(cx - fw * 0.28, y1 - 22), (cx, y0 + fh * 0.32), (cx + fw * 0.28, y1 - 22)],
              fill=GREEN_LT, outline=INK, width=4)
    d.ellipse([cx + fw * 0.10, y0 + fh * 0.10, cx + fw * 0.10 + 44, y0 + fh * 0.10 + 44],
              fill=YELLOW, outline=INK, width=4)
    d.line([x0 + 22, y1 - 8, x0 - 10, foot_y], fill=INK, width=7)
    d.line([x1 - 22, y1 - 8, x1 + 10, foot_y], fill=INK, width=7)
    d.line([cx, y1 + 10, cx, foot_y], fill=INK, width=5)
    d.line([x0 + 30, y1 + 55, x1 - 30, y1 + 55], fill=INK, width=6)


def gavel(d, hx, hy):
    d.line([hx + 10, hy - 12, hx + 118, hy - 78], fill=INK, width=9)
    d.line([hx - 46, hy + 30, hx + 48, hy - 32], fill=INK, width=30)
    d.ellipse([hx - 52, hy + 22, hx - 36, hy + 40], fill=INK)
    d.ellipse([hx + 42, hy - 42, hx + 58, hy - 24], fill=INK)


def scales(d, cx, cy, w, h, out=INK, lw=LW):
    d.line([cx, cy - h * 0.34, cx, cy + h * 0.3], fill=out, width=lw)
    d.line([cx - w * 0.5, cy - h * 0.34, cx + w * 0.5, cy - h * 0.34], fill=out, width=lw)
    d.line([cx - w * 0.5, cy - h * 0.34, cx - w * 0.05, cy], fill=out, width=4)
    d.line([cx + w * 0.5, cy - h * 0.34, cx + w * 0.05, cy], fill=out, width=4)
    d.arc([cx - w * 0.5, cy, cx - w * 0.05, cy + h * 0.2], 0, 180, fill=out, width=4)
    d.arc([cx + w * 0.05, cy + h * 0.06, cx + w * 0.5, cy + h * 0.26], 0, 180, fill=out, width=4)
    d.polygon([(cx, cy + h * 0.3), (cx - w * 0.16, cy + h * 0.46), (cx + w * 0.16, cy + h * 0.46)], fill=out)


def open_book(d, cx, cy, bw, bh):
    x0, x1 = cx - bw / 2, cx + bw / 2
    y0, y1 = cy - bh / 2, cy + bh / 2
    d.polygon([(cx, y0 + 14), (x0, y0 - 6), (x0, y1 + 6), (cx, y1 + 20)],
              fill=WHITE, outline=INK, width=5)
    d.polygon([(cx, y0 + 14), (x1, y0 - 6), (x1, y1 + 6), (cx, y1 + 20)],
              fill=WHITE, outline=INK, width=5)
    for i in range(3):
        yy = y0 + 14 + i * (bh * 0.2)
        d.line([x0 + 18, yy, cx - 16, yy + 6], fill=GREY, width=3)
        d.line([cx + 16, yy + 6, x1 - 18, yy], fill=GREY, width=3)
    d.rectangle([x0 - 10, y1 + 6, x1 + 10, y1 + 20], fill=BLUE_LT, outline=INK, width=4)


def spotlight(d, lx, ly, fx, fy):
    d.line([lx, ly - 130, lx, ly - 26], fill=INK, width=6)
    d.polygon([(lx - 40, ly - 26), (lx + 40, ly - 26), (lx + 26, ly + 26), (lx - 26, ly + 26)],
              fill=GREY, outline=INK, width=5)
    dx, dy = fx - lx, fy - ly
    nx, ny = -dy * 0.42, dx * 0.42
    d.polygon([(lx - nx * 0.4, ly - ny * 0.4), (lx + nx * 0.4, ly + ny * 0.4),
               (fx + nx, fy + ny), (fx - nx, fy - ny)], fill=YELLOW_LT)
    d.line([lx - nx * 0.4, ly - ny * 0.4, fx - nx, fy - ny], fill=YELLOW, width=4)
    d.line([lx + nx * 0.4, ly + ny * 0.4, fx + nx, fy + ny], fill=YELLOW, width=4)
    star(d, fx, fy, 26, fill=ORANGE, out=INK, w=4)


def infinity(d, cx, cy, r, out=PURPLE, lw=10):
    d.ellipse([cx - 2 * r, cy - r * 0.72, cx, cy + r * 0.72], outline=out, width=lw)
    d.ellipse([cx, cy - r * 0.72, cx + 2 * r, cy + r * 0.72], outline=out, width=lw)


def shield(d, cx, cy, w, h, fill=GREEN_LT):
    d.polygon([(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2),
               (cx + w / 2, cy + h * 0.1), (cx, cy + h / 2), (cx - w / 2, cy + h * 0.1)],
              fill=fill, outline=INK, width=6)
    d.line([cx - w * 0.22, cy - h * 0.02, cx - w * 0.04, cy + h * 0.16], fill=GREEN, width=8)
    d.line([cx - w * 0.04, cy + h * 0.16, cx + w * 0.26, cy - h * 0.18], fill=GREEN, width=8)


def mooncake(d, cx, cy, r, num=None):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=ORANGE_LT, outline=INK, width=5)
    d.ellipse([cx - r * 0.68, cy - r * 0.68, cx + r * 0.68, cy + r * 0.68],
              fill=WHITE, outline=INK, width=4)
    for i in range(8):
        a = math.radians(i * 45)
        px, py = cx + r * 0.34 * math.cos(a), cy + r * 0.34 * math.sin(a)
        d.ellipse([px - 7, py - 7, px + 7, py + 7], fill=YELLOW, outline=INK, width=3)
    if num:
        text(d, cx, cy, str(num), 26, RED, True)


def work_badge(d, cx, cy, bw, bh, crack=True):
    x0, y0, x1, y1 = cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2
    d.rounded_rectangle([x0, y0, x1, y1], radius=14, fill=WHITE, outline=BLUE, width=6)
    d.ellipse([cx - 12, y0 + 8, cx + 12, y0 + 32], fill=WHITE, outline=BLUE, width=4)
    person(d, cx, y1 - 24, 62, out=INK, w=4)
    if crack:
        d.line([cx - 8, y0 - 4, cx + 12, cy - bh * 0.12, cx - 14, cy + bh * 0.14, cx + 8, y1 + 4],
               fill=RED, width=6, joint="curve")


def laptop(d, cx, cy, w, h):
    d.rectangle([cx - w * 0.42, cy - h * 0.5, cx + w * 0.42, cy + h * 0.18], fill=WHITE, outline=INK, width=5)
    d.line([cx - w * 0.32, cy - h * 0.32, cx + w * 0.32, cy - h * 0.32], fill=GREY, width=3)
    d.line([cx - w * 0.32, cy - h * 0.18, cx + w * 0.10, cy - h * 0.18], fill=GREY, width=3)
    d.polygon([(cx - w * 0.55, cy + h * 0.42), (cx - w * 0.42, cy + h * 0.18),
               (cx + w * 0.42, cy + h * 0.18), (cx + w * 0.55, cy + h * 0.42)],
              fill=BLUE_LT, outline=INK, width=4)


def phone(d, cx, cy, w, h):
    d.rounded_rectangle([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], radius=14,
                        fill=WHITE, outline=INK, width=5)
    d.line([cx - w * 0.15, cy - h / 2 + 10, cx + w * 0.15, cy - h / 2 + 10], fill=INK, width=4)
    d.ellipse([cx - 8, cy + h / 2 - 22, cx + 8, cy + h / 2 - 8], outline=INK, width=3)


def cart(d, cx, cy, s, out=INK, lw=5):
    """购物车"""
    d.polygon([(cx - s * 0.5, cy - s * 0.35), (cx - s * 0.32, cy - s * 0.35),
               (cx - s * 0.12, cy + s * 0.18), (cx + s * 0.42, cy + s * 0.18),
               (cx + s * 0.55, cy - s * 0.18), (cx - s * 0.26, cy - s * 0.18)],
              fill=WHITE, outline=out, width=lw)
    for dx in (-s * 0.05, s * 0.30):
        d.ellipse([cx + dx - s * 0.08, cy + s * 0.30, cx + dx + s * 0.08, cy + s * 0.46],
                  outline=out, width=4)


def brain_scale(d, cx, cy, r, fill=PINK):
    """天平上放着一颗心/脑（心理账户等概念）— 简化为心形"""
    d.polygon([(cx, cy + r * 0.9), (cx - r, cy - r * 0.1), (cx - r * 0.5, cy - r * 0.8),
               (cx, cy - r * 0.3), (cx + r * 0.5, cy - r * 0.8), (cx + r, cy - r * 0.1)],
              fill=fill, outline=INK, width=4)


def burst(d, cx, cy, r, out=ORANGE, lw=5, n=10):
    """爆炸星芒（强调）"""
    for i in range(n):
        a = math.radians(i * 360 / n)
        r1 = r if i % 2 == 0 else r * 0.55
        d.line([cx + r1 * 0.5 * math.cos(a), cy + r1 * 0.5 * math.sin(a),
                cx + r1 * math.cos(a), cy + r1 * math.sin(a)], fill=out, width=lw)
