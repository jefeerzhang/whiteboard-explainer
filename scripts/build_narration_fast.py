#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_narration_fast.py — 带语速与静音裁剪的旁白生成（短视频默认 +22%）

在 build_narration 基础上 monkey-patch tts：语速默认 +22%（Yunxi/Xiaoxiao 实测清晰），
并用 silenceremove+areverse 双程裁掉分片首尾静音（TTS 分片自带头尾 0.3~0.6s 静音，
不裁剪会白白拉长 20% 时长）。产物与 build_narration 相同：audio/narration/<sid>.mp3 + plan.json。

用法：
  python scripts/build_narration_fast.py plan.build.json [--rate +22%]
  python scripts/build_narration_fast.py plan.build.json --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

from user_gates import require

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_narration as bn  # noqa: E402

TRIM = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.08,"
        "areverse,"
        "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.08,"
        "areverse")


def make_fast(rate: str = "+22%"):
    orig = bn.tts

    async def tts_fast(text, out, voice, rate_="+0%"):
        await orig(text, out, voice, rate=rate)
        tmp = out.with_suffix(".trim.mp3")
        subprocess.run(["ffmpeg", "-y", "-i", str(out), "-af", TRIM,
                        "-c:a", "libmp3lame", "-q:a", "2", str(tmp)],
                       check=True, capture_output=True, encoding="utf-8", errors="replace")
        tmp.replace(out)

    return tts_fast


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", help="plan.build.json")
    ap.add_argument("--rate", help="须匹配 spec.rate（未指定时使用 spec.rate 或 +22%）")
    ap.add_argument("--dry-run", action="store_true")
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

    require(root, "G3", spec_path)
    rate = args.rate or spec.get("rate", "+22%")
    if rate != spec.get("rate", "+22%"):
        raise SystemExit("BLOCKED: --rate must match the approved spec rate")

    # 0 字节坏分片先删（edge-tts NoAudioReceived 后 save 可能留 0 字节文件，重跑会被 skip）
    parts = root / spec.get("audio_dir", "audio/narration") / "parts"
    if parts.exists():
        for p in parts.glob("*.mp3"):
            if p.stat().st_size < 2048:
                p.unlink()
                print(f"  删除坏分片 {p.name}")

    bn.tts = make_fast(rate)
    asyncio.run(bn.build(spec, root, dry=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
