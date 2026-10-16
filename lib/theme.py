#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""theme.py — 白板配色主题表（路线 A：只换配色与底色，不换渲染引擎）

═══ 为什么底色必须是「灰度恰好 240 的纯色」═══

whiteboard-animator 引擎有两条硬编码规则（实测确认，非推测）：

  1. animator.py:1324    r[gray > 240] = [255, 255, 255]      # 近白像素刷成纯白
  2. _find_components     只有灰度 < 240 的像素参与连通域       # 更暗的底色会被当成"内容"

逐灰度扫描的实测结果（300×300 画布 + 一条黑线）：

  gray 235~239  → 底色与图形焊成一个全屏连通域，线条被吞掉    ✗
  gray 240      → 底色被忽略，线条正常识别                   ✓ 唯一可用值
  gray 241~255  → 底色被刷成纯白（255 本来也是白，无害）      ✓ 但等于没换色

所以 240 是唯一的黄金值：不被刷白（保留原色），也不被当内容。

更严格的两条实现纪律（同样实测）：

  · 不能用渐变。任何跨过 240 的渐变（哪怕只有 232→242）都会让底色
    掉进 <240 的区间被当成内容。
  · 不能加噪点。±3 的噪点会产生 23606 个连通域，渲染直接失败。

→ 因此本文件的底色一律是**纯色**。frametell 那种"SVG 噪声滤镜 + 径向渐变"
  的质感在本引擎下无法实现，只能靠画在底上的图形去营造。

═══ 怎么加新主题 ═══

1. 复制下面任意一段，改 PAPER 的六个分量，务必让灰度命中 240
2. 跑tools/pick_paper.py 验证（它会直接调用引擎的 _enforce_white_bg 实测）
3. 底色改完再调 INK / 各语义色；注意填充色要够深（灰度 < 235）才不被吞

调色板键名与 frametell 引擎保持一致（ink/soft/muted/faint/paper +色名F），
这样日后若迁移到 frametell 的渲染后端，组件代码可以零改动复用。
"""
from __future__ import annotations

# ── 底色求解：给定 RGB 三元组返回灰度恰好 240 的最近色──────────────
# 灰度是 0.299R + 0.587G + 0.114B 的四舍五入（BT.601）。
# 关键：要的是「原色的最小偏移」，不是「任意一个命中值」。
# 早期实现沿单个通道从 0 递增搜，第一个命中往往把颜色拽向黄/蓝，
# 于是暖米变成 #FCF4B8 这种明显发黄的值。这里改成在原色附近
# ±12 的邻域内遍历全部通道，按偏移绝对值之和取最小者，色相才不会跑。
def solve_paper(r: int, g: int, b: int, target: int = 240,
                window: int = 12) -> tuple[int, int, int]:
    """把 (r,g,b) 调整到灰度恰好 target，在最小偏移内尽量保留原色。"""
    best: tuple[int, int, int, int] | None = None   # (偏移和, r, g, b)
    for dr in range(-window, window + 1):
        rr = r + dr
        if not 0 <= rr <= 255:
            continue
        # 先算出当前 rr 对应的灰度需求，再解b；b 无解就让 g 参与补偿
        for dg in range(-window, window + 1):
            gg = g + dg
            if not 0 <= gg <= 255:
                continue
            need = (target - 0.299 * rr - 0.587 * gg) / 0.114
            bb = int(round(need))
            if not 0 <= bb <= 255:
                continue
            # 灰度是四舍五入，允许 ±0.5 的容差落在 target 上
            if int(round(0.299 * rr + 0.587 * gg + 0.114 * bb)) != target:
                continue
            cost = abs(dr) + abs(dg) + abs(bb - b)
            if best is None or cost < best[0]:
                best = (cost, rr, gg, bb)
            if cost == 0:          # 原色本来就命中，直接用
                return rr, gg, bb
    return (best[1], best[2], best[3]) if best else (240, 240, 240)


def _p(r: int, g: int, b: int) -> str:
    rr, gg, bb = solve_paper(r, g, b)
    return f"#{rr:02X}{gg:02X}{bb:02X}"


# ── 主题表 ────────────────────────────────────────────────────────
# paper  : 底色（必须 gray==240 的纯色）
# ink    : 主线条色（frametell:黑记号笔）
# soft   : 次要线条/ 弱化元素
# muted  : 说明文字
# faint  : 最弱的辅助线
# xxx    : 语义色（强调）；xxxF:该色向 paper 混合的浅填充
# 语义沿用 frametell：red=问题/代价 green=正确/收益 blue=结构/标签
#                     orange=要强调的数字 yellow=高亮  purple=次要强调
THEMES: dict[str, dict] = {
    # ── 默认：近白马克笔（保持原有观感，零回归风险）──────────────
    "whiteboard": {
        "label": "白板马克笔",
        "desc": "近白底 + 黑色粗记号笔 + 四色马克笔。原默认风格。",
        "paper": _p(252, 252, 250),
        "ink": "#1E2226",
        "soft": "#4B5158",
        "muted": "#8C939B",
        "faint": "#CDD2D7",
        "red": "#D0342C", "redF": "#F7D9D6",
        "orange": "#E5762A", "orangeF": "#FBE3D2",
        "green": "#1E8A4A", "greenF": "#D6EEDD",
        "blue": "#1F5DBA", "blueF": "#D6E2F6",
        "purple": "#8A3F7E", "purpleF": "#EFD9E8",
        "yellow": "#F6CB1F", "yellowF": "#FBEFC0",
        "font": "regular",
    },

    # ── 暖纸：知识科普首选，温和耐看──────────────────────────────
    "warm": {
        "label": "暖纸讲义",
        "desc": "米黄纸底 + 深棕墨线 + 赭红/芥黄/鼠尾草绿。低对比、像讲义。",
        "paper": _p(252, 244, 228),
        "ink": "#3A2E28",
        "soft": "#6B5A4E",
        "muted": "#7E6B5C",
        "faint": "#D8CBB8",
        "red": "#C8603C", "redF": "#F5DCCB",
        "orange": "#C98A2E", "orangeF": "#F7E6C4",
        "green": "#6E8F6A", "greenF": "#DFE9D8",
        "blue": "#3A6E72", "blueF": "#D6E6E4",
        "purple": "#8A5F70", "purpleF": "#EDDCE0",
        "yellow": "#E0B24A", "yellowF": "#F7EBC8",
        "font": "regular",
    },

    # ── 冷调：技术/代码讲解，冷静克制──────────────────────────────
    # 注意 muted 不能用「和底色同色相的浅蓝灰」（如 #8496A8 配 #EAF1FB）：
    # 实测会让30px 中文小字被二值化切成 98 个碎块，连通域直接爆掉。
    # 规则：辅助文字色要够深（灰度 ≲ 125）且色相拉开，宁可偏中性。
    "cool": {
        "label": "冷调讲义",
        "desc": "冷灰蓝底 + 墨蓝线 + 钢蓝/青灰。清爽、像技术文档。",
        "paper": _p(234, 240, 252),
        "ink": "#1F2A38",
        "soft": "#46566A",
        "muted": "#6B7A8C",
        "faint": "#B8C6D6",
        "red": "#C0483C", "redF": "#F5DAD6",
        "orange": "#C87A2E", "orangeF": "#F7E4CE",
        "green": "#2E7D5B", "greenF": "#D6E9DF",
        "blue": "#2A5FA8", "blueF": "#D5E1F5",
        "purple": "#6A4E8C", "purpleF": "#E4DCF0",
        "yellow": "#C9A93A", "yellowF": "#F5EECA",
        "font": "regular",
    },

    # ── 薄荷：轻松活泼，适合轻量科普/生活类─────────────────────
    "mint": {
        "label": "薄荷讲义",
        "desc": "极浅青底 + 墨青线 + 翠绿/珊瑚。清爽透气。",
        "paper": _p(232, 248, 244),
        "ink": "#16342F",
        "soft": "#3E6259",
        "muted": "#55736C",
        "faint": "#C4E0D8",
        "red": "#D2503F", "redF": "#F8DAD5",
        "orange": "#D07A2C", "orangeF": "#F8E4CD",
        "green": "#1F8A63", "greenF": "#D2EADD",
        "blue": "#2668A8", "blueF": "#D4E2F4",
        "purple": "#7A4E8E", "purpleF": "#E7DCF0",
        "yellow": "#BFA032", "yellowF": "#F4EDC6",
        "font": "regular",
    },

    # ── 樱粉：人文/情感/生活叙事────────────────────────────────
    "sakura": {
        "label": "樱粉讲义",
        "desc": "浅粉底 + 深梅墨线 + 玫红/藕荷。柔和、有温度。",
        "paper": _p(252, 236, 238),
        "ink": "#3A2430",
        "soft": "#6E4A58",
        "muted": "#846472",
        "faint": "#E4CCD4",
        "red": "#C4445E", "redF": "#F6D8DE",
        "orange": "#C87A3E", "orangeF": "#F6E2CC",
        "green": "#5E8A62", "greenF": "#DCE9DA",
        "blue": "#4A6A9E", "blueF": "#DCE2F0",
        "purple": "#8A4E82", "purpleF": "#EFD8EA",
        "yellow": "#C9A83E", "yellowF": "#F6EDC8",
        "font": "regular",
    },
}

DEFAULT_THEME = "whiteboard"


def get(name: str | None) -> dict:
    """按名字取主题；未知名字回落到默认主题（并给出提示）。"""
    if not name:
        return THEMES[DEFAULT_THEME]
    key = name.strip().lower()
    if key not in THEMES:
        import sys
        print(f"[theme] 未知主题 {name!r}，可用：{', '.join(THEMES)}；"
              f"已回落到 {DEFAULT_THEME}", file=sys.stderr)
        return THEMES[DEFAULT_THEME]
    return THEMES[key]


def names() -> list[str]:
    return list(THEMES)


def paper_rgb(theme: dict) -> tuple[int, int, int]:
    h = theme["paper"].lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

# ── ffmpeg 定位（引擎与染色管线都要用）────────────────────────────
# 本机 PATH / 注册表里登记的 ffmpeg 目录已失效
#（D:\ffmpeg-2025-10-01-git-1a02412170-essentials_build 不存在），
# 真正可用的是 ShadowBot 自带的那份：2016 版、有 libx264，但**没有 tpad 滤镜**
#（引擎的收尾延帧已用 draw_end == total 规避）。
# 注意：剪映自带的 ffmpeg **缺 libx264**，会渲染失败，所以放在最后。
FFMPEG_CANDIDATES = [
    r"D:\ffmpeg\bin\ffmpeg.exe",
    r"D:\ffmpeg-2025-10-01-git-1a02412170-essentials_build\bin\ffmpeg.exe",
    r"D:\Program Files (x86)\ShadowBot\shadowbot-5.21.17\ffmpeg.exe",
    r"D:\Program Files (x86)\ShadowBot\shadowbot-5.21.27\ffmpeg.exe",
    r"D:\JianyingPro\11.5.0.14471\ffmpeg.exe",
]


def ffmpeg_path() -> str | None:
    """找到可用的 ffmpeg.exe；找不到返回 None。"""
    from shutil import which
    from pathlib import Path as _P
    p = which("ffmpeg")
    if p and "ffmpeg-2025-10-01" not in p:      # 跳过失效登记项
        return p
    for c in FFMPEG_CANDIDATES:
        if _P(c).exists():
            return c
    return None


def setup_ffmpeg_env() -> str | None:
    """把找到的 ffmpeg 目录塞进 PATH，让引擎的裸 `ffmpeg` 调用能用。"""
    import os
    p = ffmpeg_path()
    if p:
        os.environ["PATH"] = os.path.dirname(p) + os.pathsep + os.environ.get("PATH", "")
    return p


def patch_no_tpad() -> bool:
    """禁用引擎的 tpad 延帧路径（老版 ffmpeg 缺该滤镜）。

    引擎 `video_encoding.encode_timing_video` 里：
        hold_dur = max(total_duration - draw_end - fade_dur, 0)
        use_tpad = hold_dur > 0.5        # → True 时用 ffmpeg tpad 滤镜克隆末帧
    只要 draw_end < total（有旁白时必然如此，因为要留收尾）就会走 tpad，
    而 ShadowBot 那份 2016 版 ffmpeg **没有 tpad**，直接报
    "No such filter: 'tpad'"。

    这里把 `encode_timing_video` 换成一个 draw_end == total_duration 的薄包装：
    让引擎把整段时间都当"绘制期"，用管道逐帧写出，不用任何滤镜。
    代价是收尾那段会逐帧重写（慢一点），换来的是跨ffmpeg 版本都能跑。
    """
    try:
        from whiteboard_animator import video_encoding as ve
    except ImportError:
        return False
    if getattr(ve, "_no_tpad_patched", False):
        return True

    orig = ve.encode_timing_video

    def patched(img_array, timing, draw_end, total_duration, fade_dur,
                output_path, *a, **kw):
        # 把绘制期拉满整段 → hold_dur 变0 → 引擎不调用 tpad
        return orig(img_array, timing, total_duration, total_duration,
                    fade_dur, output_path, *a, **kw)

    ve.encode_timing_video = patched
    ve._no_tpad_patched = True
    # 动画器模块里是 `from .video_encoding import encode_timing_video`，
    # 所以还要替换 animator 模块内的引用
    try:
        from whiteboard_animator import animator as an
        if hasattr(an, "encode_timing_video"):
            an.encode_timing_video = patched
    except ImportError:
        pass
    return True
