"""Local narration preparation shared by approval and production CLIs."""
from __future__ import annotations

import importlib.util
import json
import math
import re
import shutil
import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def read_document(path: Path):
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError:
            raise ValueError("YAML input requires PyYAML; JSON input needs no extra parser")
        spec = yaml.safe_load(text)
    else:
        spec = json.loads(text)
    return spec


def read_spec(path: Path) -> dict:
    spec = read_document(path)
    if not isinstance(spec, dict):
        raise ValueError("The production input must be an object")
    return spec


def narration_config(spec: dict, mode: str = "standard", rate: str | None = None) -> dict:
    default_voice = "zh-CN-YunxiNeural"
    if mode == "scene":
        default_voice = "en-US-JennyNeural" if spec.get("lang") == "en" else "zh-CN-XiaoyiNeural"
    default_rate = "+22%" if mode == "fast" else "+0%"
    if mode == "scene" and "speed" in spec and "rate" not in spec:
        speed = float(spec["speed"])
        if not math.isfinite(speed):
            raise ValueError("speed must be finite")
        default_rate = f"{int(round((speed - 1) * 100)):+d}%"
    try:
        sdk_version = version("edge-tts")
    except PackageNotFoundError:
        sdk_version = "unavailable"
    config = {
        "version": 1,
        "provider": spec.get("tts_provider", "edge"),
        "model": spec.get("tts_model", "edge-tts"),
        "voice": spec.get("voice", default_voice),
        "rate": rate or spec.get("rate", default_rate),
        "trim": mode == "fast",
        "text_version": 1,
        "sdk_version": sdk_version,
    }
    if config["provider"] != "edge" or config["model"] != "edge-tts":
        raise ValueError("This CLI supports only the edge / edge-tts backend")
    if not isinstance(config["voice"], str) or not config["voice"].strip():
        raise ValueError("voice must be a nonempty string")
    if not isinstance(config["rate"], str) or not re.fullmatch(r"[+-]\d+%", config["rate"]):
        raise ValueError("rate must be a signed percentage, such as +15%")
    if not -90 <= int(config["rate"][:-1]) <= 300:
        raise ValueError("rate must be between -90% and +300%")
    return config


def positive(value, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive finite number")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return number


def spoken_text(region: dict, source: str = "annotation") -> str:
    text = region.get("spoken_text", region.get(source, ""))
    if not isinstance(text, str):
        raise ValueError("spoken_text must be a string")
    return text.strip()


def validate_spec(spec: dict, root: Path, mode: str, allow_empty: bool = False) -> None:
    scenes = spec.get("scenes")
    if not isinstance(scenes, list) or (not scenes and not allow_empty):
        raise ValueError("scenes must be a nonempty array")
    gap = spec.get("gap", 0.35)
    if isinstance(gap, bool) or not math.isfinite(float(gap)) or float(gap) < 0:
        raise ValueError("gap must be a nonnegative finite number")
    canvas = spec.get("canvas", [1280, 720])
    if not isinstance(canvas, list) or len(canvas) != 2:
        raise ValueError("canvas requires width and height")
    for value in canvas:
        positive(value, "canvas")
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("canvas dimensions must be integers")
    if not isinstance(spec.get("idea", ""), str):
        raise ValueError("idea must be a string")
    audio_dir = spec.get("audio_dir", "audio/narration")
    if not isinstance(audio_dir, str) or not (root / audio_dir).resolve().is_relative_to(root.resolve()):
        raise ValueError("audio_dir must stay inside this project")
    ids = set()
    for scene in scenes:
        if not isinstance(scene, dict):
            raise ValueError("Every scene must be an object")
        sid = scene.get("id")
        if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", sid) or sid in ids:
            raise ValueError("Scene ids must be unique, nonempty and path-safe")
        ids.add(sid)
        if mode == "scene":
            if not isinstance(scene.get("text"), str) or not scene["text"].strip():
                raise ValueError(f"{sid}: text must be a nonempty string")
            if not spoken_text(scene, "text"):
                raise ValueError(f"{sid}: text must be nonempty")
            continue
        from PIL import Image
        image = scene.get("image")
        if not isinstance(image, str):
            raise ValueError(f"{sid}: image path is required")
        try:
            with Image.open(root / image) as im:
                im.verify()
        except (OSError, ValueError) as exc:
            raise ValueError(f"{sid}: image cannot be read") from exc
        if "duration" in scene:
            positive(scene["duration"], f"{sid}: duration")
        regions = scene.get("regions", [])
        if not isinstance(regions, list):
            raise ValueError(f"{sid}: regions must be an array")
        for region in regions:
            if not isinstance(region, dict):
                raise ValueError(f"{sid}: region must be an object")
            if not isinstance(region.get("annotation", ""), str):
                raise ValueError(f"{sid}: annotation must be a string")
            spoken_text(region)
            box = region.get("box", region.get("box_2d"))
            boxes = box if isinstance(box, list) and box and isinstance(box[0], (list, dict)) else [box]
            for b in boxes:
                if isinstance(b, dict):
                    b = [b.get(k) for k in ("ymin", "xmin", "ymax", "xmax")]
                if not isinstance(b, list) or len(b) != 4:
                    raise ValueError(f"{sid}: box requires four normalized coordinates")
                if any(isinstance(v, bool) or not isinstance(v, (int, float))
                       or not math.isfinite(v) or not 0 <= v <= 1000 for v in b):
                    raise ValueError(f"{sid}: box coordinates must be within 0..1000")
                y0, x0, y1, x1 = b
                if y0 >= y1 or x0 >= x1:
                    raise ValueError(f"{sid}: box must have positive width and height")
    if spec.get("font"):
        from PIL import ImageFont
        try:
            ImageFont.truetype(str(root / spec["font"]), 24)
        except OSError as exc:
            raise ValueError("The requested font cannot be loaded") from exc


def local_tools() -> dict:
    tools = {}
    for name in ("ffmpeg", "ffprobe"):
        path = shutil.which(name)
        if path is None:
            raise ValueError("Local ffmpeg and ffprobe are required")
        tools[name] = path
    result = subprocess.run([tools["ffmpeg"], "-hide_banner", "-encoders"],
                            capture_output=True, text=True, errors="replace", timeout=30)
    if result.returncode or "libx264" not in result.stdout:
        raise ValueError("ffmpeg must support libx264")
    if importlib.util.find_spec("edge_tts") is None:
        raise ValueError("The selected backend requires edge-tts")
    return tools


def inspection_report(spec: dict, root, mode: str = "standard",
                      rate: str | None = None, runtime: bool = False) -> dict:
    config = narration_config(spec, mode, rate)
    validate_spec(spec, Path(root), mode, allow_empty=not runtime)
    if runtime:
        local_tools()
    return {"status": "PASS", "config": config,
            "canvas": spec.get("canvas", [1280, 720]),
            "scenes": [scene["id"] for scene in spec["scenes"]],
            "runtime": "PASS" if runtime else "NOTRUN"}


def print_inspection(spec: dict, root, mode: str = "standard",
                     rate: str | None = None, runtime: bool = False) -> None:
    print(json.dumps(inspection_report(spec, root, mode, rate, runtime),
                     ensure_ascii=True))
