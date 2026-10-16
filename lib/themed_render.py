#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""themed_render.py — 给 whiteboard-animator 的成片注入底色（不改引擎源码）

═══ 为什么需要它 ═══

引擎的视频编码器把底色**三处硬编码为纯白 255**：

  video_encoding.py:91    white = np.ones((h,w,3), np.uint8) * 255
  video_encoding.py:132   frame_buf = np.full((h,w,3), 255, ...)
  video_encoding.py:178   255.0 + (color - 255.0) * a      # 淡入混合的底色

所以底色**只存在于 PNG**：PNG 阶段能通过连通域检查（灰度恰好 240），
但像素值根本进不了视频——实测底色从 gray 240 加深到 213，成片首帧仍是 (255,255,255)。

这意味着「只改 PNG 底色」这条路只能改到画布，改不了成片。

═══ 本模块的做法 ═══

不改 site-packages，改为**成片后整体染色**：

  1. 引擎照常渲染（纯白底线稿）
  2. ffmpeg 逐帧抽出为 PNG
  3. PIL 把「接近纯白」的像素替换成主题底色，图形与浅色填充原样保留
  4. ffmpeg 合成回视频

代价是逐帧过一遍磁盘（约 1~2倍渲染时间），换来的是：不碰引擎、引擎升级不受影响、
可随时回退。

用法：
    from themed_render import render_themed
    render_themed("v.mp4", "b/s01.png", theme="warm", total=6.0)

命令行：
    python lib/themed_render.py out.mp4 img.png --theme warm --total 6
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))
import theme as TH  # noqa: E402

# 只替换「足够接近纯白」的像素；浅色填充（gray 224~237）必须保留，
# 否则暖纸主题里那些浅黄/浅绿色块会一起被染掉。
WHITE_TOL = 250          # 三通道都 ≥250 才认为是"引擎刷出来的白"
# 但这会漏掉压缩后略低于 250 的白。折中：按灰度 ≥ WHITE_TOL_MIN 且色差小
WHITE_TOL_MIN = 246


def _find_ffmpeg() -> str:
    """优先用theme.ffmpeg_path()（已按 libx264 可用性排好优先级）。"""
    p = TH.ffmpeg_path()
    if p:
        return p
    raise FileNotFoundError(
        "找不到可用的 ffmpeg（需支持 libx264）。"
        "请装 ffmpeg 并加入 PATH，或在 lib/theme.py 的 FFMPEG_CANDIDATES 里登记路径。")


def tint_frame(arr: np.ndarray, paper: tuple[int, int, int]) -> np.ndarray:
    """把接近纯白的像素换成 paper，其余原样保留。"""
    out = arr.copy()
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    is_white = (r >= WHITE_TOL_MIN) & (g >= WHITE_TOL_MIN) & (b >= WHITE_TOL_MIN)
    out[is_white] = paper
    return out


def render_themed(out_path: str, image_path: str, theme: str = "whiteboard",
                  draw_end: float | None = None, total: float = 6.0,
                  fps: int = 20, bitrate: str = "900k",
                  ffmpeg_dir: str | None = None,
                  audio: str | None = None) -> str:
    """渲染一个带底色的分镜视频。返回输出路径。"""
    t = TH.get(theme)
    paper = TH.paper_rgb(t)
    if ffmpeg_dir:
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
    else:
        TH.setup_ffmpeg_env()
    ff = _find_ffmpeg()

    im = Image.open(image_path).convert("RGB")
    flat = Image.alpha_composite(
        Image.new("RGBA", im.size, "white"), im.convert("RGBA")).convert("RGB")
    arr = np.array(flat)

    from whiteboard_animator.animator import WhiteboardAnimator
    an = WhiteboardAnimator(fade_duration=0.06)
    raw = str(Path(out_path).with_suffix(".raw.mp4"))
    an.render_to_file(arr, total, total, raw, fps=fps, bitrate=bitrate)

    # 抽帧 → 染色 → 合成
    tmp = tempfile.mkdtemp(prefix="tint_")
    frames_dir = os.path.join(tmp, "f")
    os.makedirs(frames_dir, exist_ok=True)
    subprocess.run([ff, "-y", "-i", raw, "-vsync", "0",
                    os.path.join(frames_dir, "%05d.png")], capture_output=True)
    pngs = sorted(Path(frames_dir).glob("*.png"))
    if not pngs:
        raise RuntimeError(f"抽帧失败，检查 ffmpeg：{ff}")

    tinted_dir = os.path.join(tmp, "t")
    os.makedirs(tinted_dir, exist_ok=True)
    for i, p in enumerate(pngs):
        a = np.array(Image.open(p).convert("RGB"))
        Image.fromarray(tint_frame(a, paper)).save(
            os.path.join(tinted_dir, f"{i+1:05d}.png"))

    cmd = [ff, "-y", "-framerate", str(fps), "-i",
           os.path.join(tinted_dir, "%05d.png"),
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps)]
    if audio:
        cmd += ["-i", audio, "-c:a", "aac", "-shortest"]
    cmd += [out_path]
    r = subprocess.run(cmd, capture_output=True)
    if not Path(out_path).exists():
        raise RuntimeError("合成失败：" + r.stderr.decode("utf-8", "replace")[-300:])

    shutil.rmtree(tmp, ignore_errors=True)
    try:
        os.remove(raw)
    except OSError:
        pass
    return out_path


def tint_video(video_path: str, theme: str, ffmpeg_dir: str | None = None) -> str:
    """对一个**已渲染完成**的 mp4 做底色染色（视频流复制，音轨不变）。

    与 render_themed 的区别：这个函数不碰渲染，只处理成片，
    供 render_explainer.py 在每拍渲完后调用。-c:v copy 保证音画同步不受影响。
    """
    if ffmpeg_dir:
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
    else:
        TH.setup_ffmpeg_env()
    ff = _find_ffmpeg()
    paper = TH.paper_rgb(TH.get(theme))
    src = Path(video_path)
    tmpdir = tempfile.mkdtemp(prefix="tintv_")
    frames = os.path.join(tmpdir, "f")
    os.makedirs(frames, exist_ok=True)

    subprocess.run([ff, "-y", "-i", str(src), "-vsync", "0",
                    os.path.join(frames, "%05d.png")], capture_output=True)
    pngs = sorted(Path(frames).glob("*.png"))
    if not pngs:
        raise RuntimeError(f"抽帧失败：{src}")

    tinted = os.path.join(tmpdir, "t")
    os.makedirs(tinted, exist_ok=True)
    for i, p in enumerate(pngs):
        a = np.array(Image.open(p).convert("RGB"))
        Image.fromarray(tint_frame(a, paper)).save(
            os.path.join(tinted, f"{i+1:05d}.png"))

    out = src.with_suffix(".tinted.mp4")
    fps = _probe_fps(ff, str(src))
    r = subprocess.run(
        [ff, "-y", "-framerate", str(fps), "-i",
         os.path.join(tinted, "%05d.png"),
         "-i", str(src), "-map", "0:v", "-map", "1:a?",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy",
         str(out)], capture_output=True)
    if not out.exists():
        raise RuntimeError("染色合成失败：" + r.stderr.decode("utf-8", "replace")[-300:])
    out.replace(src)
    shutil.rmtree(tmpdir, ignore_errors=True)
    return video_path


def _probe_fps(ff: str, path: str) -> int:
    """读视频帧率，失败则退回 20（白板 skill 的默认档）。"""
    r = subprocess.run([ff.replace("ffmpeg", "ffprobe") if False else ff,
                        "-i", path], capture_output=True)
    txt = r.stderr.decode("utf-8", "replace")
    import re
    m = re.search(r"(\d+(?:\.\d+)?)\s*fps", txt)
    if m:
        try:
            return max(1, round(float(m.group(1))))
        except ValueError:
            pass
    return 20


def main() -> int:
    ap = argparse.ArgumentParser(description="带底色的白板渲染")
    ap.add_argument("out", help="输出 mp4")
    ap.add_argument("image", help="底图 png")
    ap.add_argument("--theme", default="whiteboard")
    ap.add_argument("--total", type=float, default=6.0)
    ap.add_argument("--fps", type=int, default=20)
    ap.add_argument("--audio", help="可选：旁白 mp3")
    ap.add_argument("--ffmpeg-dir", help="ffmpeg.exe 所在目录")
    a = ap.parse_args()
    render_themed(a.out, a.image, a.theme, total=a.total, fps=a.fps,
                  audio=a.audio, ffmpeg_dir=a.ffmpeg_dir)
    print(f"完成 -> {a.out}  主题={a.theme} 底色={TH.get(a.theme)['paper']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())