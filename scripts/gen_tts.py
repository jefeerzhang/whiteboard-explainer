"""gen_tts.py — 按场景配音，生成独立 WAV 音轨、清单与 timeline。

使用共享 G3、内容缓存和本地媒体验证。输入支持 JSON 和 YAML：
  lang: zh                    # 可选：en 时默认 voice 切 en-US-JennyNeural（英文教学）
  voice: zh-CN-XiaoyiNeural   # 可覆盖；英文用 en-US-JennyNeural
  speed: 1.0
  scenes:
    - id: s01
      text: "盛唐长安，万邦来朝……"

运行目录位于 --out-dir/runs/ 下；--out-dir/timeline.json 保留兼容入口。
--dry-run / --preflight 不调用合成；--preview 须单独获准。
"""
from __future__ import annotations
import argparse
import asyncio
import json
from pathlib import Path

from artifacts import atomic_bytes, atomic_json, file_lock
from audio_timing import pad_scene
from build_narration import tts
from narration_cache import get_audio
from narration_runs import NarrationRun, relative
from production import inspection_report, narration_config, print_design, print_inspection, read_spec, spoken_text
from user_gates import confirm_preview, require, require_spec

def load_narration(path: Path) -> dict:
    return read_spec(path)


def main():
    parser = argparse.ArgumentParser(
        description="故事手绘风视频旁白配音（edge-tts 免费）+ 生成 timeline.json",
    )
    parser.add_argument("narration_yaml", help="narration.yaml 路径")
    parser.add_argument(
        "--out-dir", default="public/audio/narration",
        help="输出目录（默认 public/audio/narration/）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印不生成")
    parser.add_argument("--preflight", action="store_true", help="仅执行本地预检")
    parser.add_argument("--design-only", action="store_true")
    parser.add_argument("--preview", action="store_true",
                        help="单句试听，须交互授权，不代替 G3")
    args = parser.parse_args()

    root = Path(args.narration_yaml).resolve().parent
    if not args.dry_run and not args.preflight and not args.design_only and not args.preview:
        require(root, "G3", Path(args.narration_yaml))
    spec = load_narration(Path(args.narration_yaml))
    if args.design_only:
        print_design(spec)
        return
    if args.dry_run or args.preflight:
        print_inspection(spec, root, "scene", runtime=args.preflight)
        return
    if not args.preview:
        require_spec(root, spec, "scene")
    inspection_report(spec, root, "scene", runtime=True)
    config = narration_config(spec, "scene")
    voice = config["voice"]
    scenes = spec["scenes"]
    if args.preview:
        texts = [spoken_text(s, "text") for s in scenes]
        print(f"Preview: voice={voice}, rate={config['rate']}, texts={texts}")
        confirm_preview(root, texts)
    out_dir = Path(args.out_dir).resolve()
    if Path(args.narration_yaml).resolve() == out_dir / "timeline.json":
        raise ValueError("Use a separate narration input; timeline.json is generated")
    with file_lock(root / ".narration-cache" / "production.lock"):
        current = NarrationRun(root, spec, config, Path(args.narration_yaml).resolve(), out_dir)
        try:
            timeline = []
            for sc in scenes:
                sid = sc["id"]
                text = spoken_text(sc, "text")
                out_path = current.directory / f"{sid}.wav"
                cached, seconds, facts = asyncio.run(get_audio(
                    text, config, root / ".narration-cache", tts))
                atomic_bytes(out_path, cached.read_bytes())
                timing = pad_scene(out_path, float(sc.get("hold", 0)), spec.get("fps", 24),
                                   float(spec.get("tail_pad", 0)))
                current.record(sid, out_path, [], [facts], timing)
                timeline.append({
                    "id": sid, "file": relative(out_path, root), "text": sc["text"],
                    "spoken_text": text, "seconds": timing["frames"] / timing["fps"], **timing,
                    "manifest": relative(current.manifest, root),
                })
            archived = [{**item, "file": relative(root / item["file"], current.directory),
                         "manifest": "manifest.json"} for item in timeline]
            summary = current.complete(archived, "timeline.json")
            atomic_json(out_dir / "timeline.json", timeline)
            print(json.dumps(summary, ensure_ascii=True))
        except BaseException:
            current.fail()
            raise


if __name__ == "__main__":
    main()
