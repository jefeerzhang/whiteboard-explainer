"""Production CLI regression tests; all synthesis stays offline."""
from __future__ import annotations

import json
import contextlib
import importlib
import io
import subprocess
import sys
import tempfile
import unittest
import wave
import hashlib
from pathlib import Path
from unittest.mock import patch

from PIL import Image


SCRIPTS = Path(__file__).resolve().parent


class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        Image.new("RGB", (64, 36), "white").save(self.root / "board.png")
        self.spec = {
            "voice": "zh-CN-XiaoyiNeural",
            "rate": "+15%",
            "scenes": [{
                "id": "s01", "image": "board.png",
                "regions": [{"box": [0, 0, 1000, 1000], "annotation": "a_b"}],
            }],
        }
        self.path = self.root / "plan.build.json"
        self.save()

    def save(self):
        self.path.write_text(json.dumps(self.spec), encoding="utf-8")

    def cli(self, script, *args, input_text=None):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / script), *map(str, args)],
            capture_output=True, text=True, encoding="utf-8", input=input_text,
        )

    def test_dry_run_reports_effective_config_without_production_outputs(self):
        result = self.cli("build_narration.py", self.path, "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["config"]["voice"], "zh-CN-XiaoyiNeural")
        self.assertEqual(report["config"]["rate"], "+15%")
        self.assertEqual(report["status"], "PASS")
        self.assertFalse((self.root / "audio").exists())
        self.assertFalse((self.root / "plan.json").exists())

    def test_invalid_box_is_rejected_before_any_production(self):
        self.spec["scenes"][0]["regions"][0]["box"] = [0, 900, 1000, 100]
        self.save()
        result = self.cli("build_narration.py", self.path, "--dry-run")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("s01", result.stderr)
        self.assertIn("box", result.stderr)
        self.assertFalse((self.root / "audio").exists())

    def test_fast_and_scene_clis_share_inspection_and_validate_fonts(self):
        result = self.cli("build_narration_fast.py", self.path, "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["config"]["rate"], "+15%")
        self.spec["scenes"] = [{"id": "s01", "text": "a_b"}]
        self.save()
        result = self.cli("gen_tts.py", self.path, "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["config"]["voice"], "zh-CN-XiaoyiNeural")
        self.spec["font"] = "missing.ttf"
        self.spec["scenes"] = [{"id": "s01", "image": "board.png", "regions": []}]
        self.save()
        result = self.cli("build_narration.py", self.path, "--preflight")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("font", result.stderr)

    def approve(self, mode="standard"):
        note = self.root / "review.md"
        note.write_text("fixture reviewed", encoding="utf-8")
        for gate in ("G0", "G1", "G2", "G3"):
            artifact = self.path if gate == "G3" else note
            result = self.cli(
                "user_gates.py", "--root", self.root, "approve", gate,
                "--artifact", artifact, *(["--mode", mode] if gate == "G3" else []),
                input_text=f"CONFIRM {gate}\n",
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_g3_records_the_effective_fast_configuration(self):
        self.spec.pop("rate")
        self.save()
        self.approve("fast")
        state = json.loads((self.root / ".user-gates.json").read_text(encoding="utf-8"))
        config = state["G3"]["narration"][str(self.path.resolve())]
        self.assertEqual(config["rate"], "+22%")
        self.assertTrue(config["trim"])
        result = self.cli("build_narration.py", self.path)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("G3", result.stderr)
        self.assertFalse((self.root / "audio").exists())

    def run_narration(self, script="build_narration", *args):
        output = io.StringIO()
        with patch.object(sys, "argv", [script, str(self.path), *args]), contextlib.redirect_stdout(output):
            result = importlib.import_module(script).main()
        self.assertIn(result, (None, 0))
        return output.getvalue()

    def fake_tts(self, requests):
        def communicate(text, voice, rate):
            requests.append((text, voice, rate))

            class Request:
                async def save(self, filename):
                    with wave.open(str(filename), "wb") as stream:
                        stream.setnchannels(1)
                        stream.setsampwidth(2)
                        stream.setframerate(24000)
                        stream.writeframes(b"\xe8\x03" * 6000)

            return Request()
        return communicate

    def test_changed_spoken_text_regenerates_only_the_affected_audio(self):
        self.spec["scenes"][0]["regions"].append({
            "box": [0, 0, 1000, 1000], "annotation": "unchanged",
        })
        self.save()
        self.approve()
        requests = []
        with patch("edge_tts.Communicate", side_effect=self.fake_tts(requests)):
            self.run_narration()
            self.assertEqual(len(requests), 2)
            self.assertEqual(requests[0], ("a_b", "zh-CN-XiaoyiNeural", "+15%"))
            self.spec["scenes"][0]["regions"][0]["spoken_text"] = "A B"
            self.save()
            self.approve()
            self.run_narration()
            self.assertEqual(len(requests), 3)
            self.assertEqual(requests[-1][0], "A B")
            self.run_narration()
            self.assertEqual(len(requests), 3)
        plan = json.loads((self.root / "plan.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["scenes"][0]["regions"][0]["annotation"], "a_b")

    def test_scene_cli_does_not_reuse_audio_after_voice_changes(self):
        self.spec["scenes"] = [{"id": "s01", "text": "a_b", "spoken_text": "A B"}]
        self.save()
        self.approve("scene")
        requests = []
        output = self.root / "scene-audio"
        with patch("edge_tts.Communicate", side_effect=self.fake_tts(requests)):
            self.run_narration("gen_tts", "--out-dir", str(output))
            self.spec["voice"] = "zh-CN-YunxiNeural"
            self.save()
            self.approve("scene")
            self.run_narration("gen_tts", "--out-dir", str(output))
        self.assertEqual([r[1] for r in requests], ["zh-CN-XiaoyiNeural", "zh-CN-YunxiNeural"])

    def test_each_run_owns_audio_cues_and_reuse_facts(self):
        self.spec["scenes"][0]["regions"].append({
            "box": [0, 0, 1000, 1000], "annotation": "second",
        })
        self.save()
        self.approve()
        requests = []
        with patch("edge_tts.Communicate", side_effect=self.fake_tts(requests)):
            self.run_narration()
            first = json.loads((self.root / "plan.json").read_text())
            first_audio = self.root / first["scenes"][0]["audio"]
            original_bytes = first_audio.read_bytes()
            self.spec["gap"] = 0.8
            self.save()
            self.approve()
            self.run_narration()
        second = json.loads((self.root / "plan.json").read_text())
        report = json.loads((self.root / second["narration"]["manifest"]).read_text())
        self.assertEqual(len(requests), 2)
        self.assertNotEqual(first["scenes"][0]["audio"], second["scenes"][0]["audio"])
        self.assertEqual(first_audio.read_bytes(), original_bytes)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["tts"], {"generated": 0, "reused": 2})
        self.assertGreater(second["scenes"][0]["regions"][1]["start"],
                           first["scenes"][0]["regions"][1]["start"])
        result = self.cli("verify_media.py", "--manifest",
                          self.root / second["narration"]["manifest"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_fast_processing_reuses_raw_audio_but_owns_processed_results(self):
        self.approve()
        requests = []
        with patch("edge_tts.Communicate", side_effect=self.fake_tts(requests)):
            self.run_narration()
            first = json.loads((self.root / "plan.json").read_text())
            self.approve("fast")
            self.run_narration("build_narration_fast")
        second = json.loads((self.root / "plan.json").read_text())
        self.assertEqual(len(requests), 1)
        self.assertNotEqual(first["narration"]["run_key"], second["narration"]["run_key"])
        report = json.loads((self.root / second["narration"]["manifest"]).read_text())
        self.assertTrue(report["inputs"]["config"]["trim"])
        self.assertEqual(report["tts"], {"generated": 0, "reused": 1})

    def test_legacy_audio_is_preserved_and_corrupt_cache_is_not_reused(self):
        legacy = self.root / "audio/narration/parts/s01_r00.mp3"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b"legacy")
        self.approve()
        requests = []
        with patch("edge_tts.Communicate", side_effect=self.fake_tts(requests)):
            self.run_narration()
            raw = next((self.root / ".narration-cache/raw").glob("*.mp3"))
            raw.write_bytes(b"corrupt")
            metadata_path = raw.with_suffix(".mp3.json")
            metadata = json.loads(metadata_path.read_text())
            metadata["sha256"] = hashlib.sha256(raw.read_bytes()).hexdigest()
            metadata_path.write_text(json.dumps(metadata))
            self.run_narration()
        self.assertEqual(len(requests), 2)
        self.assertEqual(legacy.read_bytes(), b"legacy")

    def test_failed_synthesis_does_not_replace_previous_plan(self):
        self.approve()
        with patch("edge_tts.Communicate", side_effect=self.fake_tts([])):
            self.run_narration()
        original = (self.root / "plan.json").read_bytes()
        self.spec["scenes"][0]["regions"][0]["annotation"] = "new text"
        self.save()
        self.approve()

        class InvalidRequest:
            async def save(self, filename):
                Path(filename).write_bytes(b"not media" * 400)

        with patch("edge_tts.Communicate", return_value=InvalidRequest()):
            with self.assertRaises(ValueError):
                self.run_narration()
        self.assertEqual((self.root / "plan.json").read_bytes(), original)
        reports = [json.loads(p.read_text()) for p in
                   (self.root / "audio/narration/runs").rglob("manifest.json")]
        self.assertEqual(sorted(r["status"] for r in reports), ["FAIL", "PASS"])

    def test_invalid_input_after_approval_calls_no_tts(self):
        self.spec["scenes"][0]["regions"][0]["box"] = [0, 900, 1000, 100]
        self.save()
        self.approve()
        requests = []
        with patch("edge_tts.Communicate", side_effect=self.fake_tts(requests)):
            with self.assertRaises(ValueError):
                self.run_narration()
        self.assertEqual(requests, [])
        self.assertFalse((self.root / "audio").exists())

    def test_source_changed_during_synthesis_cannot_publish_a_successful_plan(self):
        self.approve()
        factory = self.fake_tts([])

        def changing(text, voice, rate):
            self.spec["rate"] = "+30%"
            self.save()
            return factory(text, voice, rate)

        with patch("edge_tts.Communicate", side_effect=changing):
            with self.assertRaises((ValueError, SystemExit)):
                self.run_narration()
        self.assertFalse((self.root / "plan.json").exists())

    def test_competing_producer_is_rejected_before_another_tts_request(self):
        self.approve()
        attempts = []
        factory = self.fake_tts([])

        def competing(text, voice, rate):
            attempts.append(self.cli("build_narration.py", self.path))
            return factory(text, voice, rate)

        with patch("edge_tts.Communicate", side_effect=competing):
            self.run_narration()
        self.assertEqual(len(attempts), 1)
        self.assertNotEqual(attempts[0].returncode, 0)
        self.assertIn("Another narration producer", attempts[0].stderr)

    def test_legacy_g3_requires_reconfirmation_before_production(self):
        self.approve()
        path = self.root / ".user-gates.json"
        state = json.loads(path.read_text())
        state["G3"].pop("narration")
        path.write_text(json.dumps(state))
        result = self.cli("build_narration.py", self.path)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reapprove G3", result.stderr)
        self.assertFalse((self.root / "audio").exists())

    def test_ordinary_approval_accepts_json_array_material(self):
        material = self.root / "outline.json"
        material.write_text('["review item"]')
        result = self.cli(
            "user_gates.py", "--root", self.root, "approve", "G0",
            "--artifact", material, input_text="CONFIRM G0\n",
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_documented_inspection_contract_matches_cli(self):
        document = (SCRIPTS.parent / "references/narration-workflow.md").read_text(encoding="utf-8")
        self.assertIn("NOTRUN", document)
        self.assertIn("--mode fast", document)
        self.assertIn("原始合成与裁静音/格式转换分开", document)
        result = self.cli("build_narration.py", self.path, "--dry-run")
        self.assertEqual(json.loads(result.stdout)["runtime"], "NOTRUN")
        self.assertFalse((self.root / ".narration-cache").exists())


if __name__ == "__main__":
    unittest.main()
