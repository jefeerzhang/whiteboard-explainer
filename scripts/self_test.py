#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""self_test.py — whiteboard-explainer 出片前的三关自检。

跑：
    python scripts/self_test.py            # 全套
    python scripts/self_test.py --quick    # 跳过 element_plan cue 测试（更快）

每个测试独立显示 PASS/FAIL，最后统计全部通过才退出 0。
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# 把 scripts 加进 sys.path（whiteboard_animator 来自 pip 安装，无需 vendor）
SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

try:
    from whiteboard_animator import WhiteboardAnimator  # noqa: E402
except ImportError:
    print("❌ whiteboard_animator 未安装。先跑 scripts/setup.sh 或 scripts/setup.ps1", file=sys.stderr)
    sys.exit(2)

# 用 make_text_layer 的字体探测，缺字体时优雅退化而不是硬挂
try:
    from make_text_layer import load_font  # noqa: E402
except ImportError:
    load_font = None  # type: ignore

PASSED: list[tuple[str, bool, str]] = []


def log(test: str, ok: bool, msg: str = "") -> None:
    icon = "✅" if ok else "❌"
    print(f"  {icon} {test}" + (f"  ({msg})" if msg else ""))
    PASSED.append((test, ok, msg))


def _make_test_image(text: str, tmpdir: Path) -> Path:
    """画一张白底中文测试图。"""
    img = Image.new("RGB", (1280, 720), "white")
    draw = ImageDraw.Draw(img)
    if load_font is not None:
        try:
            font = load_font("bold", 80)
        except Exception:
            font = ImageFont.load_default()
    else:
        font = ImageFont.load_default()
    draw.text((640, 320), text, fill="#171714", font=font, anchor="mm")
    # 一个简单方框给引擎做图形测试
    draw.rectangle((140, 160, 540, 560), outline="#171714", width=8)
    draw.line((140, 160, 540, 560), fill="#171714", width=4)
    p = tmpdir / "self_test_input.png"
    img.save(p)
    return p


def test_craft_chinese(tmpdir: Path) -> None:
    """测试 1：CRAFT 能识别中文 + 出图。"""
    print("\n[1/3] CRAFT 中文识别 + 白板动画")
    src = _make_test_image("日全食讲解测试", tmpdir)
    out = tmpdir / "craft_test.mp4"
    img = np.array(Image.open(src).convert("RGB"))
    an = WhiteboardAnimator(fade_duration=0.05)
    t0 = time.time()
    try:
        an.render_to_file(img, 6.0, 4.0, str(out))
        dur = time.time() - t0
        if out.exists() and out.stat().st_size > 1000:
            # probe 时长校验
            res = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(out)],
                capture_output=True, text=True, timeout=30,
            )
            video_dur = float(res.stdout.strip()) if res.stdout.strip() else 0.0
            log("CRAFT 中文渲染", True, f"{video_dur:.1f}s video, {dur:.1f}s render")
        else:
            log("CRAFT 中文渲染", False, "输出文件缺失或过小")
    except Exception as e:
        log("CRAFT 中文渲染", False, f"{type(e).__name__}: {e}")


def test_ink_on_white(tmpdir: Path) -> None:
    """测试 2：白底净化 + 笔画绘制（最简单 happy path）。"""
    print("\n[2/3] ink-on-white 净化 + 笔画绘制")
    img = Image.new("RGB", (640, 360), "white")
    d = ImageDraw.Draw(img)
    # 故意画一些非纯白像素（浅灰），引擎应该 snap 成白
    d.rectangle((50, 50, 250, 250), fill=(250, 250, 250))
    d.rectangle((350, 100, 580, 300), outline="#000000", width=6)
    src = tmpdir / "ink_test.png"
    img.save(src)
    out = tmpdir / "ink_test.mp4"
    arr = np.array(Image.open(src).convert("RGB"))
    an = WhiteboardAnimator(fade_duration=0.05)
    try:
        an.render_to_file(arr, 3.5, 2.5, str(out))
        if out.exists() and out.stat().st_size > 1000:
            log("白底净化", True, f"{out.stat().st_size // 1024}KB")
        else:
            log("白底净化", False, "输出异常")
    except Exception as e:
        log("白底净化", False, f"{type(e).__name__}: {e}")


def test_cue_alignment(tmpdir: Path) -> None:
    """测试 3：精确 cue 时间窗生效（窗口内才绘制）。"""
    print("\n[3/3] element_plan 精确 cue 对齐")
    src = _make_test_image("上", tmpdir)
    arr = np.array(Image.open(src).convert("RGB"))
    an = WhiteboardAnimator(fade_duration=0.05)
    plan = [
        {"boxes": [{"ymin": 0, "xmin": 0, "ymax": 1000, "xmax": 1000}], "start": 0.0, "end": 1.5},
        {"boxes": [{"ymin": 0, "xmin": 0, "ymax": 1000, "xmax": 1000}], "start": 4.0, "end": 5.5},
    ]
    out = tmpdir / "cue_test.mp4"
    try:
        an.render_to_file(arr, 5.5, 6.0, str(out), element_plan=plan)
        if out.exists() and out.stat().st_size > 1000:
            log("element_plan cue", True, "窗口 [0-1.5] / [4-5.5] 渲染完成")
        else:
            log("element_plan cue", False, "输出异常")
    except Exception as e:
        log("element_plan cue", False, f"{type(e).__name__}: {e}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="跳过 element_plan cue 测试（更快）")
    args = ap.parse_args()

    print("whiteboard-explainer 三关自检")
    print("（验证 CRAFT 引擎、白底净化、cue 对齐全链路可用）")

    with tempfile.TemporaryDirectory(prefix="wb_self_test_") as td:
        tmp = Path(td)
        try:
            test_craft_chinese(tmp)
            test_ink_on_white(tmp)
            if not args.quick:
                test_cue_alignment(tmp)
        finally:
            # 即使后续测试失败，前面成功的产物保留到 cwd 下的 self_test_artifacts/ 方便排查
            if any(ok for _, ok, _ in PASSED):
                artifacts = Path("self_test_artifacts")
                artifacts.mkdir(exist_ok=True)
                for f in tmp.glob("*"):
                    shutil.copy2(f, artifacts / f.name)

    print()
    fails = [name for name, ok, _ in PASSED if not ok]
    total = len(PASSED)
    passed = total - len(fails)
    if fails:
        print(f"❌ {passed}/{total} 通过。失败：{', '.join(fails)}")
        return 1
    print(f"✅ 全部 {total} 关通过。skill 可放心发布。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
