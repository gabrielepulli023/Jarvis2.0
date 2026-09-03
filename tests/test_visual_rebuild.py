import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtWidgets import QApplication, QWidget

from hud_ui import HomeView, OrbWidget, StartupView
from hud_ui.orb_widget import CANONICAL_IDLE_ASSET


ROOT = Path(__file__).resolve().parents[1]


class VisualRebuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_canonical_asset_family_is_rgba_and_complete(self):
        master = ROOT / "assets" / "orb" / "orb_idle.png"
        with Image.open(master) as image:
            self.assertEqual(image.mode, "RGBA")
            self.assertEqual((image.width, image.height), (465, 465))
            self.assertIsNotNone(image.getchannel("A").getbbox())
        for state in ("listening", "thinking", "speaking"):
            frames = sorted((ROOT / "assets" / "orb" / state).glob("frame_*.png"))
            self.assertEqual(len(frames), 24)
            modes = []
            for path in frames:
                with Image.open(path) as image:
                    modes.append(image.mode)
            self.assertTrue(all(mode == "RGBA" for mode in modes))

        realistic = ROOT / "assets" / "orb" / "orb_idle_realistic_transparent.png"
        self.assertTrue(realistic.exists())
        with Image.open(realistic) as image:
            self.assertEqual(image.mode, "RGBA")
            self.assertGreaterEqual(image.width, 1024)
            self.assertEqual(image.width, image.height)
            self.assertIsNotNone(image.getchannel("A").getbbox())

        refined = ROOT / "assets" / "orb" / CANONICAL_IDLE_ASSET
        self.assertTrue(refined.exists())
        with Image.open(refined) as image:
            self.assertEqual(image.mode, "RGBA")
            self.assertGreaterEqual(image.width, 3840)
            self.assertEqual(image.width, image.height)
            self.assertIsNotNone(image.getchannel("A").getbbox())

    def test_all_assistant_states_keep_one_static_3d_master(self):
        orb = OrbWidget()
        self.addCleanup(orb.close)

        orb.set_state("idle")
        self.assertFalse(orb.animation_active)
        self.assertEqual(orb.frame_index, 0)
        master = orb.idle_pixmap
        orb._tick()
        self.assertEqual(orb.phase, 0.0)

        for state in ("listening", "thinking", "speaking"):
            orb.set_state(state)
            self.assertFalse(orb.animation_active)
            self.assertEqual(orb.frame_index, 0)
            orb._tick()
            self.assertEqual(orb.phase, 0.0)
            self.assertIs(orb.idle_pixmap, master)

        orb.set_state("idle")
        orb._tick()
        self.assertEqual(orb.phase, 0.0)
        orb.set_state("listening")
        orb._tick()
        self.assertEqual(orb.phase, 0.0)

        orb.set_state("idle")
        self.assertFalse(orb.animation_active)
        self.assertEqual(orb.frame_index, 0)

    def test_static_render_keeps_the_master_unchanged(self):
        orb = OrbWidget()
        self.addCleanup(orb.close)
        source = orb.idle_pixmap.scaled(512, 512)
        orb.phase = 0.0
        first = orb._animated_pixmap(source)
        orb.phase = 0.5
        second = orb._animated_pixmap(source)
        self.assertEqual(first.toImage(), second.toImage())

    def test_startup_reuses_the_canonical_orb_renderer(self):
        startup = StartupView()
        self.addCleanup(startup.close)
        startup.resize(1280, 720)
        startup.set_status("INITIALIZING SYSTEMS")
        startup.set_progress(62)
        startup._tick()
        self.assertIsInstance(startup.orb, OrbWidget)
        self.assertEqual(startup.orb.state, "idle")
        self.assertTrue(any(isinstance(child, OrbWidget) for child in startup.findChildren(QWidget)))

    def test_home_and_startup_share_the_exact_same_idle_3d_asset(self):
        home = HomeView()
        startup = StartupView()
        self.addCleanup(home.close)
        self.addCleanup(startup.close)

        self.assertIs(home.orb.idle_pixmap, startup.orb.idle_pixmap)
        self.assertFalse(home.orb.idle_pixmap.isNull())


if __name__ == "__main__":
    unittest.main()
