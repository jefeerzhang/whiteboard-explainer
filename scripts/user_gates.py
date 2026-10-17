"""Persistent, version-bound production approvals. Not a security boundary."""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from artifacts import atomic_json, file_digest
from production import narration_config, read_document


STATE_FILE = ".user-gates.json"
GATES = tuple(f"G{i}" for i in range(6))
ACTIONS = {"boards": "G2", "tts": "G3", "sample": "G3",
           "render": "G4", "deliver": "G5"}


class GateError(SystemExit):
    pass


digest = file_digest


def load(root: Path) -> dict:
    path = root / STATE_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("expected an object")
        return data
    except (ValueError, OSError) as exc:
        raise GateError(f"BLOCKED: invalid approval file: {path}: {exc}")


def require(root: Path, gate: str, artifact: Path | None = None) -> None:
    root = root.resolve()
    data = load(root)
    for name in GATES[:GATES.index(gate) + 1]:
        record = data.get(name)
        if not isinstance(record, dict) or not record.get("artifacts"):
            raise GateError(f"BLOCKED: {name} approval missing in {root / STATE_FILE}")
        try:
            for filename, expected in record["artifacts"].items():
                if digest(Path(filename)) != expected:
                    raise GateError(f"BLOCKED: {name} artifact changed: {filename}")
        except (OSError, TypeError, AttributeError) as exc:
            raise GateError(f"BLOCKED: {name} approval cannot be verified: {exc}")
    if artifact is not None:
        filename = str(artifact.resolve())
        if filename not in data[gate]["artifacts"]:
            raise GateError(f"BLOCKED: {gate} does not approve this input: {filename}")


def approve(root: Path, gate: str, artifacts: list[Path], mode: str = "standard") -> None:
    root = root.resolve()
    index = GATES.index(gate)
    if index:
        require(root, GATES[index - 1])
    if not artifacts:
        raise GateError("BLOCKED: at least one artifact is required")
    files = {p.resolve() for p in artifacts}
    narration = {}
    # Bind referenced boards/audio too, not just the JSON pointing at them.
    for path in list(files):
        if path.suffix.lower() in (".json", ".yaml", ".yml"):
            content = read_document(path)
            if isinstance(content, dict):
                if gate == "G3" and "scenes" in content:
                    narration[str(path)] = narration_config(content, mode)
                for scene in content.get("scenes", []):
                    for key in ("image", "audio"):
                        if scene.get(key):
                            files.add((path.parent / scene[key]).resolve())
    hashes = {str(p): digest(p) for p in sorted(files)}
    print(f"Approve {gate} for these exact files:")
    for filename in hashes:
        print(f"  {filename}")
    if narration:
        print("Effective narration: " + json.dumps(narration, ensure_ascii=True))
    try:
        answer = input(f"After reviewing them, type CONFIRM {gate}: ")
    except EOFError:
        raise GateError("BLOCKED: interactive confirmation required")
    if answer != f"CONFIRM {gate}":
        raise GateError("BLOCKED: confirmation cancelled")
    # Recheck after the prompt so a changed file is never approved unseen.
    if any(digest(Path(p)) != h for p, h in hashes.items()):
        raise GateError("BLOCKED: artifact changed during confirmation")
    if index:
        require(root, GATES[index - 1])
    data = load(root)
    for name in GATES[index:]:
        data.pop(name, None)
    data[gate] = {"artifacts": hashes,
                  "confirmed_at": datetime.now(timezone.utc).isoformat()}
    if gate == "G3":
        data[gate]["narration"] = narration
    atomic_json(root / STATE_FILE, data)
    print(f"Recorded {gate}; downstream approvals cleared.")


def confirm_preview(root: Path, texts: list[str]) -> None:
    require(root, "G2")
    if len(texts) != 1 or not texts[0].strip() or len(texts[0]) > 100:
        raise GateError("BLOCKED: preview requires one nonempty text, at most 100 characters")
    try:
        answer = input("Authorize this one-line TTS request: type CONFIRM PREVIEW: ")
    except EOFError:
        raise GateError("BLOCKED: preview confirmation required")
    if answer != "CONFIRM PREVIEW":
        raise GateError("BLOCKED: preview cancelled")


def require_spec(root: Path, spec: dict, mode: str = "standard",
                 rate: str | None = None) -> Path:
    require(root, "G3")
    record = load(root.resolve())["G3"]
    for filename in record["artifacts"]:
        path = Path(filename)
        if path.suffix.lower() in (".json", ".yaml", ".yml") and read_document(path) == spec:
            snapshot = record.get("narration")
            if (isinstance(snapshot, dict)
                    and snapshot.get(filename) == narration_config(spec, mode, rate)):
                return path
            raise GateError("BLOCKED: G3 effective configuration differs or is missing; reapprove G3")
    raise GateError("BLOCKED: G3 does not approve this narration spec")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True,
                        help="Directory holding this episode's inputs and approvals")
    sub = parser.add_subparsers(dest="operation", required=True)
    approval = sub.add_parser("approve")
    approval.add_argument("gate", choices=GATES)
    approval.add_argument("--artifact", type=Path, action="append", required=True)
    approval.add_argument("--mode", choices=["standard", "fast", "scene"], default="standard",
                          help="G3 使用的配音入口；会展示实际音色、语速及处理配置")
    check = sub.add_parser("check")
    check.add_argument("gate", choices=GATES)
    check.add_argument("--artifact", type=Path)
    run = sub.add_parser("run", help="Guard a custom production command")
    run.add_argument("action", choices=ACTIONS)
    run.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.operation == "approve":
        approve(args.root, args.gate, args.artifact, args.mode)
    elif args.operation == "check":
        require(args.root, args.gate, args.artifact)
        print(f"PASS: {args.gate}")
    else:
        require(args.root, ACTIONS[args.action])
        command = args.command
        if command[:1] == ["--"]:
            command = command[1:]
        if not command:
            parser.error("a command is required")
        return subprocess.run(command, cwd=args.root, check=False).returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
