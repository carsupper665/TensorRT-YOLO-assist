import tensorrt as trt
from cuda import cudart
import numpy as np
import cv2

from utils import common

class BaseEngine(object):
    def __init__(self, engine_path):
        self.mean = None
        self.std = None
        self.n_classes = 3
        self.class_names = ['enm', 'down', 'friend']

        logger = trt.Logger(trt.Logger.ERROR)
        trt.init_libnvinfer_plugins(logger, "")
        runtime = trt.Runtime(logger)

        with open(engine_path, "rb") as f:
            self.engine = runtime.deserialize_cuda_engine(f.read())

        # 讀模型輸入尺寸 (CHW 或 NCHW 的 HW)
        in_name0 = self.engine.get_tensor_name(0)
        in_shape0 = list(self.engine.get_tensor_shape(in_name0))
        self.imgsz = in_shape0[-2:]  # H, W

        self.context = self.engine.create_execution_context()

        # ---- 一次性配置 I/O ----
        self.inputs, self.outputs, self.allocations = [], [], []
        for i in range(self.engine.num_io_tensors):
            name = self.engine.get_tensor_name(i)
            dtype = np.dtype(trt.nptype(self.engine.get_tensor_dtype(name)))
            shape = list(self.engine.get_tensor_shape(name))

            # 動態輸入則設定實際形狀（例如 1x3x640x640）
            if self.engine.get_tensor_mode(name) == trt.TensorIOMode.INPUT:
                if any(d < 0 for d in shape):  # 動態
                    if len(shape) == 4:   # NCHW
                        shape = [1, shape[1] if shape[1] > 0 else 3, self.imgsz[0], self.imgsz[1]]
                        self.context.set_input_shape(name, tuple(shape))
                    elif len(shape) == 3: # CHW
                        shape = [shape[0] if shape[0] > 0 else 3, self.imgsz[0], self.imgsz[1]]
                        self.context.set_input_shape(name, tuple(shape))

            nbytes = dtype.itemsize
            for s in shape:
                nbytes *= s
            # GPU 配置
            d_ptr = common.cuda_call(cudart.cudaMalloc(nbytes))
            self.allocations.append(d_ptr)

            b = {"index": i, "name": name, "dtype": dtype, "shape": shape,
                 "allocation": d_ptr, "size": nbytes}
            if self.engine.get_tensor_mode(name) == trt.TensorIOMode.INPUT:
                self.inputs.append(b)
            else:
                self.outputs.append(b)

        # 預先建立主機輸出緩衝，避免每幀分配
        self.h_outputs = [np.empty(o["shape"], dtype=o["dtype"]) for o in self.outputs]

        # CUDA stream
        self.stream = cudart.cudaStreamCreate()[1]

        # v3：把每個 tensor 綁定到位址（僅需做一次）
        for b in (self.inputs + self.outputs):
            self.context.set_tensor_address(b["name"], int(b["allocation"]))

    def output_spec(self):
        return [(o["shape"], o["dtype"]) for o in self.outputs]

    def infer(self, img):
        # 轉型為引擎期望 dtype，確保連續
        inp = np.ascontiguousarray(img, dtype=self.inputs[0]["dtype"])
        # H2D
        cudart.cudaMemcpyAsync(
            self.inputs[0]["allocation"],                        # dst: device ptr
            inp.ctypes.data,                                     # src: host ptr
            inp.nbytes,
            cudart.cudaMemcpyKind.cudaMemcpyHostToDevice,
            self.stream
        )
        # 執行
        self.context.execute_async_v3(self.stream)

        # D2H 所有輸出
        for i, o in enumerate(self.outputs):
            cudart.cudaMemcpyAsync(
                self.h_outputs[i].ctypes.data,                   # dst: host ptr
                o["allocation"],                                 # src: device ptr
                o["size"],
                cudart.cudaMemcpyKind.cudaMemcpyDeviceToHost,
                self.stream
            )

        cudart.cudaStreamSynchronize(self.stream)
        return self.h_outputs

    def forward(self, image, swap=(2, 0, 1)):
        # 若你的 engine 已內含前處理與 NMS，這段可對齊 engine 期待的輸入
        img = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        img = img.transpose(swap)
        img = np.ascontiguousarray(img, dtype=np.float32) / 255.0

        num, final_boxes, final_scores, final_cls_inds = self.infer(img)
        ratio, dwdh = 1.0, (0.0, 0.0)

        dwdh = np.asarray(dwdh * 2, dtype=np.float32)
        final_boxes -= dwdh
        final_boxes = np.reshape(final_boxes / ratio, (-1, 4))
        final_scores = np.reshape(final_scores, (-1, 1))
        final_cls_inds = np.reshape(final_cls_inds, (-1, 1))
        dets = np.concatenate(
            [
                np.array(final_boxes)[: int(num[0])],
                np.array(final_scores)[: int(num[0])],
                np.array(final_cls_inds)[: int(num[0])],
            ],
            axis=-1,
        )

        if dets is not None:
            final_boxes, final_scores, final_cls_inds = dets[:, :4], dets[:, 4], dets[:, 5]
        return final_boxes, final_scores, final_cls_inds
    
    def close(self):
        try:
            cudart.cudaStreamSynchronize(self.stream)
        except Exception:
            pass
        # 先毀掉 stream，再釋放 device 記憶體
        try:
            if getattr(self, "stream", None):
                cudart.cudaStreamDestroy(self.stream)
                self.stream = None
        except Exception:
            pass
        for ptr in getattr(self, "allocations", []):
            try: cudart.cudaFree(ptr)
            except Exception: pass
        self.allocations = []
        # 斷開參照，讓 Python GC 回收 TensorRT 物件
        self.context = None
        self.engine = None

