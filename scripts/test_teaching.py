"""Teaching-plan confirmation through the existing public CLIs."""
import json
import contextlib
import importlib
import io
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from PIL import Image


SCRIPTS = Path(__file__).resolve().parent


class TeachingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        Image.new("RGB", (64, 36), "white").save(self.root / "board.png")
        self.path = self.root / "plan.build.json"
        self.spec = {"teaching": True, "scenes": [{
            "id": "s01", "image": "board.png", "role": "rule",
            "visual": {"form": "structure", "objects": ["cause", "result"],
                       "change": "connect cause to result", "order": ["cause", "result"]},
            "regions": [{"label": "rule", "box": [0, 0, 1000, 1000], "annotation": "explain"}],
        }]}
        self.save()

    def save(self):
        self.path.write_text(json.dumps(self.spec))

    def cli(self, script, *args, input_text=None):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / script), *map(str, args)],
            capture_output=True, encoding="utf-8", text=True, input=input_text,
        )

    def test_plan_is_visible_before_confirmation_without_making_media(self):
        result = self.cli("build_narration.py", self.path, "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["teaching_plan"][0]["role"], "rule")
        self.assertEqual(report["teaching_plan"][0]["visual"]["order"], ["cause", "result"])
        self.assertFalse((self.root / "audio").exists())

    def test_design_can_be_confirmed_before_any_board_has_been_drawn(self):
        (self.root / "board.png").unlink()
        result = self.cli("build_narration.py", self.path, "--design-only")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["teaching_plan"][0]["role"], "rule")
        self.assertFalse((self.root / "audio").exists())

    def test_changed_design_requires_g2_again_before_tts(self):
        self.approvals()
        self.spec["scenes"][0]["visual"]["change"] = "a different explanation"
        self.save()
        result = self.cli("user_gates.py", "--root", self.root, "approve", "G3",
                          "--artifact", self.path, input_text="CONFIRM G3\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.cli("build_narration.py", self.path)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("G2", result.stderr)
        self.assertFalse((self.root / ".narration-cache").exists())

    def test_ordinary_explainer_is_not_forced_into_a_teaching_arc(self):
        self.spec.pop("teaching")
        self.spec["scenes"][0].pop("role")
        self.spec["scenes"][0].pop("visual")
        self.save()
        result = self.cli("build_narration.py", self.path, "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(json.loads(result.stdout)["teaching_plan"])

    def approvals(self):
        note = self.root / "review.md"
        note.write_text("reviewed")
        preview = self.cli("build_narration.py", self.path, "--design-only")
        self.assertEqual(preview.returncode, 0, preview.stderr)
        design = self.root / "design.json"
        design.write_text(preview.stdout, encoding="utf-8")
        for gate, source in (("G0", note), ("G1", note), ("G2", design), ("G3", self.path)):
            result = self.cli("user_gates.py", "--root", self.root, "approve", gate,
                              "--artifact", source, input_text=f"CONFIRM {gate}\n")
            self.assertEqual(result.returncode, 0, result.stderr)

    def run_narration(self):
        with patch.object(sys, "argv", ["build_narration", str(self.path)]), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(importlib.import_module("build_narration").main(), 0)
        return json.loads((self.root / "plan.json").read_text())

    def fake_tts(self, requests):
        def communicate(text, voice, rate):
            requests.append(text)

            class Request:
                async def save(self, filename):
                    with wave.open(str(filename), "wb") as stream:
                        stream.setnchannels(1)
                        stream.setsampwidth(2)
                        stream.setframerate(24000)
                        stream.writeframes(b"\xe8\x03" * 5520)
            return Request()
        return communicate

    def test_practice_hold_is_silent_frame_aligned_and_reuses_raw_when_fps_changes(self):
        self.spec["fps"] = 20
        question = self.spec["scenes"][0]
        question["role"] = "practice"
        question["hold"] = 5
        answer = json.loads(json.dumps(question))
        answer.update({"id": "s02", "role": "answer", "hold": 0})
        answer["regions"][0]["annotation"] = "answer"
        self.spec["scenes"].append(answer)
        self.save()
        self.approvals()
        requests = []
        with patch("edge_tts.Communicate", side_effect=self.fake_tts(requests)):
            first = self.run_narration()
            self.assertEqual(first["fps"], 20)
            scene = first["scenes"][0]
            self.assertAlmostEqual(scene["narration_duration"], 0.23)
            with wave.open(str(self.root / scene["audio"]), "rb") as audio:
                samples = audio.readframes(audio.getnframes())
                self.assertEqual(len(samples) // 2, 126000)  # 105 frames at 20 fps
                self.assertEqual(samples[11040:], b"\0" * (len(samples) - 11040))
            self.spec["fps"] = 24
            self.save()
            self.approvals()
            second = self.run_narration()
        self.assertEqual(len(requests), 2)
        self.assertNotEqual(first["scenes"][0]["audio"], second["scenes"][0]["audio"])
        self.assertLessEqual(second["scenes"][0]["regions"][0]["end"], 0.23)


if __name__ == "__main__":
    unittest.main()
