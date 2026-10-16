#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""verify_media.py — 产物校验层：每个音视频产物生成后必须过这道检查

纪律（借鉴 ffmpeg-skill：probe-first / verify-after，两 skill 并存、互不吞并）：
  - 底层探测调用同级 ffmpeg-skill 的 probe.py --json（路径自动按 ../ffmpeg-skill 解析）
  - 每个产物必须：存在、可解码、时长与期望一致（±容差）
  - 任何一项失败 → 汇总报告并以非零码退出（禁止静默继续）

用法：
  python verify_media.py --manifest manifest.json
  python verify_media.py --file a.mp3 --expect 24.0
manifest.json: [{"path": "...", "expect": 秒数}]   expect 可省略（只查可解码）
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

TOL = 0.75  # 时长容差（秒）。mp3 分片重编码/关键帧裁剪有固有偏差


def sibling_probe() -> Path:
    env = os.environ.get("FFMPEG_SKILL_DIR")
    here = Path(__file__).resolve().parent          # .../skills/whiteboard-explainer/scripts
    cands = []
    if env:
        cands.append(Path(env) / "scripts" / "probe.py")
    cands.append(here.parent.parent / "ffmpeg-skill" / "scripts" / "probe.py")
    for c in cands:
        if c.exists():
            return c
    raise SystemExit(f"找不到 ffmpeg-skill 的 probe.py（候选：{[str(c) for c in cands]}）；"
                     f"确认 ffmpeg-skill 与本 skill 同级安装，或设 FFMPEG_SKILL_DIR")


def probe_duration(py: str, probe: Path, path: Path) -> float:
    r = subprocess.run([py, str(probe), str(path), "--json"], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise ValueError(f"probe 失败：{r.stderr.strip()[:200]}")
    data = json.loads(r.stdout)
    if isinstance(data, list):
        data = data[0]
    return float(data["duration"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest")
    ap.add_argument("--file")
    ap.add_argument("--expect", type=float, default=None)
    ap.add_argument("--python", default=sys.executable,
                    help="用于调 probe.py 的解释器（默认当前）")
    args = ap.parse_args()

    items = []
    if args.manifest:
        items += json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    if args.file:
        items.append({"path": args.file, "expect": args.expect})
    if not items:
        raise SystemExit("没有待校验的产物")

    probe = sibling_probe()
    rows, failed = [], 0
    for it in items:
        path = Path(it["path"])
        expect = it.get("expect")
        if not path.exists():
            rows.append((str(path), "FAIL", "文件不存在"))
            failed += 1
            continue
        try:
            got = probe_duration(args.python, probe, path)
        except Exception as exc:
            rows.append((str(path), "FAIL", f"无法解码: {exc}"))
            failed += 1
            continue
        if expect is not None and abs(got - float(expect)) > TOL:
            rows.append((str(path), "FAIL", f"时长 {got:.2f}s ≠ 期望 {expect:.2f}s"))
            failed += 1
            continue
        rows.append((str(path), "PASS", f"{got:.2f}s"))

    for path, st, msg in rows:
        print(f"  [{st}] {path}  {msg}")
    print(f"verify_media：{len(rows) - failed}/{len(rows)} 通过")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
