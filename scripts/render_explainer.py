#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""render_explainer.py — 白板讲解动画渲染器

输入：plan.json（每拍：白板图 + 音频 + region 绘制窗口）
输出：每拍 mp4 → concat 成片

三种音画对齐档位，自动降级：
  1. 精确档  region 写了 start/end（来自 LRC/逐句 TTS 真实时间戳）→ 帧级"讲到哪画到哪"
  2. 估算档  region 只有 annotation 文本 → 按字符数 70% / 面积 30% 分配窗口
  3. 均分档  没有 regions → 引擎全局启发式，前 70% 时间画完

用法：
  python scripts/render_explainer.py plan.json --out out/eclipse.mp4
  python scripts/render_explainer.py plan.json --out out/x.mp4 --only s01 --force
  python scripts/render_explainer.py plan.json --dry-run
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from user_gates import require

import numpy as np
from PIL import Image

try:
    from whiteboard_animator import WhiteboardAnimator
except ImportError:  # pragma: no cover
    sys.exit(
        "未找到 whiteboard_animator。请先跑：\n"
        "  scripts/setup.sh        # Linux / macOS / Git Bash\n"
        "  scripts/setup.ps1       # Windows PowerShell\n"
        "或在已激活 venv 里安装：\n"
        "  pip install 'whiteboard-animator==0.1.1'\n"
    )

QUALITY = {
    "low": {"fps": 20, "bitrate": "500k"},
    "medium": {"fps": 24, "bitrate": "1500k"},
    "high": {"fps": 24, "bitrate": "3000k"},
}

# 绘制预算：占音频总时长的比例，剩下的时间保留已完成画面（呼吸/收尾）
DRAW_BUDGET = 0.75
# 单个 region 窗口的最小秒数，太窄会让引擎装不下绘制量而 RuntimeError
MIN_WINDOW = 0.6
# 分配窗口时字符数 vs 面积 的权重（与引擎内置策略一致）
NARRATION_WEIGHT = 0.7


def log(msg: str) -> None:
    print(msg, flush=True)


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    """Windows 中文路径安全：所有 subprocess 显式 utf-8。"""
    return subprocess.run(
        cmd, check=True, capture_output=True,
        encoding="utf-8", errors="replace",
    )


def probe_duration(path: Path) -> float:
    """读媒体时长。优先 ffprobe；本机没装 ffprobe 时退回 ffmpeg 解析。"""
    try:
        out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                   "-of", "csv=p=0", str(path)])
        return _check_duration(float(out.stdout.strip()), path)
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    # 兜底：用 ffmpeg 读 stderr 里的 Duration
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
    import theme as _t
    _t.setup_ffmpeg_env()
    ff = _t.ffmpeg_path()
    if not ff:
        raise FileNotFoundError("需要 ffprobe 或 ffmpeg 才能读时长，两者都没找到")
    r = subprocess.run([ff, "-i", str(path)], capture_output=True, encoding="utf-8",
                       errors="replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", r.stderr)
    if not m:
        raise ValueError(f"无法读取时长: {path}")
    h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return _check_duration(h * 3600 + mi * 60 + s, path)


def _check_duration(duration: float, path: Path) -> float:
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(f"时长非法: {path} -> {duration}")
    return duration


# --------------------------------------------------------------------------
# region 窗口计算
# --------------------------------------------------------------------------

def normalize_box(region: dict) -> dict:
    """把单个 box 统一成 {ymin,xmin,ymax,xmax} 归一化 0-1000 字典。

    接受：box: {ymin,xmin,ymax,xmax} / [ymin,xmin,ymax,xmax] / box_2d。
    """
    box = region.get("box")
    if box is None:
        box = region.get("box_2d")
    if box is None:
        raise ValueError(f"region '{region.get('label')}' 缺少 box 或 box_2d")
    if isinstance(box, dict):
        keys = ("ymin", "xmin", "ymax", "xmax")
        missing = [k for k in keys if k not in box]
        if missing:
            raise ValueError(f"region '{region.get('label')}' box 缺字段: {missing}")
        return {k: int(box[k]) for k in keys}
    if isinstance(box, (list, tuple)) and len(box) == 4:
        ymin, xmin, ymax, xmax = [int(v) for v in box]
        return {"ymin": ymin, "xmin": xmin, "ymax": ymax, "xmax": xmax}
    raise ValueError(f"region '{region.get('label')}' box 格式无法识别: {box!r}")


def region_boxes(region: dict) -> list[dict]:
    """region 的 box 支持单个或数组，统一返回归一化 box 列表。"""
    box = region.get("box")
    raw = region.get("box_2d") if box is None else box
    if raw is None:
        raise ValueError(f"region '{region.get('label')}' 缺少 box 或 box_2d")
    items = raw if isinstance(raw, list) and raw and isinstance(raw[0], (dict, list, tuple)) else [raw]
    fake = {"label": region.get("label"), "box": items[0]}
    if len(items) > 1:
        return [normalize_box({"label": region.get("label"), "box": b}) for b in items]
    return [normalize_box(fake)]


def box_area(box: dict) -> int:
    return max((box["xmax"] - box["xmin"]) * (box["ymax"] - box["ymin"]), 1)


def _overlap(a: dict, b: dict) -> float:
    """两个 0-1000 归一化 box 的交叠面积（对 a 的占比）。"""
    ix = max(0, min(a["xmax"], b["xmax"]) - max(a["xmin"], b["xmin"]))
    iy = max(0, min(a["ymax"], b["ymax"]) - max(a["ymin"], b["ymin"]))
    return ix * iy / max(box_area(a), 1)


def build_windows(regions: list[dict], total: float) -> list[dict]:
    """给每个 region 算出 [start, end) 绘制窗口。

    - 有 cue（start/end，来自 build_narration 的真实时间戳）→ 精确档
    - 无 cue 且无 annotation 的纯图形 region → 并入与其空间重叠最大的
      cue 窗口，和那段讲解同时画出（图形属于那段话的一部分）
    - 全部无 cue → 按 annotation 字符数与面积加权估算窗口
    """
    cued = [r for r in regions if r.get("start") is not None and r.get("end") is not None]
    if cued:
        windows = []
        for r in sorted(cued, key=lambda x: float(x["start"])):
            windows.append({
                "boxes": region_boxes(r),
                "start": float(r["start"]),
                "end": float(r["end"]),
            })
        for r in regions:
            if r.get("start") is not None:
                continue
            boxes = region_boxes(r)
            best_w, best_score = None, 0.0
            for w in windows:
                for b in boxes:
                    for b2 in w["boxes"]:
                        score = _overlap(b, b2)
                        if score > best_score:
                            best_w, best_score = w, score
            (best_w or windows[-1])["boxes"].extend(boxes)
        return windows

    ordered = sorted(regions, key=lambda r: r.get("reveal_order", 10_000))
    chars = [len(str(r.get("annotation") or "").strip()) for r in ordered]
    areas = [sum(box_area(b) for b in region_boxes(r)) for r in ordered]
    total_chars, total_area = sum(chars), sum(areas)

    shares = []
    for c, a in zip(chars, areas):
        if total_chars:
            shares.append(NARRATION_WEIGHT * (c / total_chars)
                          + (1 - NARRATION_WEIGHT) * (a / total_area))
        else:
            shares.append(a / total_area)
    share_sum = sum(shares) or 1.0

    budget = DRAW_BUDGET * total
    windows, cursor = [], 0.0
    for region, share in zip(ordered, shares):
        duration = max(budget * share / share_sum, MIN_WINDOW)
        windows.append({
            "boxes": region_boxes(region),
            "start": round(cursor, 3),
            "end": round(cursor + duration, 3),
        })
        cursor += duration
    return windows


def widen(windows: list[dict], factor: float, total: float) -> list[dict]:
    """窗口整体放大（引擎装不下绘制量时的自动重试策略）。"""
    out = []
    for w in windows:
        start = w["start"] / factor
        end = min(w["end"] * factor, total * 0.97)
        out.append({"boxes": w["boxes"], "start": round(start, 3), "end": round(end, 3)})
    return out


# --------------------------------------------------------------------------
# 单拍渲染
# --------------------------------------------------------------------------

def render_scene(scene: dict, root: Path, out_dir: Path, quality: str,
                 animator: WhiteboardAnimator | None, force: bool) -> tuple[Path, float]:
    sid = scene["id"]
    scene_out = out_dir / f"{sid}.mp4"

    image_path = root / scene["image"]
    if not image_path.is_file():
        raise FileNotFoundError(f"[{sid}] 图不存在: {image_path}")

    audio_path = None
    if scene.get("audio"):
        audio_path = root / scene["audio"]
        if not audio_path.is_file():
            raise FileNotFoundError(f"[{sid}] 音频不存在: {audio_path}")

    if audio_path:
        total = probe_duration(audio_path)
    else:
        total = float(scene.get("duration") or 8.0)
    if scene.get("duration_override"):
        total = float(scene["duration_override"])

    if scene_out.exists() and not force:
        log(f"  [{sid}] 已存在，跳过（--force 可重渲）")
        return scene_out, total

    with Image.open(image_path) as im:
        rgba = im.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, "white")
        img = np.array(Image.alpha_composite(bg, rgba).convert("RGB"))

    settings = QUALITY.get(quality, QUALITY["medium"])
    fps, bitrate = settings["fps"], settings["bitrate"]

    regions = scene.get("regions") or []
    element_plan = build_windows(regions, total) if regions else None
    need_plan = element_plan is not None
    animator = animator or WhiteboardAnimator(fade_duration=0.06 if need_plan else 0.12)
    if (animator.fade_duration == 0.12) == need_plan:
        animator = WhiteboardAnimator(fade_duration=0.06 if need_plan else 0.12)

    video_only = out_dir / f"{sid}.video_only.mp4"
    last_error = None
    for attempt in range(4):
        try:
            animator.render_to_file(
                img, total * DRAW_BUDGET, total, str(video_only),
                fps=fps, bitrate=bitrate,
                element_plan=(element_plan if attempt == 0 else widen(element_plan, 1 + 0.15 * attempt, total)),
            )
            last_error = None
            break
        except RuntimeError as exc:
            last_error = exc
            log(f"  [{sid}] 窗口过窄（{exc}），自动放宽 {int(15 * (attempt + 1))}% 重试")
    if last_error:
        raise last_error

    if audio_path is None:
        video_only.replace(scene_out)
    else:
        run(["ffmpeg", "-y", "-i", str(video_only), "-i", str(audio_path),
             "-c:v", "copy", "-c:a", "aac", "-shortest", str(scene_out)])
    try:
        video_only.unlink()
    except OSError:
        pass

    # 换主题时，成片后再整体染色（引擎只认纯白，底色进不了帧缓冲）
    if globals().get("_THEME_NAME") and globals()["_THEME_NAME"] != "whiteboard":
        from themed_render import tint_video
        tint_video(str(scene_out), globals()["_THEME_NAME"])
        log(f"  [{sid}] 已按主题 {_THEME_NAME} 染色底色")

    total = probe_duration(scene_out)
    return scene_out, total


def concatenate(parts: list[Path], output: Path) -> None:
    if len(parts) == 1:
        if parts[0].resolve() != output.resolve():
            run(["ffmpeg", "-y", "-i", str(parts[0]), "-c", "copy", str(output)])
        return
    concat_list = output.parent / (output.name + ".concat.txt")
    try:
        concat_list.write_text(
            "".join(f"file '{p.resolve().as_posix()}'\n" for p in parts),
            encoding="utf-8",
        )
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", str(concat_list), "-c", "copy", str(output)])
    finally:
        if concat_list.exists():
            concat_list.unlink()


def main() -> int:
    ap = argparse.ArgumentParser(description="白板讲解动画渲染器")
    ap.add_argument("plan", help="plan.json 路径")
    ap.add_argument("--out", required=True, help="成片输出路径（.mp4）")
    ap.add_argument("--quality", choices=list(QUALITY), default="medium")
    ap.add_argument("--only", help="只渲这一拍（如 s01），不 concat")
    ap.add_argument("--force", action="store_true", help="忽略已存在的分拍 mp4，强制重渲")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不渲染")
    ap.add_argument("--theme", help="配色主题（whiteboard/warm/cool/mint/sakura）；"
                                   "非默认主题会走 lib/themed_render.py 成片后整体染色")
    args = ap.parse_args()

    plan_path = Path(args.plan).resolve()
    root = plan_path.parent
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    scenes = plan["scenes"]

    if not args.dry_run:
        require(root, "G3" if args.only else "G4",
                None if args.only else plan_path)

    # 主题：默认主题走原路径（零成本）；换主题则成片后整体染色
    theme_name = args.theme or os.environ.get("WHITEBOARD_THEME") or "whiteboard"
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
    import theme as _theme_mod
    _theme_mod.setup_ffmpeg_env()
    # 老版 ffmpeg 缺 tpad 滤镜 → 禁用引擎的延帧路径（整段当绘制期）
    _theme_mod.patch_no_tpad()
    themed = theme_name != _theme_mod.DEFAULT_THEME
    globals()["_THEME_NAME"] = theme_name
    if args.theme:
        log(f"配色主题：{theme_name}（{_theme_mod.get(theme_name)['paper']}）"
            + ("｜成片后整体染色" if themed else "｜默认路径"))

    if args.only:
        scenes = [s for s in scenes if s["id"] == args.only]
        if not scenes:
            sys.exit(f"--only {args.only} 没有匹配到任何拍")

    log(f"方案：{plan.get('idea', plan_path.name)}  共 {len(scenes)} 拍")
    for s in scenes:
        regions = s.get("regions") or []
        has_cue = any(r.get("start") is not None and r.get("end") is not None for r in regions)
        mode = "精确cue" if has_cue else ("估算窗口" if regions else "均分")
        log(f"  {s['id']}: {s['image']}"
            + (f" + {s['audio']}" if s.get("audio") else f" ({s.get('duration', 8)}s 静音)")
            + f"  [{len(regions)} region / {mode}]")

    if args.dry_run:
        return 0

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = root / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_dir = out_path.parent / (out_path.stem + "_parts")
    out_dir.mkdir(parents=True, exist_ok=True)

    has_audio = [bool(s.get("audio")) for s in scenes]
    if len(set(has_audio)) > 1:
        sys.exit("所有拍必须统一：要么全有音频，要么全静音（ffmpeg concat 要求流一致）")

    t0 = time.monotonic()
    parts, durations = [], []
    for scene in scenes:
        log(f"渲染 {scene['id']} ...")
        part, dur = render_scene(scene, root, out_dir, args.quality, None, args.force)
        parts.append(part)
        durations.append(dur)
        log(f"  -> {part.name} ({dur:.2f}s)")

    if args.only:
        log(f"单拍完成：{parts[0]}（跳过 concat）")
        return 0

    log(f"合并 {len(parts)} 段 -> {out_path}")
    concatenate(parts, out_path)

    # 产物校验：合并后必须可解码且时长≈分拍合计，否则删坏文件并定位异常分拍
    try:
        total_video = probe_duration(out_path)
        if abs(total_video - sum(durations)) > 1.0 + 0.01 * len(parts):
            raise ValueError(f"成片时长 {total_video:.1f}s ≠ 分拍合计 {sum(durations):.1f}s")
    except Exception as exc:
        log(f"  [ERROR] 合并产物校验失败：{exc}")
        bad = []
        for p in parts:
            try:
                if probe_duration(p) <= 0.2:
                    bad.append(f"{p} (时长异常)")
            except Exception:
                bad.append(f"{p} (无法解码)")
        if out_path.exists():
            out_path.unlink()                      # 不留无效成片
        log(f"  [ERROR] 异常分拍：{bad or '无（可能是磁盘空间不足）'}")
        raise SystemExit("合并产物无效，已删除。排查异常分拍后重跑（分拍会缓存）。")

    log(f"成片：{out_path}")
    log(f"  分拍时长合计 {sum(durations):.1f}s / 成片 {total_video:.1f}s / 耗时 {time.monotonic() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
