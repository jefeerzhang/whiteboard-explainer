#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""transcribe_align.py — 原声直用：转写 + 脚本对齐 → timeline.json

场景：已有播客/讲解的成片原声（mp3）和对应文字脚本（md/txt），不重新配音，
直接取原声做白板动画。本脚本解决「脚本句子 ↔ 原声时间」的对齐问题。

机制（经实战验证）：
  1. faster-whisper 分块转写（长音频每 CHUNK 秒一块带重叠，避免内存峰值；
     模型下载走 HF_ENDPOINT=https://hf-mirror.com + HF_HUB_DISABLE_XET=1，国内可用）
  2. 脚本按 。？！ 切句，句子按字数比例估计时间，再吸附到最近的转写分段起点（±SNAP 秒）
  3. 句起点强制单调，场最短 MIN_SCENE 秒

用法：
  python transcribe_align.py <原声.mp3> <脚本.md> <项目目录> [--whisper-model small]

依赖：faster-whisper（pip install faster-whisper；首跑自动下模型）
输出：<项目目录>/transcript.json、<项目目录>/sentences.txt、<项目目录>/timeline.json
timeline.json 的 scenes[].sentences 就是每场的文案（一句一拍），供 spec 排版使用。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path

CHUNK = 300.0      # 分块转写块长（秒）
OVERLAP = 3.0      # 块间重叠（秒）
SNAP = 8.0         # 吸附半径（秒）
MIN_SCENE = 5.0    # 句起点最小间隔（秒）


# ---------------------------------------------------------------- 转写
def transcribe(mp3: Path, model_size: str) -> tuple[list[dict], float]:
    from faster_whisper import WhisperModel
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(mp3)], capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=True).stdout.strip())
    model = WhisperModel(model_size, device="cpu", compute_type="int8", cpu_threads=2)
    segments: list[dict] = []
    t, i = 0.0, 0
    while t < dur - 0.5:
        end = min(t + CHUNK + OVERLAP, dur)
        tmp = Path(f"_al_chunk_{i}.mp3")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-to", f"{end:.2f}",
                        "-i", str(mp3), str(tmp)], check=True)
        segs, _info = model.transcribe(str(tmp), language="zh", vad_filter=True,
                                       vad_parameters={"min_silence_duration_ms": 300})
        for s in segs:
            st, en = s.start + t, s.end + t
            if segments and st < segments[-1]["end"] - 0.5:   # 重叠区去重
                continue
            segments.append({"start": round(st, 2), "end": round(en, 2),
                             "text": s.text.strip()})
        tmp.unlink(missing_ok=True)
        print(f"  转写块 {i}: {t:.0f}-{end:.0f}s（累计 {len(segments)} 段）", flush=True)
        t += CHUNK
        i += 1
    return segments, dur


# ---------------------------------------------------------------- 切句
def split_sentences(md_text: str) -> list[str]:
    text = re.sub(r"^---\n.*?\n---\n", "", md_text, flags=re.S)
    paras = []
    for line in text.splitlines():
        t = line.strip()
        if not t or t.startswith("#") or t.startswith(">") or re.fullmatch(r"[（(].*[)）]", t):
            continue
        paras.append(t)
    sents = []
    for p in paras:
        buf = ""
        for part in re.split(r"(?<=[。？！?!])", p):
            if not part:
                continue
            buf += part
            if len(buf) >= 18:
                sents.append(buf.strip()); buf = ""
        if buf.strip():
            if sents and len(buf) < 8:
                sents[-1] += buf
            else:
                sents.append(buf.strip())
    return sents


def norm(t: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffa-z]", "", t.lower())


# ---------------------------------------------------------------- 对齐
def align(sents: list[str], segments: list[dict], dur: float):
    """句子按字数比例估计时间 → 吸附最近转写分段起点 → 单调钳制"""
    total = sum(len(s) for s in sents) or 1
    seg_times = sorted({round(x["start"], 2) for x in segments if x["start"] > 2.0})

    def snap(est):
        if not seg_times:
            return est
        best = min(seg_times, key=lambda t: abs(t - est))
        return best if abs(best - est) <= SNAP else est

    acc, starts = 0.0, []
    for s in sents:
        starts.append(snap(dur * acc / total))
        acc += len(s)
    prev = 0.0
    for i in range(len(starts)):
        starts[i] = min(max(starts[i], prev + MIN_SCENE), max(dur - MIN_SCENE, prev + MIN_SCENE))
        prev = starts[i]
    return starts


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mp3")
    ap.add_argument("script")
    ap.add_argument("dir")
    ap.add_argument("--whisper-model", default="small")
    args = ap.parse_args()

    d = Path(args.dir); d.mkdir(parents=True, exist_ok=True)
    mp3, md = Path(args.mp3), Path(args.script)
    t0 = time.monotonic()

    tr_path = d / "transcript.json"
    if tr_path.exists():
        print("transcript.json 已存在，跳过转写")
        tr = json.loads(tr_path.read_text(encoding="utf-8"))
        segments, dur = tr["segments"], tr["duration"]
    else:
        segments, dur = transcribe(mp3, args.whisper_model)
        tr_path.write_text(json.dumps({"duration": dur, "segments": segments},
                                      ensure_ascii=False, indent=1), encoding="utf-8")

    sents = split_sentences(md.read_text(encoding="utf-8"))
    (d / "sentences.txt").write_text(
        "\n".join(f"{i:3d}  {t}" for i, t in enumerate(sents)), encoding="utf-8")
    starts = align(sents, segments, dur)

    n_scenes = max(1, round(dur / 30.0))
    per_scene = max(len(sents) // n_scenes, 1)
    timeline = []
    for k in range(n_scenes):
        a = k * per_scene
        b = (k + 1) * per_scene if k < n_scenes - 1 else len(sents)
        if a >= b:
            continue
        timeline.append({
            "id": f"s{k+1:02d}",
            "sentences": sents[a:b],
            "start": starts[a],
            "end": starts[b] if b < len(starts) else dur,
        })
    (d / "timeline.json").write_text(json.dumps(
        {"duration": dur, "scenes": timeline}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"timeline.json：{len(timeline)} 场，耗时 {time.monotonic()-t0:.0f}s")
    print("每场 sentences 数组即一句一拍的文案——排版成画面文案后即可渲染")


if __name__ == "__main__":
    main()
