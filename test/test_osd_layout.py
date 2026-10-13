import unittest

from utils.osd_layout import (
    DEFAULT_OSD_CFG,
    compute_osd_pos,
    display_numbers,
    layout_tiles,
    monitor_number,
    normalize_osd_cfg,
    resolve_monitor,
)


class TestNormalizeOsdCfg(unittest.TestCase):
    def test_missing_cfg_uses_defaults(self):
        self.assertEqual(normalize_osd_cfg(None), DEFAULT_OSD_CFG)

    def test_invalid_values_are_fixed(self):
        cfg = normalize_osd_cfg(
            {"corner": "middle", "offset_x": -5, "offset_y": "abc", "monitor": None, "x": 1}
        )
        self.assertEqual(cfg["corner"], "top_left")
        self.assertEqual(cfg["offset_x"], 0)
        self.assertEqual(cfg["offset_y"], DEFAULT_OSD_CFG["offset_y"])
        self.assertEqual(cfg["monitor"], "")
        self.assertNotIn("x", cfg)

    def test_offset_upper_clamp(self):
        self.assertEqual(normalize_osd_cfg({"offset_x": 99999})["offset_x"], 2000)


class TestComputeOsdPos(unittest.TestCase):
    screen = (0, 0, 1920, 1080)
    size = (200, 100)

    def test_corners(self):
        self.assertEqual(compute_osd_pos(self.screen, self.size, "top_left", 10, 20), (10, 20))
        self.assertEqual(compute_osd_pos(self.screen, self.size, "top_right", 10, 20), (1710, 20))
        self.assertEqual(compute_osd_pos(self.screen, self.size, "bottom_left", 10, 20), (10, 960))
        self.assertEqual(compute_osd_pos(self.screen, self.size, "bottom_right", 10, 20), (1710, 960))

    def test_negative_origin_screen(self):
        left = (-2560, -200, 2560, 1440)
        self.assertEqual(compute_osd_pos(left, self.size, "top_left", 0, 0), (-2560, -200))
        self.assertEqual(compute_osd_pos(left, self.size, "bottom_right", 0, 0), (-200, 1140))

    def test_offset_clamped_inside_screen(self):
        self.assertEqual(compute_osd_pos(self.screen, self.size, "top_left", 5000, 5000), (1720, 980))
        self.assertEqual(compute_osd_pos(self.screen, self.size, "bottom_right", 5000, 5000), (0, 0))


class TestResolveMonitor(unittest.TestCase):
    avail = ["\\\\.\\DISPLAY1", "\\\\.\\DISPLAY2"]

    def test_saved_exists(self):
        self.assertEqual(resolve_monitor(self.avail[1], self.avail, self.avail[0]), (self.avail[1], False))

    def test_saved_missing_falls_back_to_current(self):
        self.assertEqual(resolve_monitor("\\\\.\\DISPLAY9", self.avail, self.avail[1]), (self.avail[1], True))

    def test_empty_saved_falls_back_to_current(self):
        self.assertEqual(resolve_monitor("", self.avail, self.avail[0]), (self.avail[0], True))

    def test_current_missing_uses_first(self):
        self.assertEqual(resolve_monitor("x", self.avail, None), (self.avail[0], True))

    def test_no_screens(self):
        self.assertEqual(resolve_monitor("x", [], None), ("x", False))


class TestMonitorNumber(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(monitor_number("\\\\.\\DISPLAY2", 0), 2)

    def test_fallback(self):
        self.assertEqual(monitor_number("HDMI", 2), 3)


class TestDisplayNumbers(unittest.TestCase):
    def test_primary_first_then_device_order(self):
        ids = [r"\\.\DISPLAY5", r"\\.\DISPLAY1", r"\\.\DISPLAY3"]
        nums = display_numbers(ids, ids[1])
        self.assertEqual(nums, {ids[1]: 1, ids[2]: 2, ids[0]: 3})

    def test_primary_not_first_device(self):
        ids = [r"\\.\DISPLAY1", r"\\.\DISPLAY2"]
        self.assertEqual(display_numbers(ids, ids[1]), {ids[1]: 1, ids[0]: 2})

    def test_missing_primary(self):
        self.assertEqual(display_numbers(["A", "B"], None), {"A": 1, "B": 2})


class TestLayoutTiles(unittest.TestCase):
    def test_side_by_side_scaled_and_centered(self):
        rects = [(-1920, 0, 1920, 1080), (0, 0, 1920, 1080)]
        tiles = layout_tiles(rects, 400, 200, margin=0, gap=0)
        # 3840x1080 縮放到 400 寬 -> scale = 400/3840
        s = 400 / 3840
        self.assertAlmostEqual(tiles[0][0], 0)
        self.assertAlmostEqual(tiles[1][0], 1920 * s)
        self.assertAlmostEqual(tiles[0][2], 1920 * s)
        # 垂直置中
        self.assertAlmostEqual(tiles[0][1], (200 - 1080 * s) / 2)

    def test_empty(self):
        self.assertEqual(layout_tiles([], 100, 100), [])


if __name__ == "__main__":
    unittest.main()
