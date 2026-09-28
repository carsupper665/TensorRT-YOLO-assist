import importlib
import sys
import types
import unittest
from unittest import mock

import numpy as np


class FakeTimer:
    def __init__(self, avg_size=120):
        self.avg_size = avg_size


class FakeVideoCapture:
    def __init__(self, camera_id, opened=True, reads=None, grabbed_frames=None):
        self.camera_id = camera_id
        self.opened = opened
        self.reads = list(reads or [])
        self.grabbed_frames = list(grabbed_frames) if grabbed_frames is not None else None
        self.last_grabbed_frame = None
        self.set_calls = []
        self.read_calls = 0
        self.grab_calls = 0
        self.retrieve_calls = 0

    def isOpened(self):
        return self.opened

    def set(self, prop, value):
        self.set_calls.append((prop, value))
        return True

    def read(self):
        self.read_calls += 1
        if self.reads:
            return self.reads.pop(0)
        return False, None

    def grab(self):
        if self.grabbed_frames is None:
            raise AttributeError("grab unavailable")
        self.grab_calls += 1
        if self.grabbed_frames:
            self.last_grabbed_frame = self.grabbed_frames.pop(0)
            return True
        return False

    def retrieve(self):
        self.retrieve_calls += 1
        if self.last_grabbed_frame is None:
            return False, None
        return True, self.last_grabbed_frame


class OBSCaptureTest(unittest.TestCase):
    def setUp(self):
        self._original_cv2 = sys.modules.get("cv2")
        self._original_common = sys.modules.get("utils.common")
        self._original_obs = sys.modules.pop("utils.obs", None)
        self.capture_instances = []

    def tearDown(self):
        sys.modules.pop("utils.obs", None)
        if self._original_obs is not None:
            sys.modules["utils.obs"] = self._original_obs

        sys.modules.pop("cv2", None)
        if self._original_cv2 is not None:
            sys.modules["cv2"] = self._original_cv2

        sys.modules.pop("utils.common", None)
        if self._original_common is not None:
            sys.modules["utils.common"] = self._original_common

    def load_obs_module(self, opened=True, reads=None, grabbed_frames=None):
        def video_capture(camera_id):
            capture = FakeVideoCapture(camera_id, opened=opened, reads=reads, grabbed_frames=grabbed_frames)
            self.capture_instances.append(capture)
            return capture

        sys.modules["cv2"] = types.SimpleNamespace(
            VideoCapture=video_capture,
            CAP_PROP_FRAME_WIDTH=3,
            CAP_PROP_FRAME_HEIGHT=4,
            CAP_PROP_FPS=5,
        )
        sys.modules["utils.common"] = types.SimpleNamespace(HighQualityTimer=FakeTimer)
        return importlib.import_module("utils.obs")

    def test_init_opens_camera_and_sets_capture_properties(self):
        obs = self.load_obs_module()

        capture = obs.OBSCapture(w=1920, h=1080, id=2, frame_rate=120)

        fake_cam = self.capture_instances[0]
        self.assertIs(capture.cam, fake_cam)
        self.assertEqual(fake_cam.camera_id, 2)
        self.assertEqual(fake_cam.set_calls, [(3, 1920), (4, 1080), (5, 120)])
        self.assertEqual(capture.width, 1920)
        self.assertEqual(capture.height, 1080)
        self.assertEqual(capture.frame_rate, 120)

    def test_init_raises_when_camera_cannot_be_opened(self):
        obs = self.load_obs_module(opened=False)

        with self.assertRaisesRegex(RuntimeError, "Failed to open camera"):
            obs.OBSCapture(w=1920, h=1080, id=9)

    def test_get_latest_frame_returns_frame_from_successful_read(self):
        frame = np.zeros((2, 3, 4), dtype=np.uint8)
        obs = self.load_obs_module(reads=[(True, frame)])

        capture = obs.OBSCapture(w=1920, h=1080)

        self.assertIs(capture.get_latest_frame(), frame)
        self.assertEqual(self.capture_instances[0].read_calls, 1)

    def test_get_latest_frame_drains_buffered_obs_frames_and_returns_newest(self):
        old_frame = np.zeros((2, 3, 4), dtype=np.uint8)
        latest_frame = np.ones((2, 3, 4), dtype=np.uint8)
        obs = self.load_obs_module(grabbed_frames=[old_frame, latest_frame])

        capture = obs.OBSCapture(w=1920, h=1080)

        self.assertIs(capture.get_latest_frame(), latest_frame)
        self.assertEqual(self.capture_instances[0].retrieve_calls, 1)
        self.assertEqual(self.capture_instances[0].read_calls, 0)

    def test_get_latest_frame_bounds_continuously_successful_grab_drain(self):
        frame = np.full((2, 3, 4), 7, dtype=np.uint8)
        obs = self.load_obs_module()
        capture = obs.OBSCapture(w=1920, h=1080)
        capture.max_drain_frames = 5
        fake_cam = self.capture_instances[0]
        fake_cam.grabbed_frames = [frame] * 100

        self.assertIs(capture.get_latest_frame(), frame)
        self.assertEqual(fake_cam.grab_calls, 5)
        self.assertEqual(fake_cam.retrieve_calls, 1)
        self.assertEqual(fake_cam.read_calls, 0)

    def test_start_accepts_dxcam_style_region_and_target_fps(self):
        frame = np.arange(4 * 5 * 3, dtype=np.uint8).reshape((4, 5, 3))
        obs = self.load_obs_module(reads=[(True, frame)])

        capture = obs.OBSCapture(w=1920, h=1080, frame_rate=60)
        result = capture.start(region=(1, 1, 4, 3), target_fps=240)

        self.assertIs(result, capture)
        self.assertEqual(capture.frame_rate, 240)
        self.assertEqual(self.capture_instances[0].set_calls[-1], (5, 240))
        np.testing.assert_array_equal(capture.get_latest_frame(), frame[1:3, 1:4])

    def test_get_latest_frame_retries_failed_reads_until_frame_is_available(self):
        frame = np.ones((2, 3, 4), dtype=np.uint8)
        obs = self.load_obs_module(reads=[(False, None), (False, None), (True, frame)])

        capture = obs.OBSCapture(w=1920, h=1080)

        result = capture.get_latest_frame()

        self.assertIs(result, frame)
        self.assertEqual(self.capture_instances[0].read_calls, 3)

    def test_get_latest_frame_waits_between_failed_reads(self):
        frame = np.ones((2, 3, 4), dtype=np.uint8)
        obs = self.load_obs_module(reads=[(False, None), (False, None), (True, frame)])

        capture = obs.OBSCapture(w=1920, h=1080)

        with mock.patch.object(obs.time, "sleep") as sleep:
            self.assertIs(capture.get_latest_frame(), frame)

        self.assertEqual(sleep.call_count, 2)
        self.assertTrue(all(call.args[0] > 0 for call in sleep.call_args_list))

    def test_get_latest_frame_raises_after_retry_limit_is_exhausted(self):
        obs = self.load_obs_module(reads=[(False, None)] * 20)

        capture = obs.OBSCapture(w=1920, h=1080)

        with self.assertRaisesRegex(RuntimeError, "Failed to get latest frame"):
            capture.get_latest_frame()
        self.assertEqual(self.capture_instances[0].read_calls, 20)


if __name__ == "__main__":
    unittest.main()
