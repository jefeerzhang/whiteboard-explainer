"""Render configuration and content identity shared by rendering and approvals."""
from __future__ import annotations

import math
import uuid
from contextlib import contextmanager
from importlib.metadata import version
from pathlib import Path

from PIL import Image

from artifacts import atomic_bytes, atomic_json, file_digest, fingerprint, relative
from media import verify
from narration_runs import read_run
from production import normalize_canvas, positive, read_spec, validate_spec


QUALITY = {
    "low": {"fps": 20, "bitrate": "500k"},
    "medium": {"fps": 24, "bitrate": "1500k"},
    "high": {"fps": 24, "bitrate": "3000k"},
}


class CueError(ValueError):
    pass


def render_config(quality: str, theme: str, fps: int | None = None,
                  canvas: list[int] | None = None) -> dict:
    config = {"quality": quality, "theme": theme, **QUALITY[quality],
              "canvas": normalize_canvas(canvas if canvas is not None else [1280, 720])}
    if fps is not None:
        if isinstance(fps, bool) or not 1 <= fps <= 120:
            raise ValueError("fps must be within 1..120")
        config["fps"] = fps
    return config


def implementation() -> dict:
    scripts = Path(__file__).resolve().parent
    root = scripts.parent
    return {
        "engine": version("whiteboard-animator"),
        "files": {str(path): file_digest(path) for path in [
            scripts / "render_explainer.py", scripts / "render_contract.py",
            scripts / "check_assignment.py", scripts / "media.py",
            scripts / "production.py", scripts / "teaching.py",
            scripts / "artifacts.py", scripts / "audio_timing.py", scripts / "narration_runs.py",
            root / "lib/theme.py", root / "lib/themed_render.py",
        ]},
    }


def scene_key(scene: dict, root: Path, config: dict) -> str:
    return fingerprint({
        "scene": {k: v for k, v in scene.items() if k not in ("image", "audio")},
        "image": file_digest(root / scene["image"]),
        "audio": file_digest(root / scene["audio"]) if scene.get("audio") else None,
        "config": config, "implementation": implementation(),
    })


def frame_duration(duration: float, fps: int, scene: dict) -> float:
    frames = scene.get("frames")
    if (isinstance(frames, int) and not isinstance(frames, bool) and frames > 0
            and scene.get("fps") == fps and abs(duration - frames / fps) <= 1 / 24000 + 1e-6):
        return frames / fps
    return math.ceil(duration * fps - 1e-9) / fps


def snapshot(path: Path, plan: dict, config: dict) -> dict:
    root = path.parent
    validate_spec(plan, root, "render")
    if (isinstance(plan.get("narration"), dict) and plan["narration"].get("fps") is not None
            and plan["narration"]["fps"] != config["fps"]):
        raise ValueError("Regenerate narration with the requested fps before rendering")
    assets = {str(path.resolve()): file_digest(path)}
    narration = None
    if "narration" in plan:
        native = plan["narration"]
        if not isinstance(native, dict) or not isinstance(native.get("manifest"), str):
            raise ValueError("Narration provenance requires a run manifest")
        narration_path = (root / native["manifest"]).resolve()
        report, files = read_run(narration_path)
        if native.get("run_id") != report["run_id"] or native.get("run_key") != report["run_key"]:
            raise ValueError("Narration provenance belongs to another run")
        expected_audio = {(narration_path.parent / a["path"]).resolve() for a in report["media"]}
        actual_audio = {(root / s["audio"]).resolve() for s in plan["scenes"] if s.get("audio")}
        if expected_audio != actual_audio:
            raise ValueError("Narration run does not own the current scene audio")
        assets.update({str(p): file_digest(p) for p in files})
        narration = {"source": report["inputs"]["source"], "config": report["inputs"]["config"]}
    scenes = []
    audio_modes = {bool(s.get("audio")) for s in plan["scenes"]}
    if len(audio_modes) != 1:
        raise ValueError("All scenes must consistently include audio or be silent")
    for scene in plan["scenes"]:
        sid = scene["id"]
        assets[str((root / scene["image"]).resolve())] = file_digest(root / scene["image"])
        duration = positive(scene.get("duration", 8), f"{sid}: duration")
        if scene.get("audio"):
            audio = root / scene["audio"]
            assets[str(audio.resolve())] = file_digest(audio)
            duration = verify(audio, kind="audio")["duration"]
        if scene.get("duration_override") is not None:
            duration = positive(scene["duration_override"], f"{sid}: duration_override")
        if scene.get("hold", 0) or scene.get("tail_pad", 0):
            active = positive(scene.get("narration_duration"), f"{sid}: narration_duration")
            if active + scene.get("hold", 0) + scene.get("tail_pad", 0) > duration + 1 / 24000 + 1e-6:
                raise ValueError(f"{sid}: audio does not include the declared silent hold")
        for region in scene.get("regions", []):
            start, end = region.get("start"), region.get("end")
            if (start is None) != (end is None):
                raise CueError(f"{sid}: cue requires both start and end")
            if start is not None:
                if (isinstance(start, bool) or isinstance(end, bool)
                        or not isinstance(start, (int, float)) or not isinstance(end, (int, float))
                        or not math.isfinite(start) or not math.isfinite(end)
                        or not 0 <= start < end <= duration + 0.001):
                    raise CueError(f"{sid}: cue must stay inside the scene duration")
        mode = ("exact" if any(r.get("start") is not None for r in scene.get("regions", []))
                else "estimated" if scene.get("regions") else "uniform")
        scenes.append({"id": sid, "duration": frame_duration(duration, config["fps"], scene),
                       "regions": bool(scene.get("regions")), "cue_mode": mode})
    value = {"plan": str(path.resolve()), "assets": assets, "config": config,
             "implementation": implementation(), "scenes": scenes,
             "audio": next(iter(audio_modes)), "narration": narration}
    return {"key": fingerprint(value), **value}


def check_snapshot(context: dict) -> None:
    if context.get("key") != fingerprint({k: v for k, v in context.items() if k != "key"}):
        raise ValueError("Render snapshot is malformed")
    for filename, expected in {
        **context["assets"], **context["implementation"]["files"],
    }.items():
        if file_digest(Path(filename)) != expected:
            raise ValueError("Render inputs or implementation changed; create a new sample")
    if context["implementation"]["engine"] != version("whiteboard-animator"):
        raise ValueError("Render engine changed; create a new sample")


def verify_video(path: Path, config: dict, audio: bool) -> dict:
    result = verify(path, kind="video")
    if audio and "audio" not in result["streams"]:
        raise ValueError("Video is missing audio")
    if abs(result["video"]["fps"] - config["fps"]) > 0.001:
        raise ValueError("Video frame rate differs from the confirmed configuration")
    if [result["video"]["width"], result["video"]["height"]] != config["canvas"]:
        raise ValueError("Video dimensions differ from the confirmed canvas")
    return result


def _receipt_contract(proof: dict, stage: str, base: Path) -> None:
    if stage not in ("sample", "render"):
        raise ValueError("Unknown render receipt stage")
    if proof.get("schema") != 1 or proof.get("stage") != stage or proof.get("status") != "PASS":
        raise ValueError(f"A completed {stage} receipt is required")
    context = proof["context"]
    checks = proof["checks"]
    for name in ("inputs", "render", "media", "duration"):
        if checks.get(name) != "PASS":
            raise ValueError(f"Required {name} check did not pass")
    selected = proof["scenes"]
    available = [s["id"] for s in context["scenes"]]
    if (not selected or len(selected) != len(set(selected))
            or any(sid not in available for sid in selected)):
        raise ValueError("Receipt has an invalid scene selection")
    if stage == "render" and selected != available:
        raise ValueError("A partial scene receipt cannot approve final delivery")
    cue_state = "PASS" if any(s["cue_mode"] == "exact" for s in context["scenes"]) else "SKIP"
    if checks.get("cue") != cue_state:
        raise ValueError("Cue check is missing or inconsistent")
    assignment = checks.get("assignment")
    needs_assignment = any(s["regions"] for s in context["scenes"])
    if assignment != ("PASS" if needs_assignment else "SKIP"):
        raise ValueError("Assignment check is missing or inconsistent")
    artifacts = proof["artifacts"]
    allowed = {"sample", "frame"} if stage == "sample" else {"video", "delivery", "frame"}
    targets = set()
    for artifact in artifacts:
        if artifact.get("role") not in allowed:
            raise ValueError("Artifact role does not belong to this receipt stage")
        target = (base / artifact["path"]).resolve()
        if target in targets:
            raise ValueError("Receipt contains duplicate artifact paths")
        targets.add(target)
    role = "sample" if stage == "sample" else "video"
    videos = [a for a in artifacts if a.get("role") == role]
    frames = [a for a in artifacts if a.get("role") == "frame"]
    if len(videos) != 1 or (stage == "sample" and len(frames) != 2):
        raise ValueError("Receipt is missing its video or sample frames")
    if stage == "render":
        deliveries = [a for a in artifacts if a.get("role") == "delivery"]
        if len(deliveries) != 1 or deliveries[0]["sha256"] != videos[0]["sha256"]:
            raise ValueError("Final output does not match the verified video")


def _check_duration(result: dict, context: dict, selected: list[str]) -> None:
    expected = sum(s["duration"] for s in context["scenes"] if s["id"] in selected)
    if abs(result["duration"] - expected) > 2 / context["config"]["fps"] + 0.05:
        raise ValueError("Receipt video duration differs from this run")


def _artifact(role: str, path: Path, base: Path) -> dict:
    return {"role": role, "path": relative(path, base), "sha256": file_digest(path)}


def validate_evidence(path: Path, stage: str) -> tuple[dict, set[Path]]:
    proof = read_spec(path)
    _receipt_contract(proof, stage, path.parent)
    context = proof["context"]
    check_snapshot(context)
    files = {path.resolve(), *(Path(p) for p in context["assets"]),
             *(Path(p) for p in context["implementation"]["files"])}
    for artifact in proof["artifacts"]:
        target = (path.parent / artifact["path"]).resolve()
        if file_digest(target) != artifact["sha256"]:
            raise ValueError("Receipt artifact changed")
        files.add(target)
        if artifact["role"] == "frame":
            with Image.open(target) as image:
                image.verify()
        elif artifact["role"] in ("sample", "video", "delivery"):
            result = verify_video(target, context["config"], context["audio"])
            _check_duration(result, context, proof["scenes"])
    return proof, files


class RenderReceipt:
    """渲染回执：检查推进、产物登记与读写约束属于同一 module。"""

    def __init__(self):
        self._checks = {name: "NOTRUN" for name in
                        ("inputs", "assignment", "cue", "render", "media", "duration")}
        self._phase = "PREFLIGHT"
        self._context: dict = {}
        self._proof: dict = {}
        self._workspace: Path | None = None
        self._movie: Path | None = None

    @property
    def checks(self) -> dict:
        return dict(self._checks)

    @contextmanager
    def check(self, name: str):
        if name not in self._checks:
            raise ValueError(f"Unknown render check: {name}")
        self._checks[name] = "FAIL"
        if name == "render":
            self._phase = "RENDER"
        yield
        self._checks[name] = "PASS"
        if name == "render":
            self._phase = "VERIFY"

    def bind(self, context: dict) -> None:
        self._context = context
        self._checks["cue"] = ("PASS" if any(s["cue_mode"] == "exact"
                                             for s in context["scenes"]) else "SKIP")

    def assignment(self, result: dict) -> None:
        state = result["state"]
        if state not in ("PASS", "FAIL", "SKIP"):
            raise ValueError("Assignment check returned an invalid state")
        self._checks["assignment"] = state
        if state == "FAIL":
            raise ValueError(f"Unassigned components: {result['unassigned']}")

    @contextmanager
    def run(self, root: Path, *, only: str | None = None):
        if self._workspace is not None:
            raise ValueError("A receipt owns exactly one render run")
        context = self._context
        stage = "sample" if only else "render"
        selected = [only] if only else [s["id"] for s in context["scenes"]]
        if any(sid not in [s["id"] for s in context["scenes"]] for sid in selected):
            raise ValueError("--only does not match a scene")
        self._workspace = root / ".render-runs" / context["key"] / uuid.uuid4().hex
        self._workspace.mkdir(parents=True, exist_ok=False)
        self._proof = {"schema": 1, "stage": stage, "status": "FAIL", "context": context,
                       "scenes": selected, "artifacts": [],
                       "video_cache": {"generated": 0, "reused": 0}}
        try:
            yield self._workspace
            if self._proof["status"] != "PASS":
                raise ValueError("Render run ended without a completed receipt")
        except BaseException:
            self._write("FAIL")
            raise

    def cache(self, facts: dict) -> None:
        for field in ("generated", "reused"):
            self._proof["video_cache"][field] += facts[field]

    def video(self, movie: Path) -> dict:
        context = self._context
        with self.check("media"):
            result = verify_video(movie, context["config"], context["audio"])
        with self.check("duration"):
            _check_duration(result, context, self._proof["scenes"])
        with self.check("inputs"):
            check_snapshot(context)
        assert self._workspace is not None
        role = "sample" if self._proof["stage"] == "sample" else "video"
        self._proof["artifacts"].append(_artifact(role, movie, self._workspace))
        self._movie = movie
        return result

    def complete(self, *, frames: list[Path] | None = None, output: Path | None = None) -> dict:
        if self._workspace is None or self._movie is None:
            raise ValueError("Verify the run video before completing its receipt")
        stage = self._proof["stage"]
        if (stage == "sample" and output is not None) or (stage == "render" and output is None):
            raise ValueError("Sample and final render outputs have different receipt roles")
        artifacts = list(self._proof["artifacts"])
        for frame in frames or []:
            with Image.open(frame) as image:
                image.verify()
            artifacts.append(_artifact("frame", frame, self._workspace))
        if file_digest(self._movie) != artifacts[0]["sha256"]:
            raise ValueError("Verified video changed before publication")
        if output is not None:
            artifacts.append({"role": "delivery", "path": relative(output, self._workspace),
                              "sha256": artifacts[0]["sha256"]})
        proof = {**self._proof, "status": "PASS", "checks": self.checks, "artifacts": artifacts}
        _receipt_contract(proof, stage, self._workspace)
        with self.check("inputs"):
            check_snapshot(self._context)
        if output is not None:
            atomic_bytes(output, self._movie.read_bytes())
            artifacts[-1] = _artifact("delivery", output, self._workspace)
            _receipt_contract({**proof, "artifacts": artifacts}, stage, self._workspace)
        self._proof["artifacts"] = artifacts
        receipt = self._write("PASS")
        return {"status": "PASS", "stage": stage, "receipt": str(receipt),
                "output": str(output if output is not None else self._movie),
                "checks": self.checks, "video_cache": dict(self._proof["video_cache"])}

    def _write(self, status: str) -> Path:
        assert self._workspace is not None
        receipt = self._workspace / f"{self._proof['stage']}.json"
        atomic_json(receipt, {**self._proof, "status": status, "checks": self.checks})
        self._proof["status"] = status
        return receipt

    def failure(self, error: BaseException, *, blocked: bool = False) -> dict:
        if isinstance(error, CueError):
            self._checks["cue"] = "FAIL"
        if self._checks["inputs"] == "NOTRUN" and not blocked:
            self._checks["inputs"] = "FAIL"
        return {"status": "FAIL", "stage": self._phase,
                "checks": self.checks, "error": str(error)}
