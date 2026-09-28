import importlib
import sys
import types
import unittest
from unittest import mock


class HighQualityTimerTest(unittest.TestCase):
    def setUp(self):
        self._saved_modules = {
            name: sys.modules.get(name)
            for name in ["utils.common", "tensorrt", "cuda", "cuda.cuda", "cuda.cudart"]
        }
        for name in self._saved_modules:
            sys.modules.pop(name, None)

    def tearDown(self):
        for name in self._saved_modules:
            sys.modules.pop(name, None)
        for name, module in self._saved_modules.items():
            if module is not None:
                sys.modules[name] = module

    def load_common_module(self):
        class FakeTrt(types.SimpleNamespace):
            def __getattr__(self, name):
                value = type(name, (), {})
                setattr(self, name, value)
                return value
        fake_trt = FakeTrt(NetworkDefinitionCreationFlag=types.SimpleNamespace(EXPLICIT_BATCH=0))
        class FakeCudaModule(types.SimpleNamespace):
            def __getattr__(self, name):
                value = type(name, (), {})
                setattr(self, name, value)
                return value
        fake_cuda = FakeCudaModule(CUresult=types.SimpleNamespace(CUDA_SUCCESS=0))
        fake_cudart = FakeCudaModule(cudaError_t=types.SimpleNamespace(cudaSuccess=0))
        sys.modules["tensorrt"] = fake_trt
        sys.modules["cuda"] = types.SimpleNamespace(cuda=fake_cuda, cudart=fake_cudart)
        sys.modules["cuda.cuda"] = fake_cuda
        sys.modules["cuda.cudart"] = fake_cudart
        return importlib.import_module("utils.common")

    def test_high_quality_timer_maintains_constant_time_rolling_total(self):
        common = self.load_common_module()
        timestamps = iter([1_000_000_000, 1_010_000_000, 1_030_000_000, 1_060_000_000, 1_100_000_000])

        with mock.patch.object(common.time, "perf_counter_ns", side_effect=lambda: next(timestamps)):
            timer = common.HighQualityTimer(avg_size=3)
            timer.update()
            timer.update()
            timer.update()
            status = timer.update()

        self.assertEqual(status["frame"], 4)
        self.assertAlmostEqual(status["avg_ms"], 30.0)
        self.assertAlmostEqual(status["fps"], 1000.0 / 30.0)
        self.assertTrue(hasattr(timer, "_frame_times_total_ms"))
        self.assertAlmostEqual(timer._frame_times_total_ms, 90.0)


if __name__ == "__main__":
    unittest.main()
