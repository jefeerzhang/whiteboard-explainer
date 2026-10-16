#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""draw_eclipse_diagrams.py — 用 PIL 程序化绘制「日全食」几何示意图

几何准确性优先（影锥收敛、轨道倾角这类图生图模型画不准）。
风格：白底 + 粗记号笔轮廓 + 少量平涂马克笔色，符合白板引擎的 ink-on-white 假设。
所有文字用本机字体确定性渲染，随后由白板引擎逐笔"写"出来。
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 720
OUT = Path(__file__).parent / "boards"
OUT.mkdir(parents=True, exist_ok=True)

INK = "#171714"
YELLOW = "#FFD34D"
YELLOW_DK = "#F5A623"
BLUE = "#2E6FD6"
BLUE_LT = "#9EC5F0"
GREY = "#8A8A8A"
GREY_LT = "#CFCFCF"
RED = "#D64545"
GREEN = "#2E7D32"
WHITE = "#FFFFFF"
UMBRA = "#3A3A3A"

F_BOLD = "bold"
F_REG = "regular"


def f(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """复用 skill 自带的 make_text_layer.resolve_font_path（regular/bold 跨平台兜底）"""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from make_text_layer import load_font  # type: ignore  # noqa: E402
    return load_font(F_BOLD if bold else F_REG, size)


def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), WHITE)
    return img, ImageDraw.Draw(img)


def label(d: ImageDraw.ImageDraw, xy, text, size=34, color=INK, bold=False, anchor="mm"):
    d.text(xy, text, font=f(size, bold), fill=color, anchor=anchor)


def title(d: ImageDraw.ImageDraw, text: str) -> None:
    label(d, (W // 2, 62), text, size=48, bold=True, anchor="mm")


def sun(d: ImageDraw.ImageDraw, cx, cy, r, rays=True, color=YELLOW) -> None:
    if rays:
        for i in range(16):
            a = i * 2 * math.pi / 16
            x1, y1 = cx + (r + 10) * math.cos(a), cy + (r + 10) * math.sin(a)
            x2, y2 = cx + (r + 34) * math.cos(a), cy + (r + 34) * math.sin(a)
            d.line((x1, y1, x2, y2), fill=YELLOW_DK, width=7)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color, outline=INK, width=6)


def moon(d: ImageDraw.ImageDraw, cx, cy, r, color=GREY) -> None:
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color, outline=INK, width=5)


def earth(d: ImageDraw.ImageDraw, cx, cy, r) -> None:
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=BLUE_LT, outline=INK, width=6)
    # 简化大陆块
    d.ellipse((cx - r * 0.62, cy - r * 0.38, cx - r * 0.05, cy + r * 0.30), fill=GREEN, outline=INK, width=4)
    d.ellipse((cx + r * 0.18, cy + r * 0.12, cx + r * 0.70, cy + r * 0.62), fill=GREEN, outline=INK, width=4)


def dashed(d: ImageDraw.ImageDraw, p1, p2, color=GREY, width=4, dash=16, gap=12) -> None:
    x1, y1, x2, y2 = p1 + p2
    length = math.hypot(x2 - x1, y2 - y1)
    n = int(length // (dash + gap))
    for i in range(n):
        t0, t1 = i * (dash + gap) / length, (i * (dash + gap) + dash) / length
        d.line((x1 + (x2 - x1) * t0, y1 + (y2 - y1) * t0,
                x1 + (x2 - x1) * t1, y1 + (y2 - y1) * t1), fill=color, width=width)


# ---------------------------------------------------------------- s02 三者连线
def s02() -> None:
    img, d = canvas()
    title(d, "日全食发生时，三者连成一条直线")
    sx, sy, sr = 240, 370, 105
    mx, my, mr = 640, 370, 46
    ex, ey, er = 1010, 370, 125
    dashed(d, (sx, sy), (ex, ey))
    sun(d, sx, sy, sr)
    moon(d, mx, my, mr)
    earth(d, ex, ey, er)
    label(d, (sx, sy + sr + 78), "太阳", bold=True)
    label(d, (mx, my + mr + 78), "月球", bold=True)
    label(d, (ex, ey + er + 78), "地球", bold=True)
    label(d, (W // 2, 672), "月球运行到太阳和地球中间，正好挡住太阳", size=32, color=INK)
    img.save(OUT / "s02.png")


# ---------------------------------------------------------------- s03 本影半影
def s03() -> None:
    img, d = canvas()
    title(d, "月球投下两种影子")
    sx, sy, sr = 160, 380, 105
    mx, my, mr = 560, 380, 44
    # 本影：外公切线收敛锥
    s_top, s_bot = sy - sr, sy + sr
    m_top, m_bot = my - mr, my + mr
    k_u = (m_top - s_top) / (mx - sx)
    k_l = (m_bot - s_bot) / (mx - sx)
    # 本影锥顶点：解 s_top + k_u*(x-sx) = s_bot + k_l*(x-sx)
    x_apex = sx + (s_bot - s_top) / (k_u - k_l)
    y_apex = s_top + k_u * (x_apex - sx)
    # 半影：内公切线发散锥；放缓发散角并把内缘从月球外 10px 起步，
    # 避免与月球/本影连成单个巨型连通域（那样没法按 cue 分窗绘制）
    shrink = 0.42
    ka = (m_bot - s_top) / (mx - sx) * shrink
    kb = (m_top - s_bot) / (mx - sx) * shrink
    far_x = 1240
    inner = mr + 10
    pen_top0 = s_top + kb * (mx + inner - sx)
    pen_bot0 = s_bot + ka * (mx + inner - sx)
    pen_top = s_top + kb * (far_x - sx)
    pen_bot = s_bot + ka * (far_x - sx)
    d.polygon([(mx + inner, pen_top0), (mx + inner, pen_bot0), (far_x, pen_bot), (far_x, pen_top)], fill=GREY_LT)
    d.line([(mx + inner, pen_top0), (far_x, pen_top)], fill=GREY, width=4)
    d.line([(mx + inner, pen_bot0), (far_x, pen_bot)], fill=GREY, width=4)
    # 白缝：把半影中本影锥周围挖白一圈，保证本影与半影在像素上不连通
    # （连通组件跨 cue 无法分窗绘制），月球-本影仍保持相连
    d.polygon([(mx + 48, m_top - 30), (mx + 48, m_bot + 30), (x_apex + 30, y_apex)], fill=WHITE)
    d.polygon([(mx, m_top), (mx, m_bot), (x_apex, y_apex)], fill=UMBRA)
    d.line([(mx, m_top), (x_apex, y_apex)], fill=INK, width=5)
    d.line([(mx, m_bot), (x_apex, y_apex)], fill=INK, width=5)
    sun(d, sx, sy, sr)
    moon(d, mx, my, mr)
    label(d, (sx, sy + sr + 92), "太阳", bold=True)
    label(d, (mx, my - mr - 54), "月球", bold=True)
    label(d, (500, 488), "本影：完全变黑", size=30, bold=True)
    label(d, (1060, 180), "半影", size=36, bold=True)
    label(d, (1060, 224), "只遮一部分", size=26)
    img.save(OUT / "s03.png")


# ---------------------------------------------------------------- s04 全食带
def s04() -> None:
    img, d = canvas()
    title(d, "本影扫过地球，形成一条极窄的全食带")
    mx, my, mr = 250, 210, 40
    ex, ey, er = 900, 470, 235
    # 本影锥打到地球表面
    tx, ty = 790, 300
    d.polygon([(mx, my - mr), (mx, my + mr), (tx + 60, ty + 70), (tx - 10, ty - 10)], fill=UMBRA)
    # 半影大范围
    d.polygon([(mx, my - mr), (mx, my + mr), (1280, 720), (1280, 60)], fill=GREY_LT)
    earth(d, ex, ey, er)
    # 全食带：地球表面上的小椭圆
    d.ellipse((tx - 46, ty - 16, tx + 46, ty + 30), fill=RED, outline=INK, width=4)
    moon(d, mx, my, mr)
    label(d, (mx, my - mr - 44), "月球", bold=True)
    label(d, (tx + 30, ty - 60), "全食带", size=34, bold=True, color=RED)
    dashed(d, (tx + 46, ty + 8), (1120, 190), color=RED, width=4)
    label(d, (1130, 168), "只有这里看到全食", size=30, color=RED, anchor="rm")
    label(d, (520, 660), "半影区：看到日偏食", size=32)
    img.save(OUT / "s04.png")


# ---------------------------------------------------------------- s05 轨道倾角
def s05() -> None:
    img, d = canvas()
    title(d, "为什么不是每月都有日食？")
    ex, ey, er = 640, 430, 120
    earth(d, ex, ey, er)
    # 黄道面（水平）
    dashed(d, (140, ey), (1140, ey), color=BLUE, width=5)
    label(d, (1140, ey - 40), "黄道面", size=32, color=BLUE, anchor="rm")
    # 白道面（倾斜）
    ang = math.radians(-13)
    cx, cy = ex, ey
    rx, ry = 500, 150
    pts = []
    for i in range(181):
        t = i * math.pi / 180
        x = rx * math.cos(t)
        y = ry * math.sin(t)
        pts.append((cx + x * math.cos(ang) - y * math.sin(ang),
                    cy + x * math.sin(ang) + y * math.cos(ang)))
    d.line(pts, fill=RED, width=6)
    label(d, (1120, 200), "白道面（月球轨道）", size=32, color=RED, anchor="rm")
    # 交点
    ix, iy = cx + rx * math.cos(ang), cy + rx * math.sin(ang)
    d.ellipse((ix - 12, iy - 12, ix + 12, iy + 12), fill=YELLOW, outline=INK, width=4)
    # 倾角弧线标注
    d.arc((cx - 210, ey - 210, cx + 210, ey + 210), 340, 360, fill=INK, width=5)
    label(d, (cx + 250, ey + 46), "约 5°", size=34, bold=True)
    label(d, (W // 2, 660), "月球轨道倾斜约 5 度，多数时候影子从地球上下方掠过", size=32)
    img.save(OUT / "s05.png")


# ---------------------------------------------------------------- s06 五个阶段
def s06() -> None:
    img, d = canvas()
    title(d, "一次日全食的五个阶段")
    stages = ["初亏", "食既", "食甚", "生光", "复圆"]
    ys = 340
    r = 78
    xs = [170, 430, 690, 950, 1180]
    for i, (cx, name) in enumerate(zip(xs, stages)):
        # 太阳底
        sun(d, cx, ys, r, rays=False)
        # 月亮遮挡（黑色圆偏移）
        if i == 0:      # 初亏：右上角刚被咬一小口
            off = (105, -105)
        elif i == 1:    # 食既：几乎全遮，留一线月牙
            off = (14, -14)
        elif i == 2:    # 食甚：完全遮住
            off = (0, 0)
        elif i == 3:    # 生光：另一侧露光
            off = (-55, 25)
        else:           # 复圆：最后一点缺口
            off = (-140, 40)
        d.ellipse((cx + off[0] - r, ys + off[1] - r, cx + off[0] + r, ys + off[1] + r),
                  fill="#3A3A3A", outline=INK, width=4)
        if i == 2:  # 食甚：日冕光环
            for k in range(24):
                a = k * 2 * math.pi / 24
                x1 = cx + (r + 4) * math.cos(a)
                y1 = ys + (r + 4) * math.sin(a)
                x2 = cx + (r + 30) * math.cos(a)
                y2 = ys + (r + 30) * math.sin(a)
                d.line((x1, y1, x2, y2), fill="#F0C419", width=6)
        label(d, (cx, ys + r + 66), name, size=38, bold=True)
    label(d, (W // 2, 640), "从初亏到复圆，整个过程通常只有两三个小时", size=32)
    img.save(OUT / "s06.png")


if __name__ == "__main__":
    s02(); s03(); s04(); s05(); s06()
    print("写出 s02-s06 几何图 ->", OUT)
