# #./ui/threads.py

# # 之後把一些功能搬過來
import os, tempfile, yaml
from PyQt6.QtCore import pyqtSignal, QObject, pyqtSlot


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
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            dir_ = os.path.dirname(os.path.abspath(self.path)) or "."
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=dir_, delete=False
            ) as tf:
                tmp = tf.name
                yaml.safe_dump(
                    self.data,
                    tf,
                    sort_keys=False,
                    allow_unicode=True,
                    default_flow_style=False,
                )
                tf.flush()
                os.fsync(tf.fileno())
            os.replace(tmp, self.path)
            self.finished.emit(self.path)
        except Exception as e:
            self.error.emit(type(e), e)
