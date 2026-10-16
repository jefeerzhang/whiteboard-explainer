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
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import theme as _theme  # noqa: E402

W, H = 720, 1280

# ── 主题 ─────────────────────────────────────────────────────────
# 默认 "whiteboard" 与改造前的硬编码色板一致，老项目零变化。
# 换主题：BW.set_theme("warm")，或环境变量 WHITEBOARD_THEME=warm
_active: dict = _theme.THEMES[_theme.DEFAULT_THEME]


def set_theme(name: str | None = None) -> dict:
    """切换配色主题。底色必须是灰度 240 的纯色，详见 lib/theme.py。

    实现要点：Python 函数对象的 __defaults__ 是运行时可变的。这里把每个
    绘图函数签名里的颜色默认值就地改写成新主题的色值，因此
    「模块导入时的常量」变成「每次 set_theme 后的当前主题」，
    而所有绘图函数的函数体一行都不用动，老代码调用方式完全不变。
    """
    global _active, WHITE, INK, BLUE, GREEN, ORANGE, RED, GREY, PURPLE, YELLOW
    global BLUE_LT, GREEN_LT, YELLOW_LT, PINK, ORANGE_LT
    import os
    _active = _theme.get(name or os.environ.get("WHITEBOARD_THEME"))
    t = _active
    # 同步模块级常量（供直接 import BW; BW.INK 的老代码）
    for k in ("ink", "blue", "green", "orange", "red", "muted", "purple",
              "yellow", "blueF", "greenF", "yellowF", "purpleF", "orangeF"):
        globals()[_UPPER[k]] = t[k]
    INK, BLUE, GREEN, ORANGE, RED = t["ink"], t["blue"], t["green"], t["orange"], t["red"]
    GREY, PURPLE, YELLOW = t["muted"], t["purple"], t["yellow"]
    BLUE_LT, GREEN_LT, YELLOW_LT = t["blueF"], t["greenF"], t["yellowF"]
    PINK, ORANGE_LT = t["purpleF"], t["orangeF"]
    WHITE = t["paper"]
    # 重写所有绘图函数的颜色默认值
    _apply_defaults()
    return t


_UPPER = {"ink": "INK", "blue": "BLUE", "green": "GREEN", "orange": "ORANGE",
          "red": "RED", "muted": "GREY", "purple": "PURPLE",
          "yellow": "YELLOW", "blueF": "BLUE_LT", "greenF": "GREEN_LT",
          "yellowF": "YELLOW_LT", "purpleF": "PINK", "orangeF": "ORANGE_LT",
          "paper": "WHITE"}
# 语义名 → 调色板键。签名里写 out=INK 的，键就是 ink。
_SEM = {"INK": "ink", "BLUE": "blue", "GREEN": "green", "ORANGE": "orange",
        "RED": "red", "GREY": "muted", "PURPLE": "purple", "YELLOW": "yellow",
        "WHITE": "paper", "BLUE_LT": "blueF", "GREEN_LT": "greenF",
        "YELLOW_LT": "yellowF", "PINK": "purpleF", "ORANGE_LT": "orangeF"}

# 记录原始默认值：(函数名, 位置, 语义名)，用于主题切换时重写
_DEF_SLOTS: list[tuple] = []


def _apply_defaults() -> None:
    """把所有绘图函数签名里的颜色默认值换成当前主题色值。"""
    for fn_name, idx, sem in _DEF_SLOTS:
        fn = globals().get(fn_name)
        if fn is None:
            continue
        d = list(fn.__defaults__ or ())
        if idx < len(d):
            d[idx] = _active[_SEM[sem]]
            fn.__defaults__ = tuple(d)


def C(name: str) -> str:
    """按调色板键名取色：INK / RED / BLUE_LT / PAPER / MUTED …

    键名与 frametell 引擎一致（ink/soft/muted/faint/paper + 色名F），
    便于日后迁移到它的渲染后端时组件零改动。
    """
    t = _active
    if name in ("PAPER", "WHITE"):
        return t["paper"]
    if name in t:
        return t[name]
    alias = {"GREY": "muted", "GRAY": "muted", "BLUE_LT": "blueF",
             "GREEN_LT": "greenF", "YELLOW_LT": "yellowF",
             "ORANGE_LT": "orangeF", "PINK": "purpleF"}
    key = alias.get(name, name)
    if key in t:
        return t[key]
    raise KeyError(f"主题里没有颜色 {name!r}")


# 常用语义色的模块级别名（保持旧代码 import BW; BW.INK 的用法继续可用）
INK = _theme.THEMES[_theme.DEFAULT_THEME]["ink"]
BLUE = _theme.THEMES[_theme.DEFAULT_THEME]["blue"]
GREEN = _theme.THEMES[_theme.DEFAULT_THEME]["green"]
ORANGE = _theme.THEMES[_theme.DEFAULT_THEME]["orange"]
RED = _theme.THEMES[_theme.DEFAULT_THEME]["red"]
GREY = _theme.THEMES[_theme.DEFAULT_THEME]["muted"]
PURPLE = _theme.THEMES[_theme.DEFAULT_THEME]["purple"]
WHITE = _theme.THEMES[_theme.DEFAULT_THEME]["paper"]
YELLOW = _theme.THEMES[_theme.DEFAULT_THEME]["yellow"]
BLUE_LT = _theme.THEMES[_theme.DEFAULT_THEME]["blueF"]
GREEN_LT = _theme.THEMES[_theme.DEFAULT_THEME]["greenF"]
YELLOW_LT = _theme.THEMES[_theme.DEFAULT_THEME]["yellowF"]
PINK = _theme.THEMES[_theme.DEFAULT_THEME]["purpleF"]
ORANGE_LT = _theme.THEMES[_theme.DEFAULT_THEME]["orangeF"]
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
    """问号。三笔构成：上钩 + 下竖钩 + 圆点。

    旧实现用 arc(205~335) 画钩，小尺寸下弧几乎看不见、点也只有几像素。
    改成用 bezier 曲线画钩、点用min(lw, r*0.34) 控制，任何 r 都清晰。
    """
    import math as _m
    w = max(int(lw), int(r * 0.20))          # 线宽随尺寸自适应
    # 上钩：从左上起笔，绕到右侧再回勾向左下
    hook = [
        (cx - r * 0.62, cy - r * 0.52),
        (cx - r * 0.60, cy - r * 1.02),
        (cx + r * 0.02, cy - r * 1.10),
        (cx + r * 0.62, cy - r * 0.98),
        (cx + r * 0.64, cy - r * 0.28),
        (cx + r * 0.30, cy + r * 0.22),
        (cx + r * 0.02, cy + r * 0.46),
    ]
    d.line(hook, fill=out, width=w, joint="curve")
    # 下竖钩
    d.line([(cx + r * 0.02, cy + r * 0.46), (cx + r * 0.02, cy + r * 0.74)],
           fill=out, width=w)
    # 圆点
    pr = max(w * 0.62, r * 0.17)
    d.ellipse([cx + r * 0.02 - pr, cy + r * 1.00 - pr,
               cx + r * 0.02 + pr, cy + r * 1.00 + pr], fill=out)


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


# ── 主题默认值登记（模块导入时扫描一次）────────────────────────────
# 扫描所有模块级函数的 __defaults__，把等于颜色常量的默认值登记下来，
# 于是 set_theme() 能把它们整体换成新主题的色值。
def _register_theme_defaults() -> None:
    import inspect
    # 建立「当前色值字符串 → 语义名」的反查表，供逐个默认值比对
    cur = {}
    for sem, key in _SEM.items():
        cur[_active.get(key, "")] = sem
    for name, obj in list(globals().items()):
        if not (inspect.isfunction(obj) and obj.__module__ == __name__):
            continue
        try:
            inspect.signature(obj)
        except (TypeError, ValueError):
            continue
        defaults = obj.__defaults__ or ()
        for i, val in enumerate(defaults):
            if isinstance(val, str) and val in cur:
                _DEF_SLOTS.append((name, i, cur[val]))


_register_theme_defaults()

# 环境变量优先（WHITEBOARD_THEME=warm python make_boards.py 即可整批换肤）
import os as _os
if _os.environ.get("WHITEBOARD_THEME"):
    set_theme(_os.environ["WHITEBOARD_THEME"])


# ---------------------------------------------------------------- 正多边形（圆周率逼近）
def regular_polygon(d, cx, cy, r, n, rotate=-90, out=None, fill=None,
                    w=5, color_idx=None):
    """画内接于半径 r 的正 n 边形。rotate=-90 时顶点在正上方。

    n 边形的每条边对应圆心角 360/n，边长 = 2r·sin(π/n)，
    周长 = n · 2r·sin(π/n)，n→∞ 时趋近 2πr。
    """
    import math as _m
    out = out or C("ink")
    pts = []
    for i in range(n):
        a = _m.radians(rotate + i * 360.0 / n)
        pts.append((cx + r * _m.cos(a), cy + r * _m.sin(a)))
    d.polygon(pts, fill=fill, outline=out, width=w)
    return pts


def polygon_perimeter(r: float, n: int) -> float:
    """半径 r 的内接正 n 边形周长。"""
    import math as _m
    return n * 2 * r * _m.sin(_m.pi / n)


def circle_outline(d, cx, cy, r, out=None, w=4, dashed=False):
    """虚线圆：表示"理想的圆"，与逼近的多边形区分开。"""
    import math as _m
    out = out or C("muted")
    if not dashed:
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=out, width=w)
        return
    segs = 72
    for i in range(0, segs, 2):
        a1 = _m.radians(i * 360 / segs)
        a2 = _m.radians((i + 1) * 360 / segs)
        d.line([cx + r * _m.cos(a1), cy + r * _m.sin(a1),
                cx + r * _m.cos(a2), cy + r * _m.sin(a2)], fill=out, width=w)


def arch(d, cx, ytop, w, h, out=None, lw=6):
    """牌坊式建筑轮廓（画府/营造感）。"""
    out = out or C("ink")
    d.rectangle([cx - w / 2, ytop + h * 0.3, cx + w / 2, ytop + h], outline=out, width=lw)
    d.polygon([(cx - w / 2 - 14, ytop + h * 0.3), (cx, ytop),
               (cx + w / 2 + 14, ytop + h * 0.3)], outline=out, width=lw)
    d.rectangle([cx - w / 2 - 14, ytop + h * 0.26, cx + w / 2 + 14, ytop + h * 0.34],
                outline=out, width=lw)


def scroll(d, cx, cy, w, h, out=None, lw=5):
    """竹简/卷轴：呼应古代算术。"""
    out = out or C("ink")
    d.rectangle([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2],
                fill=C("yellowF"), outline=out, width=lw)
    for i in range(4):
        xx = cx - w / 2 + w * (i + 1) / 5
        d.line([xx, cy - h / 2 + 10, xx, cy + h / 2 - 10], fill=out, width=2)
