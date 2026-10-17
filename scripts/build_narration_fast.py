#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_narration_fast.py — 带语速与静音裁剪的旁白生成（短视频默认 +22%）

复用 build_narration 的审批、缓存与运行归属。语速默认 +22%，
对加工音频裁首尾静音；原始旁白仍可跨处理配置复用。

用法：
  python scripts/build_narration_fast.py plan.build.json [--rate +22%]
  python scripts/build_narration_fast.py plan.build.json --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from production import print_design, print_inspection, read_spec
from user_gates import require, require_spec

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_narration as bn  # noqa: E402

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", help="plan.build.json")
    ap.add_argument("--rate", help="须匹配 spec.rate（未指定时使用 spec.rate 或 +22%）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--preflight", action="store_true")
    ap.add_argument("--design-only", action="store_true")
    args = ap.parse_args()

    spec_path = Path(args.spec).resolve()
    root = spec_path.parent
    spec = read_spec(spec_path)
    if args.design_only:
        print_design(spec)
        return 0

    if args.dry_run or args.preflight:
        print_inspection(spec, root, "fast", args.rate, args.preflight)
        return 0

    require(root, "G3", spec_path)
    rate = args.rate or spec.get("rate", "+22%")
    if rate != spec.get("rate", "+22%"):
        raise SystemExit("BLOCKED: --rate must match the approved spec rate")
    require_spec(root, spec, "fast", rate)

    asyncio.run(bn.build(spec, root, dry=False, mode="fast", rate=rate))
    return 0


if __name__ == "__main__":
    sys.exit(main())
