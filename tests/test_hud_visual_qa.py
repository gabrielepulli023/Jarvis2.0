import importlib.util
import sys
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = Path(__file__).with_name("hud_visual_qa.py")
SPEC = importlib.util.spec_from_file_location("jarvis_hud_visual_qa", MODULE_PATH)
hud_visual_qa = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = hud_visual_qa
SPEC.loader.exec_module(hud_visual_qa)


class HUDVisualQATests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference_path = Path(
            r"C:\Users\gabri\Downloads\552694ef-37c5-4251-988f-f02040c0cc00.png"
        )
        cls.baseline_path = ROOT / "tests" / "fixtures" / "assistant_clean_baseline.png"

    def test_identical_image_scores_nearly_one_hundred(self):
        if not self.reference_path.is_file():
            self.skipTest("reference attachment is unavailable")
        with Image.open(self.reference_path) as image:
            first = image.convert("RGB")
            second = image.convert("RGB")
        result = hud_visual_qa.compare_images(first, second)
        self.assertGreaterEqual(result["comparison"]["overall_score"], 99.9)
        self.assertTrue(all(gate["passed"] for gate in result["comparison"]["quality_gates"]))
        self.assertFalse(result["comparison"]["tofu_suspected"])
        self.assertEqual(
            result["reference"]["metrics"]["visible_ratio"],
            result["candidate"]["metrics"]["visible_ratio"],
        )

    def test_old_dashboard_is_detected_as_materially_sparser(self):
        if not self.reference_path.is_file():
            self.skipTest("reference attachment is unavailable")
        with Image.open(self.reference_path) as image:
            reference = image.convert("RGB")
        with Image.open(self.baseline_path) as image:
            baseline = image.convert("RGB")
        result = hud_visual_qa.compare_images(reference, baseline)
        comparison = result["comparison"]
        self.assertLess(comparison["overall_score"], 60.0)
        self.assertLess(comparison["candidate_to_reference_visible_density"], 0.5)
        self.assertLess(comparison["candidate_to_reference_bright_density"], 0.5)
        self.assertIn("core_visual_similarity", comparison)
        self.assertIn("typography_similarity", comparison)
        self.assertIn("structural_alignment", comparison)

    def test_resolution_change_does_not_create_a_false_redesign(self):
        if not self.reference_path.is_file():
            self.skipTest("reference attachment is unavailable")
        with Image.open(self.reference_path) as image:
            reference = image.convert("RGB")
        resized = reference.resize((1280, 720), Image.Resampling.LANCZOS)
        result = hud_visual_qa.compare_images(reference, resized)
        self.assertGreaterEqual(result["comparison"]["overall_score"], 88.0)
        self.assertLess(result["comparison"]["aspect_ratio_delta"], 0.01)


if __name__ == "__main__":
    unittest.main()
