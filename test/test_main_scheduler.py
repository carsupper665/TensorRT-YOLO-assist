import importlib
import sys
import types
import unittest


class FakeSignal:
    def __init__(self):
        self.emissions = []

    def emit(self, *args, **kwargs):
        self.emissions.append((args, kwargs))


class FakeLogger:
    def debug(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass


class FakeEngine:
    def forward(self, img):
        return [], [], []


class FakeStopEvent:
    def __init__(self):
        self.wait_calls = []

    def clear(self):
        pass

    def set(self):
        pass

    def wait(self, timeout):
        self.wait_calls.append(timeout)
        return False


class MainSchedulerTest(unittest.TestCase):
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
        sys.modules["dxcam"] = types.SimpleNamespace(DXCamera=type("DXCamera", (), {}), create=lambda **kwargs: object())
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

    def test_control_loop_pacing_waits_for_next_deadline(self):
        main = self.load_main_module()
        instance = object.__new__(main.Main)
        instance.args = {"control_fps": 100}
        instance.LOGGER = FakeLogger()
        instance._scheduler_stop_event = FakeStopEvent()
        instance._init_runtime_scheduler(100.0)

        instance._pace_control_loop(100.0)

        self.assertEqual(len(instance._scheduler_stop_event.wait_calls), 1)
        self.assertAlmostEqual(instance._scheduler_stop_event.wait_calls[0], 0.01)
        self.assertAlmostEqual(instance._next_control_deadline, 100.02)

    def test_default_config_does_not_pace_control_loop(self):
        main = self.load_main_module()
        instance = object.__new__(main.Main)
        instance.args = {}
        instance.LOGGER = FakeLogger()
        instance._scheduler_stop_event = FakeStopEvent()
        instance._init_runtime_scheduler(100.0)

        instance._pace_control_loop(100.0)

        self.assertEqual(instance._scheduler_stop_event.wait_calls, [])
        status = instance.get_scheduler_status(100.01)
        self.assertEqual(status["control_target_fps"], 0.0)

    def test_scheduler_status_reports_control_cadence_and_bounded_queue(self):
        main = self.load_main_module()
        instance = object.__new__(main.Main)
        instance.args = {"control_fps": 240}
        instance.LOGGER = FakeLogger()
        instance._scheduler_stop_event = FakeStopEvent()
        instance._init_runtime_scheduler(10.0)

        instance._record_control_tick(10.00, 0.002)
        instance._record_control_tick(10.01, 0.003)
        instance._record_control_tick(10.02, 0.004)

        status = instance.get_scheduler_status(10.03)

        self.assertIn("control_cadence_hz", status)
        self.assertGreater(status["control_cadence_hz"], 0.0)
        self.assertLessEqual(status["queue_depth_max"], 1)
        self.assertEqual(status["control_target_fps"], 240.0)

    def test_forward_drops_intermediate_ui_payloads_at_preview_cadence(self):
        main = self.load_main_module()
        instance = object.__new__(main.Main)
        instance.args = {"control_fps": 240, "ui_preview_fps": 20}
        instance.LOGGER = FakeLogger()
        instance.no_gui = False
        instance.current_mouse_mode = 1
        instance.silent_aim = False
        instance.grab_screen = lambda: "latest-frame"
        instance.engine = FakeEngine()
        instance.target_list = lambda boxes, confidences, classes: None
        instance.lock_target = lambda target, mode, tick, scale: None
        instance.mms = 1.0
        instance.image_queue = FakeSignal()
        instance._scheduler_stop_event = FakeStopEvent()
        instance._init_runtime_scheduler(100.0)

        clock_values = iter([100.000, 100.010, 100.020, 100.050, 100.060])
        original_perf_counter = main.time.perf_counter
        try:
            main.time.perf_counter = lambda: next(clock_values)
            for tick in range(5):
                instance.forward(tick)
        finally:
            main.time.perf_counter = original_perf_counter

        self.assertEqual(len(instance.image_queue.emissions), 2)
        status = instance.get_scheduler_status(100.100)
        self.assertEqual(status["control_target_fps"], 240.0)
        self.assertEqual(status["ui_preview_target_fps"], 20.0)
        self.assertAlmostEqual(status["ui_emit_cadence_hz"], 20.0)

    def test_default_config_does_not_throttle_ui_preview(self):
        main = self.load_main_module()
        instance = object.__new__(main.Main)
        instance.args = {}
        instance.LOGGER = FakeLogger()
        instance.no_gui = False
        instance.current_mouse_mode = 1
        instance.silent_aim = False
        instance.grab_screen = lambda: "latest-frame"
        instance.engine = FakeEngine()
        instance.target_list = lambda boxes, confidences, classes: None
        instance.lock_target = lambda target, mode, tick, scale: None
        instance.mms = 1.0
        instance.image_queue = FakeSignal()
        instance._scheduler_stop_event = FakeStopEvent()
        instance._init_runtime_scheduler(100.0)

        clock_values = iter([100.000, 100.010, 100.020, 100.030, 100.040])
        original_perf_counter = main.time.perf_counter
        try:
            main.time.perf_counter = lambda: next(clock_values)
            for tick in range(5):
                instance.forward(tick)
        finally:
            main.time.perf_counter = original_perf_counter

        self.assertEqual(len(instance.image_queue.emissions), 5)
        status = instance.get_scheduler_status(100.050)
        self.assertEqual(status["ui_preview_target_fps"], 0.0)

    def test_no_gui_reports_disabled_ui_preview_without_emitting(self):
        main = self.load_main_module()
        instance = object.__new__(main.Main)
        instance.args = {"control_fps": 240, "ui_preview_fps": 20}
        instance.LOGGER = FakeLogger()
        instance.no_gui = True
        instance.current_mouse_mode = 0
        instance.silent_aim = False
        instance.grab_screen = lambda: "latest-frame"
        instance.image_queue = FakeSignal()
        instance._scheduler_stop_event = FakeStopEvent()
        instance._init_runtime_scheduler(200.0)

        instance.forward(0)

        self.assertEqual(instance.image_queue.emissions, [])
        status = instance.get_scheduler_status(201.0)
        self.assertIn("ui_preview_enabled", status)
        self.assertFalse(status["ui_preview_enabled"])
        self.assertEqual(status["ui_emit_cadence_hz"], 0.0)


if __name__ == "__main__":
    unittest.main()
