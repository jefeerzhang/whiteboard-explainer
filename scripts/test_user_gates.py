"""Offline regression tests; no media generation or paid API requests."""
import asyncio
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import user_gates as gates


class GateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.artifact = self.root / "script.md"
        self.artifact.write_text("reviewed", encoding="utf-8")

    def approve_through(self, last):
        for gate in gates.GATES[:gates.GATES.index(last) + 1]:
            with patch("builtins.input", return_value=f"CONFIRM {gate}"):
                gates.approve(self.root, gate, [self.artifact])

    def test_missing_or_malformed_approval_blocks(self):
        with self.assertRaises(gates.GateError):
            gates.require(self.root, "G2")
        (self.root / gates.STATE_FILE).write_text("[]", encoding="utf-8")
        with self.assertRaises(gates.GateError):
            gates.require(self.root, "G2")

    def test_cannot_skip_or_cancel_gate(self):
        with self.assertRaises(gates.GateError):
            gates.approve(self.root, "G3", [self.artifact])
        with patch("builtins.input", return_value="no"):
            with self.assertRaises(gates.GateError):
                gates.approve(self.root, "G0", [self.artifact])
        self.assertFalse((self.root / gates.STATE_FILE).exists())

    def test_changed_missing_and_unapproved_inputs_block(self):
        self.approve_through("G5")
        gates.require(self.root, "G5", self.artifact)
        with self.assertRaises(gates.GateError):
            gates.require(self.root, "G5", self.root / "other.mp4")
        self.artifact.write_text("changed", encoding="utf-8")
        with self.assertRaises(gates.GateError):
            gates.require(self.root, "G5")
        self.artifact.unlink()
        with self.assertRaises(gates.GateError):
            gates.require(self.root, "G5")

    def test_reapproval_clears_downstream(self):
        self.approve_through("G5")
        with patch("builtins.input", return_value="CONFIRM G2"):
            gates.approve(self.root, "G2", [self.artifact])
        gates.require(self.root, "G2")
        with self.assertRaises(gates.GateError):
            gates.require(self.root, "G3")

    def test_referenced_media_changes_block(self):
        image = self.root / "board.png"
        image.write_bytes(b"image")
        plan = self.root / "plan.json"
        plan.write_text(json.dumps({"scenes": [{"image": "board.png"}]}))
        with patch("builtins.input", return_value="CONFIRM G0"):
            gates.approve(self.root, "G0", [plan])
        image.write_bytes(b"different")
        with self.assertRaises(gates.GateError):
            gates.require(self.root, "G0")

    def test_preview_is_single_line_and_requires_confirmation(self):
        self.approve_through("G2")
        with self.assertRaises(gates.GateError):
            gates.confirm_preview(self.root, ["one", "two"])
        with patch("builtins.input", return_value="no"):
            with self.assertRaises(gates.GateError):
                gates.confirm_preview(self.root, ["one"])
        with patch("builtins.input", return_value="CONFIRM PREVIEW"):
            gates.confirm_preview(self.root, ["one"])
        with self.assertRaises(gates.GateError):
            gates.require(self.root, "G3")

    def test_custom_command_does_not_execute_when_blocked(self):
        marker = self.root / "executed"
        result = subprocess.run(
            [sys.executable, str(Path(gates.__file__).resolve()),
             "--root", str(self.root), "run", "boards", "--",
             sys.executable, "-c", "from pathlib import Path; Path('executed').touch()"],
            capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("BLOCKED", result.stderr)
        self.assertFalse(marker.exists())

    def test_shared_narration_function_blocks_before_output(self):
        import build_narration
        with self.assertRaises(gates.GateError):
            asyncio.run(build_narration.build({}, self.root, dry=False))
        self.assertFalse((self.root / "audio").exists())

    def test_render_blocks_before_creating_output(self):
        plan = self.root / "plan.json"
        plan.write_text('{"scenes": []}', encoding="utf-8")
        script = Path(gates.__file__).with_name("render_explainer.py")
        for flags in ([], ["--only", "s01"]):
            result = subprocess.run(
                [sys.executable, str(script), str(plan), "--out", "out/video.mp4", *flags],
                capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("BLOCKED", result.stderr)
        self.assertFalse((self.root / "out").exists())

    def test_approved_custom_command_runs(self):
        self.approve_through("G2")
        result = subprocess.run(
            [sys.executable, str(Path(gates.__file__).resolve()),
             "--root", str(self.root), "run", "boards", "--",
             sys.executable, "-c", "print('ALLOWED')"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ALLOWED", result.stdout)

    def test_narration_spec_must_match_approved_file(self):
        self.approve_through("G2")
        spec = self.root / "plan.build.json"
        spec.write_text('{"voice": "selected", "scenes": []}', encoding="utf-8")
        with patch("builtins.input", return_value="CONFIRM G3"):
            gates.approve(self.root, "G3", [spec])
        gates.require_spec(self.root, {"voice": "selected", "scenes": []})
        with self.assertRaises(gates.GateError):
            gates.require_spec(self.root, {"voice": "different", "scenes": []})

    def test_fast_tts_blocks_before_deleting_cached_audio(self):
        spec = self.root / "plan.build.json"
        spec.write_text('{"scenes": []}', encoding="utf-8")
        audio = self.root / "audio/narration/parts"
        audio.mkdir(parents=True)
        clip = audio / "cached.mp3"
        clip.write_bytes(b"small")
        script = Path(gates.__file__).with_name("build_narration_fast.py")
        result = subprocess.run([sys.executable, str(script), str(spec)],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("BLOCKED", result.stderr)
        self.assertEqual(clip.read_bytes(), b"small")

    def test_dry_run_does_not_require_approval_or_write(self):
        spec = self.root / "plan.build.json"
        spec.write_text('{"scenes": []}', encoding="utf-8")
        script = Path(gates.__file__).with_name("build_narration_fast.py")
        result = subprocess.run([sys.executable, str(script), str(spec), "--dry-run"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "audio").exists())
        self.assertFalse((self.root / gates.STATE_FILE).exists())

    def test_other_production_entries_block_without_outputs(self):
        scripts = Path(gates.__file__).parent
        spec = self.root / "boards.json"
        spec.write_text('{"scenes": []}', encoding="utf-8")
        output = self.root / "generated"
        commands = [
            ["gen_board_images.py", str(spec), "--out-dir", str(output)],
            ["gen_tts.py", str(self.root / "narration.yaml"), "--out-dir", str(output)],
            ["make_text_layer.py", "blank:10x10", "--out", str(output / "board.png"),
             "--project-root", str(self.root)],
        ]
        for script, *args in commands:
            with self.subTest(script=script):
                result = subprocess.run([sys.executable, str(scripts / script), *args],
                                        capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("BLOCKED", result.stderr)
                self.assertFalse(output.exists())

    def test_fast_rate_override_requires_new_approval(self):
        self.approve_through("G2")
        spec = self.root / "plan.build.json"
        spec.write_text('{"scenes": [], "rate": "+22%"}', encoding="utf-8")
        with patch("builtins.input", return_value="CONFIRM G3"):
            gates.approve(self.root, "G3", [spec])
        script = Path(gates.__file__).with_name("build_narration_fast.py")
        result = subprocess.run(
            [sys.executable, str(script), str(spec), "--rate=+15%"],
            capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("BLOCKED: --rate", result.stderr)
        self.assertFalse((self.root / "audio").exists())


if __name__ == "__main__":
    unittest.main()
