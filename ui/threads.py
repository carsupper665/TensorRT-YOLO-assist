# #./ui/threads.py

# # 之後把一些功能搬過來
import os, tempfile, yaml
from PyQt6.QtCore import pyqtSignal, QObject, pyqtSlot


def atomic_write_yaml(path: str, data: dict):
    """寫到暫存檔 -> fsync -> os.replace，避免寫到一半的設定檔。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    dir_ = os.path.dirname(os.path.abspath(path)) or "."
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=dir_, delete=False
    ) as tf:
        tmp = tf.name
        yaml.safe_dump(
            data,
            tf,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )
        tf.flush()
        os.fsync(tf.fileno())
    os.replace(tmp, path)


class YamlWriter(QObject):
    finished = pyqtSignal(str)  # 成功路徑
    error = pyqtSignal(type, object)  # (exc_type, exc)

    def __init__(self, path: str, data: dict):
        super().__init__()
        self.path = path
        self.data = data

    @pyqtSlot()
    def run(self):
        try:
            atomic_write_yaml(self.path, self.data)
            self.finished.emit(self.path)
        except Exception as e:
            self.error.emit(type(e), e)


class SysInfoWorker(QObject):
    """背景讀取 GPU / CUDA / TensorRT 版本 (env_check 通過後就不再執行，所以另外查)。"""

    finished = pyqtSignal(dict)

    @pyqtSlot()
    def run(self):
        info = {"gpu": "", "cuda": "", "trt": ""}
        try:
            import torch

            info["cuda"] = torch.version.cuda or ""
            if torch.cuda.is_available():
                info["gpu"] = torch.cuda.get_device_name(0)
        except Exception:
            pass
        try:
            import tensorrt as trt

            info["trt"] = getattr(trt, "__version__", "")
        except Exception:
            pass
        self.finished.emit(info)
