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
输出：独立运行目录内的 WAV、cue 与 manifest，以及兼容的 plan.json。
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import subprocess
import sys
from pathlib import Path

from artifacts import atomic_json, file_lock
from audio_timing import pad_scene, silent_scene
from narration_cache import get_audio
from narration_runs import NarrationRun, relative
from production import inspection_report, narration_config, print_design, print_inspection, read_spec, spoken_text
from user_gates import require, require_spec

try:
    import edge_tts
except ImportError:
    edge_tts = None  # type: ignore[assignment]

def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True,
                          encoding="utf-8", errors="replace")


def probe_duration(path: Path) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "csv=p=0", str(path)])
    return float(out.stdout.strip())


async def tts(text: str, out: Path, voice: str, rate: str = "+0%") -> None:
    """edge-tts 偶发 NoAudioReceived/网络抖动，重试 3 次。"""
    if edge_tts is None:
        raise ValueError("The selected backend requires edge-tts")
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
    gap = out_dir / ".gap.wav"
    if not gap.exists():
        run(["ffmpeg", "-y", "-f", "lavfi", "-i",
             f"anullsrc=r=24000:cl=mono", "-t", f"{seconds}",
             "-c:a", "pcm_s16le", str(gap)])
    return gap


def concat(parts: list[Path], out: Path) -> None:
    lst = out.parent / (out.name + ".concat.txt")
    escaped = [p.resolve().as_posix().replace("'", "'\\''") for p in parts]
    lst.write_text("".join(f"file '{p}'\n" for p in escaped), encoding="utf-8")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(out)])
    lst.unlink()


async def build(spec: dict, root: Path, dry: bool, mode: str = "standard",
                rate: str | None = None) -> dict:
    source = require_spec(root, spec, mode, rate) if not dry else None
    inspection_report(spec, root, mode, rate, runtime=not dry)
    config = narration_config(spec, mode, rate)
    if dry:
        return {"config": config, "scenes": spec["scenes"]}
    assert source is not None
    if source.resolve() == (root / "plan.json").resolve():
        raise ValueError("Use a separate build input; plan.json is the generated render plan")
    with file_lock(root / ".narration-cache" / "production.lock"):
        current = NarrationRun(root, spec, config, source)
        try:
            return await _build_run(spec, root, config, current)
        except BaseException:
            current.fail()
            raise


async def _build_run(spec: dict, root: Path, config: dict, current: NarrationRun) -> dict:
    gap = float(spec.get("gap", 0.35))
    audio_dir = current.directory
    gap_path = make_gap(audio_dir, gap) if gap else None

    plan = {
        "idea": spec.get("idea", ""),
        "canvas": spec.get("canvas", [1280, 720]),
        "fps": spec.get("fps", 24),
        "teaching": spec.get("teaching", False),
        "scenes": [],
    }
    audio_mode = spec.get("teaching", False) or any(
        spoken_text(region) for scene in spec["scenes"] for region in scene.get("regions", [])
    )

    for scene in spec["scenes"]:
        sid = scene["id"]
        regions = scene.get("regions") or []
        annotations = [spoken_text(r) for r in regions]
        # 无 annotation 的 region（纯图形）也要有窗口：用空串 TTS 会失败，改为复用时长 0
        spoken = [(i, a) for i, a in enumerate(annotations) if a]

        scene_audio = audio_dir / f"{sid}.wav"
        windows: dict[int, tuple[float, float]] = {}
        scene_facts = []
        timing = {}

        if spoken:
            # 1. 逐子句 TTS
            clips: list[tuple[int, Path, float]] = []
            for k, (idx, text) in enumerate(spoken):
                clip, duration, facts = await get_audio(text, config, root / ".narration-cache", tts)
                print(f"  TTS {sid} r{k:02d}: generated={facts['generated']} reused={facts['reused']}")
                scene_facts.append(facts)
                clips.append((idx, clip, duration))
            # 2. 累积时间窗：region i 的窗口 = 它自己分片起点 → 下一个分片结束（含尾部 gap）
            cursor = 0.0
            for j, (idx, clip, dur) in enumerate(clips):
                start = cursor
                end = cursor + dur + (gap if j < len(clips) - 1 else 0)
                windows[idx] = (round(start, 3), round(end, 3))
                cursor = end
            # 3. 拼接整拍音轨（分片 + 间隔）
            parts: list[Path] = []
            for j, (idx, clip, dur) in enumerate(clips):
                parts.append(clip)
                if j < len(clips) - 1 and gap_path:
                    parts.append(gap_path)
            if parts:
                concat(parts, scene_audio)
                total = probe_duration(scene_audio)
                # 尾部窗口 clamp 到实际音轨长度
                for idx, (s, e) in windows.items():
                    windows[idx] = (s, min(e, total))
                timing = pad_scene(scene_audio, float(scene.get("hold", 0)),
                                   plan["fps"], float(spec.get("tail_pad", 0)))
        elif audio_mode:
            silent_scene(scene_audio, float(scene.get("duration", 8)))
            timing = pad_scene(scene_audio, float(scene.get("hold", 0)),
                               plan["fps"], float(spec.get("tail_pad", 0)))

        out_scene = {"id": sid, "image": scene["image"]}
        out_scene.update(timing)
        for key in ("role", "visual"):
            if key in scene:
                out_scene[key] = scene[key]
        if windows or timing:
            out_scene["audio"] = relative(scene_audio, root)
        elif scene.get("duration"):
            out_scene["duration"] = scene["duration"]

        out_regions = []
        for i, r in enumerate(regions):
            entry = {"label": r.get("label", f"r{i}"), "box": r.get("box", r.get("box_2d"))}
            if "annotation" in r:
                entry["annotation"] = r["annotation"]
            if "spoken_text" in r:
                entry["spoken_text"] = r["spoken_text"]
            if i in windows:
                s, e = windows[i]
                entry["start"], entry["end"] = s, e
            elif r.get("annotation"):
                entry["annotation"] = r["annotation"]  # 降级为估算档
            out_regions.append(entry)
        out_scene["regions"] = out_regions
        plan["scenes"].append(out_scene)
        current.record(sid, scene_audio if windows or timing else None, out_regions, scene_facts, timing)
        total = sum(e - s for s, e in windows.values()) if windows else scene.get("duration", 0)
        print(f"{sid}: {len(regions)} regions, cue 总时长 {total:.1f}s")

    out_path = root / "plan.json"
    archived = copy.deepcopy(plan)
    for scene in archived["scenes"]:
        scene["image"] = relative(root / scene["image"], current.directory)
        if scene.get("audio"):
            scene["audio"] = relative(root / scene["audio"], current.directory)
    plan["narration"] = current.complete(archived)
    plan["narration"]["fps"] = plan["fps"]
    atomic_json(out_path, plan)
    print(f"写出 {out_path}")
    return plan


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", help="plan.build.json")
    ap.add_argument("--dry-run", action="store_true", help="只打印子句，不 TTS")
    ap.add_argument("--preflight", action="store_true", help="仅检查本地输入和运行依赖")
    ap.add_argument("--design-only", action="store_true", help="G2 前只展示教学画面计划，不读取画板")
    args = ap.parse_args()

    spec_path = Path(args.spec).resolve()
    root = spec_path.parent
    spec = read_spec(spec_path)
    if args.design_only:
        print_design(spec)
        return 0

    if args.dry_run or args.preflight:
        print_inspection(spec, root, runtime=args.preflight)
        return 0

    require(root, "G3", spec_path)
    asyncio.run(build(spec, root, dry=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
