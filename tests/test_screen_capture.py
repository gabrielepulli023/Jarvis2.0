import unittest

from PIL import Image

from jarvis_perception.capture import ScreenCaptureEngine


class ScreenCaptureTests(unittest.TestCase):
    def test_capture_is_volatile_and_reports_visual_diff(self):
        colors = iter(["black", "black", "white"])
        engine = ScreenCaptureEngine(lambda region=None: Image.new("RGB", (20, 10), next(colors)))
        first = engine.full(); second = engine.full(); third = engine.full()
        self.assertEqual(first.changed_ratio, 1.0); self.assertEqual(second.changed_ratio, 0.0); self.assertEqual(third.changed_ratio, 1.0)
        self.assertTrue(first.jpeg.startswith(b"\xff\xd8"))

    def test_region_validation_and_metadata(self):
        seen = []
        engine = ScreenCaptureEngine(lambda region=None: (seen.append(region) or Image.new("RGB", (region[2], region[3]), "blue")))
        frame = engine.region(-100, 20, 300, 200)
        self.assertEqual(seen, [(-100, 20, 300, 200)]); self.assertEqual(frame.region, (-100, 20, 300, 200)); self.assertEqual(frame.source, "region")
        with self.assertRaises(ValueError): engine.region(0, 0, 0, 20)


if __name__ == "__main__": unittest.main()
