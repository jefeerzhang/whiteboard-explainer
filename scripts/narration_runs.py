"""A narration run owns its processed audio, cue plan and evidence."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from artifacts import atomic_json, file_digest, fingerprint
from media import verify


VERSION = 1


def relative(path: Path, base: Path) -> str:
    return Path(os.path.relpath(path.resolve(), base.resolve())).as_posix()


class NarrationRun:
    def __init__(self, root: Path, spec: dict, config: dict,
                 source: Path, output: Path | None = None):
        self.root = root.resolve()
        self.source = source
        self.images = {s["id"]: root / s["image"] for s in spec["scenes"] if s.get("image")}
        implementation = {
            name: file_digest(Path(__file__).with_name(name))
            for name in ("production.py", "media.py", "narration_cache.py",
                         "narration_runs.py", "build_narration.py", "gen_tts.py")
        }
        inputs = {
            "source_sha256": file_digest(source), "config": config,
            "images": {s["id"]: file_digest(root / s["image"])
                       for s in spec["scenes"] if s.get("image")},
            "implementation": implementation,
        }
        self.key = fingerprint({"version": VERSION, **inputs})
        self.id = uuid.uuid4().hex
        base = output if output is not None else root / spec.get("audio_dir", "audio/narration")
        self.directory = base / "runs" / self.key / self.id
        self.directory.mkdir(parents=True, exist_ok=False)
        self.manifest = self.directory / "manifest.json"
        self.report: dict = {
            "schema": VERSION, "stage": "narration", "status": "RUNNING",
            "run_key": self.key, "run_id": self.id, "inputs": inputs,
            "tts": {"generated": 0, "reused": 0}, "media": [], "scenes": [],
        }
        atomic_json(self.manifest, self.report)

    def record(self, sid: str, path: Path | None, regions: list, facts: list[dict]) -> None:
        for entry in facts:
            for field in ("generated", "reused"):
                self.report["tts"][field] += entry[field]
        scene: dict = {"id": sid, "regions": regions, "sources": facts}
        if path is not None:
            result = verify(path, kind="audio")
            item = {
                "path": relative(path, self.directory), "expect": result["duration"],
                "sha256": file_digest(path), "kind": "audio",
            }
            self.report["media"].append(item)
            scene.update({"audio": item["path"], "duration": result["duration"],
                          "checks": result})
        else:
            scene["checks"] = {"audio": "SKIP", "reason": "silent scene"}
        self.report["scenes"].append(scene)

    def complete(self, payload: object, name: str = "plan.json") -> dict:
        if file_digest(self.source) != self.report["inputs"]["source_sha256"]:
            raise ValueError("Narration input changed during synthesis; approve the new input")
        if any(file_digest(path) != self.report["inputs"]["images"][sid]
               for sid, path in self.images.items()):
            raise ValueError("A board changed during synthesis; approve the new input")
        atomic_json(self.directory / name, payload)
        self.report.update({
            "status": "PASS", "artifact": name,
            "artifact_sha256": file_digest(self.directory / name),
        })
        atomic_json(self.manifest, self.report)
        return {"run_key": self.key, "run_id": self.id,
                "manifest": relative(self.manifest, self.root),
                **self.report["tts"]}

    def fail(self) -> None:
        self.report["status"] = "FAIL"
        atomic_json(self.manifest, self.report)
