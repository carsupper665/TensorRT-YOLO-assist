import tensorrt as trt
from cuda import cudart
import numpy as np
import cv2

from utils import common 

# os.environ["PATH"] += f";v11.8;v11.8\\bin;v11.8\\lib"
# os.environ["CUDA_MODULE_LOADING"] = "LAZY"
# os.environ["PATH"] += os.pathsep + r"./dll"
# os.environ["CUDA_MODULE_LOADING"]="LAZY"
# @staticmethod
class BaseEngine(object):
    def __init__(self, engine_path,):
        self.mean = None
        self.std = None
        self.n_classes = 3
        self.class_names = ['enm', 
                            'down', 
                            'friend']

        logger = trt.Logger(trt.Logger.WARNING)
        logger.min_severity = trt.Logger.Severity.ERROR
        runtime = trt.Runtime(logger)
        trt.init_libnvinfer_plugins(logger,'') # initialize TensorRT plugins
        with open(engine_path, "rb") as f:
            serialized_engine = f.read()
        self.engine = runtime.deserialize_cuda_engine(serialized_engine)
        self.imgsz = self.engine.get_tensor_shape(self.engine.get_tensor_name(0))[2:]  # get the read shape of model, in case user input it wrong
        self.context = self.engine.create_execution_context()

        # Setup I/O bindings
        self.inputs = []
        self.outputs = []
        self.allocations = []

        # self.stream = cuda.Stream()

        for i in range(self.engine.num_io_tensors):
            name = self.engine.get_tensor_name(i)
            dtype = self.engine.get_tensor_dtype(name)
            shape = self.engine.get_tensor_shape(name)
            is_input = False
            if self.engine.get_tensor_mode(name) == trt.TensorIOMode.INPUT:
                is_input = True
            if is_input:
                self.batch_size = shape[0]
            size = np.dtype(trt.nptype(dtype)).itemsize
            for s in shape:
                size *= s
            allocation = common.cuda_call(cudart.cudaMalloc(size))
            binding = {
                'index': i,
                'name': name,
                'dtype': np.dtype(trt.nptype(dtype)),
                'shape': list(shape),
                'allocation': allocation,
                'size': size
            }
            self.allocations.append(allocation)
            if self.engine.get_tensor_mode(name) == trt.TensorIOMode.INPUT:
                self.inputs.append(binding)
            else:
                self.outputs.append(binding)

    def output_spec(self):
        """
        Get the specs for the output tensors of the network. Useful to prepare memory allocations.
        :return: A list with two items per element, the shape and (numpy) datatype of each output tensor.
        """
        specs = []
        for o in self.outputs:
            specs.append((o['shape'], o['dtype']))
        return specs

    def infer(self, img):
        outputs = []
        for shape, dtype in self.output_spec():
            outputs.append(np.zeros(shape, dtype))

        # Process I/O and execute the network.
        common.memcpy_host_to_device(self.inputs[0]['allocation'], np.ascontiguousarray(img))

        # stream_handle = int(self.cuda_stream)  # 获取整数类型的流句柄
        # self.context.execute_async_v3(bindings=self.allocations, stream_handle=stream_handle)
        self.context.execute_v2(self.allocations)

        for o in range(len(outputs)):
            common.memcpy_device_to_host(outputs[o], self.outputs[o]['allocation'])
        return outputs


    def forward(self, image, swap=(2, 0, 1)):
        # img = np.ascontiguousarray(image.transpose(2,0,1)/255.0, dtype=np.float32)
        img = image
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = img.transpose(swap)
        img = np.ascontiguousarray(img, dtype=np.float32) / 255.
        
        # im, ratio, dwdh = letterbox(img, (640, 640))
        num, final_boxes, final_scores, final_cls_inds  = self.infer(img)
        ratio, dwdh = 1.0 ,(0.0, 0.0)

        dwdh = np.asarray(dwdh * 2, dtype=np.float32)
        final_boxes -= dwdh
        final_boxes = np.reshape(final_boxes/ratio, (-1, 4))
        final_scores = np.reshape(final_scores, (-1, 1))
        final_cls_inds = np.reshape(final_cls_inds, (-1, 1))
        dets = np.concatenate([np.array(final_boxes)[:int(num[0])], np.array(final_scores)[:int(num[0])], np.array(final_cls_inds)[:int(num[0])]], axis=-1)

        if dets is not None:
            final_boxes, final_scores, final_cls_inds = dets[:,
                                                             :4], dets[:, 4], dets[:, 5]
        # print(final_boxes, final_scores, final_cls_inds)
        return final_boxes, final_scores, final_cls_inds
        # print(final_boxes)
        # print(num)

def  letterbox(im,
            new_shape = (640, 640),
            color = (114, 114, 114),
            swap=(2, 0, 1)):
    shape = im.shape[:2]  # current shape [height, width]
    if isinstance(new_shape, int):
        new_shape = (new_shape, new_shape)
    # new_shape: [width, height]

    # Scale ratio (new / old)
    r = min(new_shape[0] / shape[1], new_shape[1] / shape[0])
    # Compute padding [width, height]
    new_unpad = int(round(shape[1] * r)), int(round(shape[0] * r))
    dw, dh = new_shape[0] - new_unpad[0], new_shape[1] - new_unpad[
        1]  # wh padding

    dw /= 2  # divide padding into 2 sides
    dh /= 2

    if shape[::-1] != new_unpad:  # resize
        im = cv2.resize(im, new_unpad, interpolation=cv2.INTER_LINEAR)
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    im = cv2.copyMakeBorder(im,
                            top,
                            bottom,
                            left,
                            right,
                            cv2.BORDER_CONSTANT,
                            value=color)  # add border
    im = cv2.cvtColor(im, cv2.COLOR_BGR2RGB)
    im = im.transpose(swap)
    im = np.ascontiguousarray(im, dtype=np.float32) / 255.
    return im, r, (dw, dh)