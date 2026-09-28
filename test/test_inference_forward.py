import importlib
import sys
import types
import unittest

import numpy as np


def install_inference_stubs():
    tensorrt = types.ModuleType("tensorrt")
    tensorrt.Logger = lambda *args, **kwargs: types.SimpleNamespace(ERROR=0)
    tensorrt.Logger.ERROR = 0
    tensorrt.init_libnvinfer_plugins = lambda *args, **kwargs: None
    tensorrt.Runtime = lambda *args, **kwargs: None
    tensorrt.TensorIOMode = types.SimpleNamespace(INPUT="INPUT")
    tensorrt.nptype = lambda dtype: np.float32

    cuda_module = types.ModuleType("cuda")
    cuda_module.cuda = types.SimpleNamespace()
    cuda_module.cudart = types.SimpleNamespace()

    common = types.ModuleType("utils.common")
    common.HighQualityTimer = lambda *args, **kwargs: types.SimpleNamespace(update=lambda: {})
    common.cuda_call = lambda value: value

    cv2 = types.ModuleType("cv2")
    cv2.COLOR_BGR2RGB = 1
    def cvt_color(image, code, dst=None):
        converted = image[..., ::-1]
        if dst is not None:
            dst[...] = converted
            return dst
        return converted

    cv2.cvtColor = cvt_color

    sys.modules.setdefault("tensorrt", tensorrt)
    sys.modules.setdefault("cuda", cuda_module)
    sys.modules["utils.common"] = common
    sys.modules.setdefault("cv2", cv2)


class InferenceForwardTest(unittest.TestCase):
    def setUp(self):
        install_inference_stubs()
        sys.modules.pop("inference", None)
        self.inference = importlib.import_module("inference")

    def make_engine(self):
        engine = object.__new__(self.inference.BaseEngine)
        engine.inputs = [{"dtype": np.float32}]
        engine._rgb_input = np.empty((2, 2, 3), dtype=np.uint8)
        engine.h_input = np.empty((3, 2, 2), dtype=np.float32)
        engine._input_scale = np.float32(1.0 / 255.0)
        engine.timer = types.SimpleNamespace(update=lambda: {"total_frames": 1})
        engine.infer_status = {}
        engine.seen_inputs = []

        def fake_infer(img):
            engine.seen_inputs.append(img)
            return (
                np.array([2], dtype=np.int32),
                np.array([[[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12]]], dtype=np.float32),
                np.array([[0.9, 0.8, 0.1]], dtype=np.float32),
                np.array([[1, 0, 2]], dtype=np.float32),
            )

        engine.infer = fake_infer
        return engine

    def test_forward_preserves_target_selection_output_contract(self):
        engine = self.make_engine()
        image = np.arange(12, dtype=np.uint8).reshape(2, 2, 3)

        boxes, scores, classes = engine.forward(image)

        np.testing.assert_array_equal(boxes, np.array([[1, 2, 3, 4], [5, 6, 7, 8]], dtype=np.float32))
        np.testing.assert_array_equal(scores, np.array([0.9, 0.8], dtype=np.float32))
        np.testing.assert_array_equal(classes, np.array([1, 0], dtype=np.float32))
        self.assertEqual(boxes.shape, (2, 4))
        self.assertEqual(scores.shape, (2,))
        self.assertEqual(classes.shape, (2,))
        self.assertEqual(engine.seen_inputs[0].shape, (3, 2, 2))
        self.assertEqual(engine.seen_inputs[0].dtype, np.float32)
        self.assertTrue(engine.seen_inputs[0].flags.c_contiguous)

    def test_forward_avoids_concatenate_and_array_postprocess_churn(self):
        source = PathLikeSource(self.inference.__file__).read_text()
        forward_source = source.split("    def forward", 1)[1].split("    def close", 1)[0]
        self.assertNotIn("np.concatenate", forward_source)
        self.assertNotIn("np.array(final_boxes)", forward_source)
        self.assertNotIn("np.array(final_scores)", forward_source)
        self.assertNotIn("np.array(final_cls_inds)", forward_source)


class PathLikeSource:
    def __init__(self, value):
        from pathlib import Path
        self.path = Path(value)

    def read_text(self):
        return self.path.read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
