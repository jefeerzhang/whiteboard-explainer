#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_narration.py — 把讲稿变成「精确 cue」的音频 + 渲染用 plan.json

核心思想（本 skill 的音画对齐方法）：
  每拍拆成若干 region，每个 region 配一句 annotation（子句）。
  逐子句 TTS 得到分片 → 中间垫静音 gap → concat 成该拍音轨。
  用分片真实时长累加出每个 region 的 [start, end] —— 帧级"讲到哪画到哪"。

用法：
  python scripts/build_narration.py plan.build.json
  python scripts/build_narration.py plan.build.json --dry-run
输出：audio/narration/<sid>.mp3 + plan.json（含 regions 的精确 start/end）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

try:
    import edge_tts
except ImportError:
    sys.exit("缺少 edge-tts：pip install edge-tts")

GAP_FILE = ".gap.mp3"


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True,
                          encoding="utf-8", errors="replace")


def probe_duration(path: Path) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "csv=p=0", str(path)])
    return float(out.stdout.strip())


async def tts(text: str, out: Path, voice: str, rate: str = "+0%") -> None:
    """edge-tts 偶发 NoAudioReceived/网络抖动，重试 3 次。"""
    last = None
    for attempt in range(3):
        try:
            com = edge_tts.Communicate(text, voice, rate=rate)
            await com.save(str(out))
            if out.exists() and out.stat().st_size > 1000:
                return
            raise RuntimeError(f"TTS 产物过小: {out.stat().st_size if out.exists() else 0}B")
        except Exception as exc:  # noqa: BLE001
            last = exc
            await asyncio.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"TTS 三次失败: {text[:20]}… -> {last}") from last


def make_gap(out_dir: Path, seconds: float) -> Path:
    gap = out_dir / GAP_FILE
    if not gap.exists():
        run(["ffmpeg", "-y", "-f", "lavfi", "-i",
             f"anullsrc=r=24000:cl=mono", "-t", f"{seconds}",
             "-c:a", "libmp3lame", "-q:a", "9", str(gap)])
    return gap


def concat(parts: list[Path], out: Path) -> None:
    lst = out.parent / (out.name + ".concat.txt")
    lst.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts), encoding="utf-8")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-c:a", "libmp3lame", "-q:a", "2", str(out)])
    lst.unlink()


async def build(spec: dict, root: Path, dry: bool) -> dict:
    voice = spec.get("voice", "zh-CN-YunxiNeural")
    gap = float(spec.get("gap", 0.35))
    audio_dir = root / spec.get("audio_dir", "audio/narration")
    parts_dir = audio_dir / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    gap_path = make_gap(parts_dir, gap)

    plan = {
        "idea": spec.get("idea", ""),
        "canvas": spec.get("canvas", [1280, 720]),
        "scenes": [],
    }

    for scene in spec["scenes"]:
        sid = scene["id"]
        regions = scene.get("regions") or []
        annotations = [r.get("annotation", "").strip() for r in regions]
        # 无 annotation 的 region（纯图形）也要有窗口：用空串 TTS 会失败，改为复用时长 0
        spoken = [(i, a) for i, a in enumerate(annotations) if a]

        scene_audio = audio_dir / f"{sid}.mp3"
        windows: dict[int, tuple[float, float]] = {}

        if not dry:
            # 1. 逐子句 TTS
            clips: list[tuple[int, Path, float]] = []
            for k, (idx, text) in enumerate(spoken):
                clip = parts_dir / f"{sid}_r{k:02d}.mp3"
                if not clip.exists():
                    await tts(text, clip, voice)
                    print(f"  TTS {sid} r{k:02d}: {text[:18]}…")
                clips.append((idx, clip, probe_duration(clip)))
            # 2. 累积时间窗：region i 的窗口 = 它自己分片起点 → 下一个分片结束（含尾部 gap）
            cursor = 0.0
            for j, (idx, clip, dur) in enumerate(clips):
                start = cursor
                end = cursor + dur + (gap if j < len(clips) - 1 else gap)
                windows[idx] = (round(start, 3), round(end, 3))
                cursor = end
            # 3. 拼接整拍音轨（分片 + 间隔）
            parts: list[Path] = []
            for j, (idx, clip, dur) in enumerate(clips):
                parts.append(clip)
                if j < len(clips) - 1:
                    parts.append(gap_path)
            if parts:
                concat(parts, scene_audio)
                total = probe_duration(scene_audio)
                # 尾部窗口 clamp 到实际音轨长度
                for idx, (s, e) in windows.items():
                    windows[idx] = (s, min(e, total))

        out_scene = {"id": sid, "image": scene["image"]}
        if windows:
            out_scene["audio"] = scene_audio.relative_to(root).as_posix()
        elif scene.get("duration"):
            out_scene["duration"] = scene["duration"]

        out_regions = []
        for i, r in enumerate(regions):
            entry = {"label": r.get("label", f"r{i}"), "box": r["box"]}
            if i in windows:
                s, e = windows[i]
                entry["start"], entry["end"] = s, e
            elif r.get("annotation"):
                entry["annotation"] = r["annotation"]  # 降级为估算档
            out_regions.append(entry)
        out_scene["regions"] = out_regions
        plan["scenes"].append(out_scene)
        total = sum(e - s for s, e in windows.values()) if windows else scene.get("duration", 0)
        print(f"{sid}: {len(regions)} regions, cue 总时长 {total:.1f}s")

    out_path = root / "plan.json"
    out_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"写出 {out_path}")
    return plan


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", help="plan.build.json")
    ap.add_argument("--dry-run", action="store_true", help="只打印子句，不 TTS")
    args = ap.parse_args()

    spec_path = Path(args.spec).resolve()
    root = spec_path.parent
    spec = json.loads(spec_path.read_text(encoding="utf-8"))

    if args.dry_run:
        for s in spec["scenes"]:
            print(f"{s['id']}:")
            for r in s.get("regions", []):
                mark = "*" if r.get("annotation") else " "
                print(f"  {mark} {r.get('label','')}: {r.get('annotation','')}")
        return 0

    asyncio.run(build(spec, root, dry=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
