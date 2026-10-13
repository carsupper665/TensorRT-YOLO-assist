# ui/config_store.py
# 集中管理 config.yaml：設定頁、OSD 頁、主頁快速開關都透過這裡讀寫，
# 避免設定頁用整份表單覆寫掉其他地方剛存的值。
import yaml
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from .threads import atomic_write_yaml


class ConfigStore(QObject):
    changed = pyqtSignal(tuple, object)  # (path, value)
    saved = pyqtSignal(str)
    error = pyqtSignal(type, object)

    def __init__(self, path: str, data: dict, parent=None, delay_ms: int = 400):
        super().__init__(parent)
        self.path = path
        self._data = data if isinstance(data, dict) else {}
        self._dirty = False

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self.flush)

    @property
    def data(self) -> dict:
        return self._data

    def get(self, path: tuple, default=None):
        cur = self._data
        for k in path:
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur

    def set(self, path: tuple, value, save: bool = True):
        cur = self._data
        for k in path[:-1]:
            if not isinstance(cur.get(k), dict):
                cur[k] = {}
            cur = cur[k]
        if cur.get(path[-1]) == value and path[-1] in cur:
            return
        cur[path[-1]] = value
        self.changed.emit(tuple(path), value)
        if save:
            self._dirty = True
            self._timer.start()

    def replace(self, new_data: dict, keep: tuple = ("osd",)):
        """用 new_data 取代整份設定 (設定頁存檔)，keep 內的區塊保留目前的值。"""
        merged = dict(new_data)
        for k in keep:
            if k in self._data:
                merged[k] = self._data[k]
        # 原地更新，讓持有同一個 dict 的地方 (MainUI.args) 不會拿到舊物件
        self._data.clear()
        self._data.update(merged)
        self._dirty = True
        self.flush()

    def flush(self):
        self._timer.stop()
        if not self._dirty:
            return
        try:
            atomic_write_yaml(self.path, self._data)
            self._dirty = False
            self.saved.emit(self.path)
        except Exception as e:
            self.error.emit(type(e), e)

    def reload(self):
        self.flush()
        with open(self.path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        self._data.clear()
        self._data.update(data)
