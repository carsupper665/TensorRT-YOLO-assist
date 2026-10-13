import os
import tempfile
import unittest

import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QCoreApplication  # noqa: E402

from ui.config_store import ConfigStore  # noqa: E402


class TestConfigStore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "config.yaml")
        self.data = {"camera": "dxcam", "osd": {"monitor": "A", "corner": "top_left"}}

    def tearDown(self):
        self.tmp.cleanup()

    def _read(self):
        with open(self.path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def test_set_then_flush_writes_file(self):
        store = ConfigStore(self.path, self.data)
        changes = []
        store.changed.connect(lambda p, v: changes.append((p, v)))
        store.set(("osd", "corner"), "bottom_right")
        self.assertFalse(os.path.exists(self.path))  # debounce 中，尚未寫檔
        store.flush()
        self.assertEqual(self._read()["osd"]["corner"], "bottom_right")
        self.assertEqual(changes, [(("osd", "corner"), "bottom_right")])

    def test_set_same_value_is_noop(self):
        store = ConfigStore(self.path, self.data)
        changes = []
        store.changed.connect(lambda p, v: changes.append(p))
        store.set(("camera",), "dxcam")
        store.flush()
        self.assertEqual(changes, [])
        self.assertFalse(os.path.exists(self.path))

    def test_set_creates_missing_section(self):
        store = ConfigStore(self.path, {})
        store.set(("osd", "enabled"), False)
        self.assertEqual(store.get(("osd", "enabled")), False)

    def test_replace_keeps_osd_section_and_identity(self):
        store = ConfigStore(self.path, self.data)
        store.set(("osd", "monitor"), "B")
        store.replace({"camera": "mss", "osd": {"monitor": "stale"}})
        saved = self._read()
        self.assertEqual(saved["camera"], "mss")
        self.assertEqual(saved["osd"]["monitor"], "B")
        self.assertIs(store.data, self.data)

    def test_reload(self):
        store = ConfigStore(self.path, self.data)
        store.set(("camera",), "obs")
        store.reload()
        self.assertEqual(store.get(("camera",)), "obs")
        self.assertIs(store.data, self.data)


if __name__ == "__main__":
    unittest.main()
