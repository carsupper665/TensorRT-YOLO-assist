import importlib
import sys
import types
import unittest
from unittest import mock


class FakeSignal:
    def emit(self, *args, **kwargs):
        pass


class FakeLogger:
    def warning(self, *args, **kwargs):
        pass


class FakeCamera:
    def __init__(self, capturing=True):
        self.start_calls = []
        self.capturing = capturing

    def start(self, **kwargs):
        self.start_calls.append(kwargs)
        return self

    def is_capturing(self):
        return self.capturing


class FakeCameraWithoutCaptureStatus:
    def __init__(self):
        self.start_calls = []

    def start(self, **kwargs):
        self.start_calls.append(kwargs)
        return self


class FakeCameraWithCaptureProperty:
    def __init__(self, capturing=True):
        self.start_calls = []
        self.is_capturing = capturing

    def start(self, **kwargs):
        self.start_calls.append(kwargs)
        return self


class MainEnsureCameraTest(unittest.TestCase):
    def setUp(self):
        self._saved_modules = {
            name: sys.modules.get(name)
            for name in [
                "main",
                "dxcam",
                "dxcam.dxcam",
                "dxcam.util",
                "dxcam.util.timer",
                "simple_pid",
                "PyQt6",
                "PyQt6.QtCore",
                "pynput",
                "pynput.mouse",
                "pynput.keyboard",
                "serial",
                "serial.serialutil",
                "utils.common",
                "utils.logger",
                "utils.mouse",
                "utils.obs",
                "inference",
            ]
        }
        for name in self._saved_modules:
            sys.modules.pop(name, None)

    def tearDown(self):
        for name in self._saved_modules:
            sys.modules.pop(name, None)
        for name, module in self._saved_modules.items():
            if module is not None:
                sys.modules[name] = module

    def load_main_module(self):
        dxcam_module = types.SimpleNamespace(DXCamera=type("DXCamera", (), {}), create=lambda **kwargs: FakeCamera())
        sys.modules["dxcam"] = dxcam_module
        sys.modules["dxcam.dxcam"] = types.SimpleNamespace(INFINITE=-1, WAIT_FAILED=-1)
        sys.modules["dxcam.util"] = types.SimpleNamespace()
        sys.modules["dxcam.util.timer"] = types.SimpleNamespace(
            create_high_resolution_timer=lambda: object(),
            set_periodic_timer=lambda *args: None,
            wait_for_timer=lambda *args: 0,
            cancel_timer=lambda *args: None,
        )
        sys.modules["simple_pid"] = types.SimpleNamespace(PID=lambda *args, **kwargs: lambda value: value)
        sys.modules["PyQt6"] = types.SimpleNamespace()
        sys.modules["PyQt6.QtCore"] = types.SimpleNamespace(
            QObject=object,
            pyqtSignal=lambda *args, **kwargs: FakeSignal(),
            pyqtSlot=lambda *args, **kwargs: (lambda func: func),
        )
        mouse_module = types.SimpleNamespace(Button=types.SimpleNamespace(), Listener=object)
        keyboard_module = types.SimpleNamespace(Listener=object)
        sys.modules["pynput"] = types.SimpleNamespace(mouse=mouse_module, keyboard=keyboard_module)
        sys.modules["pynput.mouse"] = mouse_module
        sys.modules["pynput.keyboard"] = keyboard_module
        sys.modules["serial"] = types.SimpleNamespace()
        sys.modules["serial.serialutil"] = types.SimpleNamespace(
            PortNotOpenError=RuntimeError,
            SerialException=RuntimeError,
        )
        sys.modules["utils.common"] = types.SimpleNamespace(
            MouseMode=types.SimpleNamespace(Off=0, AimBot=1, Jitter=2, Mix=3),
            MODE_TO_STR={0: "Off", 1: "AimBot", 2: "Jitter", 3: "Mix"},
        )
        sys.modules["utils.logger"] = types.SimpleNamespace(
            C={"cyan": "", "r": "", "green": ""},
            LoggerConfig=object,
            get_logger=lambda cfg: FakeLogger(),
        )
        sys.modules["utils.mouse"] = types.SimpleNamespace(USBMouse=object)
        sys.modules["utils.obs"] = types.SimpleNamespace(OBSCapture=object)
        sys.modules["inference"] = types.SimpleNamespace(BaseEngine=object)
        return importlib.import_module("main")

    def test_ensure_camera_starts_obs_capture_without_dxcam_is_capturing_check(self):
        main = self.load_main_module()
        instance = object.__new__(main.Main)
        instance.cam_type = "obs"
        instance.box = (10, 20, 30, 40)
        instance.cam = FakeCameraWithoutCaptureStatus()
        instance.LOGGER = FakeLogger()
        instance._on_dxcam_reinit = False

        instance._ensure_camera()

        self.assertEqual(
            instance.cam.start_calls,
            [{"region": (10, 20, 30, 40), "target_fps": 240}],
        )

    def test_ensure_camera_raises_when_dxcam_reports_not_capturing(self):
        main = self.load_main_module()
        instance = object.__new__(main.Main)
        instance.cam_type = "dxcam"
        instance.box = (10, 20, 30, 40)
        instance.cam = FakeCamera(capturing=False)
        instance.LOGGER = FakeLogger()
        instance._on_dxcam_reinit = False

        with self.assertRaisesRegex(RuntimeError, "Camera failed to start capturing"):
            instance._ensure_camera()

    def test_ensure_camera_accepts_dxcam_capture_status_property(self):
        main = self.load_main_module()
        instance = object.__new__(main.Main)
        instance.cam_type = "dxcam"
        instance.box = (10, 20, 30, 40)
        instance.cam = FakeCameraWithCaptureProperty(capturing=True)
        instance.LOGGER = FakeLogger()
        instance._on_dxcam_reinit = False

        instance._ensure_camera()

        self.assertEqual(
            instance.cam.start_calls,
            [{"region": (10, 20, 30, 40), "target_fps": 240}],
        )

    def test_ensure_camera_raises_when_dxcam_capture_status_property_is_false(self):
        main = self.load_main_module()
        instance = object.__new__(main.Main)
        instance.cam_type = "dxcam"
        instance.box = (10, 20, 30, 40)
        instance.cam = FakeCameraWithCaptureProperty(capturing=False)
        instance.LOGGER = FakeLogger()
        instance._on_dxcam_reinit = False

        with self.assertRaisesRegex(RuntimeError, "Camera failed to start capturing"):
            instance._ensure_camera()


    def test_cleanup_timeout_waits_on_cleanup_event_instead_of_sleep_polling(self):
        main = self.load_main_module()

        class FakeCleanupEvent:
            def __init__(self):
                self.wait_calls = []

            def wait(self, timeout):
                self.wait_calls.append(timeout)
                instance._is_cleaned = True
                return True

        instance = object.__new__(main.Main)
        instance._is_cleaned = False
        instance._cleanup_done_event = FakeCleanupEvent()
        instance.no_gui = True
        instance.LOGGER = FakeLogger()
        instance.cleanup = lambda pause: (_ for _ in ()).throw(AssertionError("cleanup should not run after clean event"))

        with mock.patch.object(main.time, "sleep") as sleep, mock.patch.object(main.time, "time", side_effect=[0.0, 0.0]):
            instance._interruption_when_time_out()

        self.assertEqual(instance._cleanup_done_event.wait_calls, [0.05])
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
