#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""audit_boards.py — 深度内容白板系列的共享组件与「防重叠审计」框架。

来源：《未来总统的物理课》系列（D:/story-skill/workspace/president-physics/）量产沉淀。
用户硬性要求：list 的文字与图标绝不重叠 → 本框架用「测量后绘制 + bbox 两两查重」
在构建期程序化保证，任何文字/图标重叠直接抛错，不靠人眼。

用法（每集 make_boards.py）：
    import sys, math
    sys.path.insert(0, r"D:/story-skill/.workbuddy/skills/whiteboard-explainer/lib")
    import audit_boards as AB
    AB.begin(__file__)                    # set_canvas(720,1280) + boards 目录
    img, d = AB.canvas()
    AB.title(d, "s01", "标题", 42)        # = mtext 居中 + 审计
    AB.mtext(d, "s01", 360, 300, "正文", 24, AB.BLUE, True)
    AB.li(d, "s01", 115, 250, 1, "列表项文字")   # 徽章+左对齐，防重叠
    AB.icon("s01", "xx", (x0, y0, x1, y1))       # 登记图形 bbox，文字不得压盖
    AB.audit("s01")                       # 场景收尾：两两查重，重叠即抛错
    AB.save(img, "s01", [(label, box(es), annotation), ...])
    AB.write_plan("plan.build.json", idea="...", gap=0.15)

纪律：
  1. 所有文字一律走 mtext/li/title；柱体、太阳、电池等图形一律 icon() 登记。
  2. 文字压图形=视觉事故 → 图形要登记；文字在图形内部（如徽章数字）=故意 → 不登记。
  3. 审计 pad=3px；溢出画布/容器、li 右越界、icon×text、text×text 全部抛 AssertionError。
  4. 抽帧目检仍不可省：斜向线条（激光束/曲线）穿字、图形骑缝 region box 不在审计范围。
"""
import math
import sys
from pathlib import Path

_SKILL = r"D:/story-skill/.workbuddy/skills/whiteboard-explainer/scripts"
_BIZNOTES = r"D:/story-skill/workspace/biznotes"
for _p in (_SKILL, _BIZNOTES):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import board_widgets as BW
from board_widgets import (INK, BLUE, GREEN, ORANGE, RED, GREY, PURPLE, WHITE,
                           YELLOW, BLUE_LT, GREEN_LT, YELLOW_LT, PINK, ORANGE_LT)
from lib_common import card, GREY_LT, PINK_LT, dashed, arrow_v  # noqa: F401

AUDIT_PAD = 3
_AUDIT: list = []


# ---------------------------------------------------------------- 框架核心
def begin(ep_file=None, w=720, h=1280):
    BW.set_canvas(w, h)
    out = Path(ep_file).resolve().parent / "boards" if ep_file else Path("boards")
    BW.set_out_dir(out)


def _hit(a, b, pad=AUDIT_PAD):
    return not (a[2] + pad <= b[0] or b[2] + pad <= a[0]
                or a[3] + pad <= b[1] or b[3] + pad <= a[1])


def mtext(d, sid, cx, cy, s, size=30, color=INK, bold=False, anchor="mm",
          fit=None, max_w=None):
    """测量后绘制：出画布/超容器/超宽即报错；登记 bbox 参与查重。"""
    f = BW._font(size, bold)
    l, t, r, b = d.textbbox((cx, cy), s, font=f, anchor=anchor)
    where = f"[{sid}]「{s}」bbox=({l:.0f},{t:.0f},{r:.0f},{b:.0f})"
    if l < 6 or t < 6 or r > BW.W - 6 or b > BW.H - 6:
        raise AssertionError(where + " 出画布")
    if max_w is not None and (r - l) > max_w:
        raise AssertionError(where + f" 宽{r - l:.0f}超限{max_w}")
    if fit is not None:
        x0, y0, x1, y1 = fit
        if l < x0 + 8 or t < y0 + 5 or r > x1 - 8 or b > y1 - 5:
            raise AssertionError(where + f" 溢出容器{fit}")
    d.text((cx, cy), s, font=f, fill=color, anchor=anchor)
    _AUDIT.append((sid, "text", s[:14], (l, t, r, b)))


def li(d, sid, x_icon, y, idx, s, x_limit=672, size=30, color=INK, gap=28):
    """列表行：数字徽章 + 左对齐文字（用户点名要求的防重叠列表）。"""
    r = 24
    BW.num_badge(d, x_icon, y, idx, out=color)
    _AUDIT.append((sid, "icon", f"badge{idx}", (x_icon - r, y - r, x_icon + r, y + r)))
    tx = x_icon + r + gap
    f = BW._font(size, True)
    l, t, rr, b = d.textbbox((tx, y), s, font=f, anchor="lm")
    if l < x_icon + r + 12:
        raise AssertionError(f"[{sid}] list#{idx} 文字距徽章过近")
    if rr > x_limit:
        raise AssertionError(f"[{sid}] list#{idx}「{s}」右溢出 {rr:.0f}>{x_limit}")
    d.text((tx, y), s, font=f, fill=color, anchor="lm")
    _AUDIT.append((sid, "text", s[:14], (l, t, rr, b)))


def title(d, sid, s, size=42, y=95, color=INK):
    mtext(d, sid, BW.W // 2, y, s, size, color, True)


def icon(sid, name, bbox):
    _AUDIT.append((sid, "icon", name, bbox))


def audit(sid):
    items = [a for a in _AUDIT if a[0] == sid]
    bad = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            _, k1, n1, b1 = items[i]
            _, k2, n2, b2 = items[j]
            if _hit(b1, b2):
                bad.append(f"  {k1}「{n1}」{tuple(round(v) for v in b1)} × "
                           f"{k2}「{n2}」{tuple(round(v) for v in b2)}")
    if bad:
        raise AssertionError(f"[{sid}] 检出 {len(bad)} 处重叠:\n" + "\n".join(bad))
    _AUDIT[:] = [a for a in _AUDIT if a[0] != sid]
    print(f"[{sid}] 防重叠审计通过 · {len(items)} 个受检元素")


# ---------------------------------------------------------------- 绘图组件
def bubble(d, sid, cx, cy, w, h, lines, size=22, col=INK, tail_dx=0):
    """对话气泡：内部文字走 mtext(fit=气泡内框)。"""
    x0, y0, x1, y1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
    d.rounded_rectangle([x0, y0, x1, y1], radius=20, fill=WHITE, outline=col, width=5)
    d.polygon([(cx - 16 + tail_dx, y1 - 2), (cx + 16 + tail_dx, y1 - 2),
               (cx + tail_dx, y1 + 26)], fill=WHITE, outline=col)
    d.line([cx - 14 + tail_dx, y1 - 3, cx + 14 + tail_dx, y1 - 3], fill=WHITE, width=7)
    for i, ln in enumerate(lines):
        ly = cy + (i - (len(lines) - 1) / 2) * (size + 16)
        mtext(d, sid, cx, ly, ln, size=size, color=col, bold=True,
              anchor="mm", fit=(x0, y0, x1, y1))


def sun(d, sid, cx, cy, r, col=ORANGE):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=YELLOW, outline=col, width=5)
    for k in range(8):
        a = math.radians(k * 45)
        d.line([cx + (r + 8) * math.cos(a), cy + (r + 8) * math.sin(a),
                cx + (r + 30) * math.cos(a), cy + (r + 30) * math.sin(a)],
               fill=col, width=5)
    icon(sid, "sun", (cx - r - 30, cy - r - 30, cx + r + 30, cy + r + 30))


def bulb(d, sid, cx, cy, r):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=YELLOW, outline=ORANGE, width=4)
    for i, yy in enumerate((5, 12)):
        d.line([cx - 10 + i * 2, cy + r + yy, cx + 10 - i * 2, cy + r + yy],
               fill=GREY, width=4)
    for k in range(6):
        a = math.radians(210 + k * 24)
        d.line([cx + (r + 6) * math.cos(a), cy + (r + 6) * math.sin(a),
                cx + (r + 22) * math.cos(a), cy + (r + 22) * math.sin(a)],
               fill=ORANGE, width=4)
    icon(sid, "bulb", (cx - r - 24, cy - r - 24, cx + r + 24, cy + r + 30))


def cake(d, sid, cx, base, w, h):
    d.rounded_rectangle([cx - w / 2, base - h, cx + w / 2, base], radius=10,
                        fill=PINK_LT, outline=INK, width=4)
    d.ellipse([cx - w / 2 - 4, base - h - 12, cx + w / 2 + 4, base - h + 12],
              fill=PINK, outline=INK, width=4)
    for dx in (-w * 0.25, 0, w * 0.25):
        d.line([cx + dx, base - h - 10, cx + dx, base - h - 44], fill=BLUE, width=4)
        d.ellipse([cx + dx - 5, base - h - 56, cx + dx + 5, base - h - 44], fill=ORANGE)
    icon(sid, "cake", (cx - w / 2 - 6, base - h - 60, cx + w / 2 + 6, base))


def reactor(d, sid, cx, base, w, h):
    """核电站安全壳：矩形厂房 + 穹顶 + 门 + 蒸汽（比冷却塔更易识别）。"""
    d.rectangle([cx - w / 2, base - h * 0.45, cx + w / 2, base],
                fill=WHITE, outline=INK, width=5)
    d.arc([cx - w / 2, base - h, cx + w / 2, base + h * 0.1], 180, 360,
          fill=INK, width=5)
    d.rectangle([cx - 16, base - 36, cx + 16, base], fill=WHITE, outline=INK, width=4)
    for dxx, dyy, rr in ((-12, -h - 4, 9), (14, -h - 22, 12)):
        d.ellipse([cx + dxx - rr, base + dyy - rr, cx + dxx + rr, base + dyy + rr],
                  fill=GREY_LT)
    icon(sid, "reactor", (cx - w / 2 - 10, base - h - 38, cx + w / 2 + 10, base))


def turbine(d, sid, hx, hy, r, base):
    """风机：一叶朝上、两叶斜下（经典位形，避免叶片与塔杆重合）。"""
    for a in (270, 30, 150):
        ang = math.radians(a)
        tx, ty = hx + r * math.cos(ang), hy + r * math.sin(ang)
        d.line([hx, hy, tx, ty], fill=INK, width=11)
        d.line([hx + 8 * math.cos(ang + 1.35), hy + 8 * math.sin(ang + 1.35),
                tx, ty], fill=WHITE, width=4)
    d.ellipse([hx - 15, hy - 15, hx + 15, hy + 15], fill=YELLOW, outline=INK, width=5)
    d.line([hx, hy + 12, hx, base], fill=INK, width=11)
    d.line([hx - 70, base, hx + 70, base], fill=INK, width=7)
    icon(sid, "turbine", (hx - r - 15, hy - r - 15, hx + r + 15, base + 8))


def battery(d, sid, x0, y0, x1, y1):
    d.rounded_rectangle([x0, y0, x1, y1], radius=12, fill=GREEN_LT,
                        outline=INK, width=6)
    d.rectangle([(x0 + x1) / 2 - 30, y0 - 16, (x0 + x1) / 2 + 30, y0],
                fill=GREY_LT, outline=INK, width=4)
    for frac in (1 / 3, 2 / 3):
        dx = x0 + (x1 - x0) * frac
        d.line([dx, y0 + 6, dx, y1 - 6], fill=INK, width=4)
    icon(sid, "battery", (x0 - 8, y0 - 22, x1 + 8, y1 + 8))


def panel(d, cx, cy, w=60, h=22):
    d.polygon([(cx - w / 2, cy + h / 2), (cx + w / 2, cy - h / 2),
               (cx + w / 2, cy - h / 2 + 9), (cx - w / 2, cy + h / 2 + 9)],
              fill=BLUE_LT, outline=INK, width=3)
    d.line([cx, cy + h / 2 + 9, cx, cy + h / 2 + 26], fill=INK, width=3)


def sheep(d, sid, cx, cy):
    d.ellipse([cx - 30, cy - 16, cx + 26, cy + 16], fill=WHITE, outline=INK, width=4)
    d.ellipse([cx + 22, cy - 22, cx + 44, cy - 2], fill=WHITE, outline=INK, width=4)
    for lx in (-20, -8, 8, 20):
        d.line([cx + lx, cy + 14, cx + lx, cy + 30], fill=INK, width=4)
    icon(sid, "sheep", (cx - 32, cy - 24, cx + 46, cy + 32))


def grass(d, cx, cy, s=16):
    for dx in (-6, 0, 6):
        d.line([cx + dx, cy, cx + dx * 1.6, cy - s], fill=GREEN, width=3)


def beam(d, cx, cy, ang, r_in, r_out):
    a = math.radians(ang)
    x0, y0 = cx + r_in * math.cos(a), cy + r_in * math.sin(a)
    x1, y1 = cx + r_out * math.cos(a), cy + r_out * math.sin(a)
    d.line([x0, y0, x1, y1], fill=BLUE, width=6)
    d.polygon([(x0, y0), (x0 + 16 * math.cos(a - 0.4), y0 + 16 * math.sin(a - 0.4)),
               (x0 + 16 * math.cos(a + 0.4), y0 + 16 * math.sin(a + 0.4))], fill=BLUE)


def coal(d, cx, base, s):
    d.polygon([(cx - s, base), (cx - s * 0.7, base - s * 0.9), (cx + s * 0.1, base - s),
               (cx + s, base - s * 0.35), (cx + s * 0.8, base)], fill=(78, 78, 82))


def bar_row(d, sid, y, lab, w, val, vcol=INK, col=BLUE_LT, x0=250, lab_x=235,
            bar_h=44, size=22):
    """天梯/对比横向条：label 右对齐 + 条 + 值（全走 mtext，防重叠）。"""
    mtext(d, sid, lab_x, y + bar_h / 2, lab, 24, INK, True, anchor="rm")
    d.rectangle([x0, y, x0 + w, y + bar_h], fill=col, outline=INK, width=4)
    icon(sid, f"bar{lab}", (x0, y, x0 + w, y + bar_h))
    mtext(d, sid, x0 + w + 14, y + bar_h / 2, val, size, vcol, True, anchor="lm")


# save / write_plan 透传
save = BW.save
write_plan = BW.write_plan
canvas = BW.canvas
