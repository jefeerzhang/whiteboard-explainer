"""Video production CLI tests with a local, deterministic engine substitute."""
from __future__ import annotations

import contextlib
import importlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw


class VideoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        Image.new("RGB", (64, 36), "white").save(self.root / "board.png")
        self.plan = {"scenes": [{
            "id": "s01", "image": "board.png", "duration": 0.5, "regions": [],
        }]}
        self.path = self.root / "plan.json"
        self.save()
        note = self.root / "review.md"
        note.write_text("reviewed")
        for gate in ("G0", "G1", "G2", "G3"):
            self.approve(gate, note)
        self.calls = []

    def save(self):
        self.path.write_text(json.dumps(self.plan), encoding="utf-8")

    def approve(self, gate, artifact):
        import user_gates
        with patch("builtins.input", return_value=f"CONFIRM {gate}"), contextlib.redirect_stdout(io.StringIO()):
            user_gates.approve(self.root, gate, [artifact])

    def fake_engine(self, fade_duration=0.1):
        calls = self.calls

        class Engine:
            def render_to_file(self, image, draw, total, filename, fps=24,
                               bitrate="1500k", element_plan=None):
                calls.append({"duration": total, "fps": fps, "windows": element_plan})
                color = "0x" + "".join(f"{int(v):02x}" for v in image[0, 0, :3])
                height, width = image.shape[:2]
                subprocess.run(
                    ["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
                     f"color=c={color}:s={width}x{height}:r={fps}", "-t", str(total),
                     "-c:v", "libx264", "-pix_fmt", "yuv420p", filename],
                    check=True, capture_output=True,
                )

        engine = Engine()
        engine.fade_duration = fade_duration
        return engine

    def render(self, *args):
        result, output = self.invoke(*args)
        self.assertEqual(result, 0, output)
        return output

    def invoke(self, *args):
        module = importlib.import_module("render_explainer")
        output = io.StringIO()
        with patch.object(sys, "argv", [
            "render_explainer", str(self.path), "--out", str(self.root / "out/movie.mp4"), *args,
        ]), patch.object(module, "WhiteboardAnimator", side_effect=self.fake_engine), \
                contextlib.redirect_stdout(output):
            try:
                result = module.main()
            except SystemExit as exc:
                result = exc.code if isinstance(exc.code, int) else 1
                print(str(exc))
        return result, output.getvalue()

    def report(self, text):
        return json.loads(next(line[7:] for line in text.splitlines() if line.startswith("REPORT ")))

    def confirm_design(self):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("build_narration.py")),
             str(self.path), "--dry-run"], capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        design = self.root / "design.json"
        design.write_text(result.stdout, encoding="utf-8")
        self.approve("G2", design)
        self.approve("G3", self.root / "review.md")

    def test_board_and_quality_changes_invalidate_video_cache(self):
        self.render("--only", "s01")
        self.render("--only", "s01")
        self.assertEqual(len(self.calls), 1)
        Image.new("RGB", (64, 36), "#aabbcc").save(self.root / "board.png")
        self.render("--only", "s01")
        self.assertEqual(len(self.calls), 2)
        self.render("--only", "s01", "--quality", "high")
        self.assertEqual(len(self.calls), 3)

    def test_sample_receipt_binds_full_render_configuration(self):
        sample = self.report(self.render("--only", "s01"))
        proof = json.loads(Path(sample["receipt"]).read_text())
        self.assertEqual(proof["stage"], "sample")
        self.assertEqual(len([a for a in proof["artifacts"] if a["role"] == "frame"]), 2)
        self.approve("G4", Path(sample["receipt"]))
        code, output = self.invoke("--quality", "high")
        self.assertNotEqual(code, 0)
        self.assertIn("G4", output)
        self.assertEqual(len(self.calls), 1)

    def test_canvas_change_rebuilds_at_the_requested_dimensions(self):
        self.render("--only", "s01")
        self.plan["canvas"] = [128, 72]
        self.save()
        sample = self.report(self.render("--only", "s01"))
        self.assertEqual(len(self.calls), 2)
        from media import verify
        self.assertEqual(verify(Path(sample["output"]))["video"]["width"], 128)

    def test_g5_rejects_a_note_even_when_g4_is_valid(self):
        import user_gates
        sample = self.report(self.render("--only", "s01"))
        self.approve("G4", Path(sample["receipt"]))
        with self.assertRaises(user_gates.GateError):
            self.approve("G5", self.root / "review.md")
        with self.assertRaises(user_gates.GateError):
            self.approve("G5", Path(sample["receipt"]))

    def test_complete_video_is_the_only_deliverable_approved_by_g5(self):
        import user_gates
        sample = self.report(self.render("--only", "s01"))
        self.approve("G4", Path(sample["receipt"]))
        final = self.report(self.render())
        self.assertEqual(final["video_cache"], {"generated": 0, "reused": 1})
        self.approve("G5", Path(final["receipt"]))
        user_gates.require(self.root, "G5", Path(final["output"]))
        verified = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("verify_media.py")),
             "--manifest", final["receipt"]], capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        Path(final["output"]).write_bytes(b"changed")
        with self.assertRaises(user_gates.GateError):
            user_gates.require(self.root, "G5")

    def test_practice_hold_freezes_before_the_answer_scene(self):
        Image.new("RGB", (64, 36), "red").save(self.root / "board.png")
        Image.new("RGB", (64, 36), "blue").save(self.root / "answer.png")
        self.plan.update({"teaching": True, "fps": 20})
        visual = {"form": "text", "objects": ["question"],
                  "change": "show the question", "order": ["question"]}
        for filename, samples in (("question.wav", 126000), ("answer.wav", 6000)):
            with wave.open(str(self.root / filename), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(24000)
                audio.writeframes(b"\xe8\x03" * 5520 + b"\0\0" * (samples - 5520))
        question = self.plan["scenes"][0]
        question.update({"audio": "question.wav", "narration_duration": 0.23,
                         "role": "practice", "hold": 5, "visual": visual})
        question.pop("duration")
        self.plan["scenes"].append({
            "id": "s02", "image": "answer.png", "audio": "answer.wav", "regions": [],
            "narration_duration": 0.23, "hold": 0, "role": "answer", "visual": visual,
        })
        self.save()
        self.confirm_design()
        sample = self.report(self.render("--only", "s01"))
        self.assertLessEqual(self.calls[0]["duration"], 0.25)
        self.approve("G4", Path(sample["receipt"]))
        final = self.report(self.render())

        def pixel(seconds):
            result = subprocess.run(
                ["ffmpeg", "-v", "error", "-ss", str(seconds), "-i", final["output"],
                 "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
                check=True, capture_output=True,
            )
            return Image.open(io.BytesIO(result.stdout)).convert("RGB").getpixel((20, 20))

        first, held, answer = pixel(1), pixel(4.5), pixel(5.4)
        self.assertEqual(first, held)
        self.assertGreater(held[0], 240)
        self.assertLess(held[2], 10)
        self.assertGreater(answer[2], 240)

    def test_hold_at_29_fps_preserves_the_exact_frame_count(self):
        self.plan.update({"teaching": True, "fps": 29})
        visual = {"form": "text", "objects": ["question"],
                  "change": "keep the question visible", "order": ["question"]}
        scenes = []
        for sid, samples, frames, role, hold in (
                ("s01", 125794, 152, "practice", 5), ("s02", 5794, 7, "answer", 0)):
            audio = self.root / f"{sid}.wav"
            with wave.open(str(audio), "wb") as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(24000)
                stream.writeframes(b"\xe8\x03" * 5520 + b"\0\0" * (samples - 5520))
            scenes.append({
                "id": sid, "image": "board.png", "audio": audio.name, "regions": [],
                "role": role, "visual": visual, "hold": hold,
                "narration_duration": 0.23, "fps": 29, "frames": frames,
            })
        self.plan["scenes"] = scenes
        self.save()
        self.confirm_design()
        sample = self.report(self.render("--only", "s01"))
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
             "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", sample["output"]],
            capture_output=True, text=True, check=True,
        )
        self.assertEqual(int(result.stdout.strip()), 152)

    def test_narration_provenance_cannot_point_at_a_missing_run(self):
        self.plan["narration"] = {"manifest": "missing.json", "run_id": "old", "run_key": "old"}
        self.save()
        code, output = self.invoke("--only", "s01")
        self.assertNotEqual(code, 0)
        self.assertIn("narration", output.lower())
        self.assertEqual(self.calls, [])

    def test_existing_output_is_not_overwritten_without_force(self):
        target = self.root / "out/movie.mp4"
        target.parent.mkdir()
        target.write_bytes(b"legacy user output")
        sample = self.report(self.render("--only", "s01"))
        self.approve("G4", Path(sample["receipt"]))
        code, output = self.invoke()
        self.assertNotEqual(code, 0)
        self.assertIn("--force", output)
        self.assertEqual(target.read_bytes(), b"legacy user output")

    def test_invalid_cue_stops_before_rendering_and_leaves_media_notrun(self):
        self.plan["scenes"][0]["regions"] = [{
            "label": "bad", "box": [0, 0, 1000, 1000], "start": 0, "end": 100,
        }]
        self.save()
        code, output = self.invoke("--only", "s01")
        report = self.report(output)
        self.assertNotEqual(code, 0)
        self.assertEqual(self.calls, [])
        self.assertEqual(report["checks"]["media"], "NOTRUN")
        self.assertEqual(report["checks"]["cue"], "FAIL")

    def test_modified_sample_frame_cannot_be_approved(self):
        import user_gates
        sample = self.report(self.render("--only", "s01"))
        receipt = Path(sample["receipt"])
        proof = json.loads(receipt.read_text())
        frame = next(a for a in proof["artifacts"] if a["role"] == "frame")
        (receipt.parent / frame["path"]).write_bytes(b"changed")
        with self.assertRaises(user_gates.GateError):
            self.approve("G4", receipt)

    def test_legacy_g4_requires_a_new_sample(self):
        import user_gates
        state = user_gates.load(self.root)
        note = self.root / "review.md"
        state["G4"] = {"artifacts": {str(note): user_gates.digest(note)}}
        (self.root / ".user-gates.json").write_text(json.dumps(state))
        code, output = self.invoke()
        self.assertNotEqual(code, 0)
        self.assertIn("G4", output)
        self.assertEqual(self.calls, [])

    def test_unassigned_components_stop_before_the_drawing_backend(self):
        image = Image.new("RGB", (64, 36), "white")
        ImageDraw.Draw(image).rectangle((20, 10, 40, 25), fill="black")
        image.save(self.root / "board.png")
        self.plan["scenes"][0]["regions"] = [{"box": [0, 0, 100, 100]}]
        self.save()

        class Detector:
            def __init__(self, **kwargs):
                pass

            def _downscale(self, image):
                return image

            def _enforce_white_bg(self, image):
                return image

            def _find_components(self, image):
                return [{"left": 20, "top": 10, "right": 41, "bottom": 26}]

        with patch("check_assignment.WhiteboardAnimator", Detector):
            code, output = self.invoke("--only", "s01")
        report = self.report(output)
        self.assertNotEqual(code, 0)
        self.assertEqual(report["checks"]["assignment"], "FAIL")
        self.assertEqual(report["checks"]["render"], "NOTRUN")
        self.assertEqual(self.calls, [])

    def test_engine_failure_does_not_claim_final_media_checks_passed(self):
        with patch.object(self, "fake_engine", side_effect=RuntimeError("engine failed")):
            code, output = self.invoke("--only", "s01")
        report = self.report(output)
        self.assertNotEqual(code, 0)
        self.assertEqual(report["checks"]["render"], "FAIL")
        self.assertEqual(report["checks"]["media"], "NOTRUN")
        receipts = list((self.root / ".render-runs").rglob("sample.json"))
        self.assertEqual(len(receipts), 1)
        self.assertEqual(json.loads(receipts[0].read_text())["status"], "FAIL")

    def test_new_g3_cannot_render_native_audio_from_the_previous_configuration(self):
        source = self.root / "plan.build.json"
        spec = {"voice": "zh-CN-XiaoyiNeural", "scenes": [{
            "id": "s01", "image": "board.png", "regions": [
                {"label": "spoken", "box": [0, 0, 1000, 1000], "annotation": "question"},
            ],
        }]}
        source.write_text(json.dumps(spec))
        self.approve("G3", source)

        class Request:
            async def save(self, filename):
                with wave.open(str(filename), "wb") as audio:
                    audio.setnchannels(1)
                    audio.setsampwidth(2)
                    audio.setframerate(24000)
                    audio.writeframes(b"\xe8\x03" * 6000)

        with patch("edge_tts.Communicate", return_value=Request()), \
                patch.object(sys, "argv", ["build_narration", str(source)]), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(importlib.import_module("build_narration").main(), 0)
        self.render("--only", "s01")
        spec["voice"] = "zh-CN-YunxiNeural"
        source.write_text(json.dumps(spec))
        self.approve("G3", source)
        code, output = self.invoke("--only", "s01")
        self.assertNotEqual(code, 0)
        self.assertIn("narration", output.lower())
        self.assertEqual(len(self.calls), 1)


if __name__ == "__main__":
    unittest.main()
