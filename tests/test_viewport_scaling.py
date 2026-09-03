import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from hud_ui import HomeView, StartupView
from hud_ui.diagnostics import collect_screen_diagnostics
from hud_ui.viewport import (
    HOME_ORB,
    REFERENCE_ASPECT,
    REFERENCE_HEIGHT,
    REFERENCE_WIDTH,
    STARTUP_MARK,
    design_transform,
    mapped_geometry,
)


class ViewportScalingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_reference_design_has_one_uniform_transform(self):
        transform = design_transform(REFERENCE_WIDTH, REFERENCE_HEIGHT)
        self.assertEqual(transform.scale, 1.0)
        self.assertEqual(transform.offset_x, 0.0)
        self.assertEqual(transform.offset_y, 0.0)
        self.assertAlmostEqual(REFERENCE_ASPECT, 1672 / 941)

    def test_letterboxing_preserves_square_orb_at_all_requested_sizes(self):
        for width, height in ((1280, 720), (1366, 768), (1600, 900), (1920, 1080), (2560, 1440)):
            transform = design_transform(width, height)
            left, top, orb_width, orb_height = mapped_geometry(transform, HOME_ORB)
            self.assertEqual(orb_width, orb_height, (width, height))
            self.assertGreaterEqual(left, 0)
            self.assertGreaterEqual(top, 0)
            self.assertLessEqual(left + orb_width, width)
            self.assertLessEqual(top + orb_height, height)

    def test_home_and_startup_children_follow_the_same_dpi_neutral_mapping(self):
        home = HomeView()
        startup = StartupView()
        self.addCleanup(home.close)
        self.addCleanup(startup.close)
        home.resize(1920, 1080)
        startup.resize(1920, 1080)
        self.assertEqual((home.orb.width(), home.orb.height()), (home.orb.height(), home.orb.width()))
        self.assertEqual((startup.orb.width(), startup.orb.height()), (startup.orb.height(), startup.orb.width()))
        expected = mapped_geometry(design_transform(1920, 1080), STARTUP_MARK)
        self.assertEqual(startup.orb.geometry().getRect(), expected)

    def test_diagnostics_report_logical_physical_and_design_metrics(self):
        home = HomeView()
        self.addCleanup(home.close)
        home.resize(1672, 941)
        values = collect_screen_diagnostics(self.app, home)
        for key in ("physical_screen_resolution", "available_geometry", "device_pixel_ratio", "logical_dpi", "physical_dpi", "window_geometry", "design_viewport_geometry", "final_scale"):
            self.assertIn(key, values)
        self.assertEqual(values["design_viewport"], {"width": 1672, "height": 941})
        self.assertGreater(values["final_scale"], 0)


if __name__ == "__main__":
    unittest.main()
