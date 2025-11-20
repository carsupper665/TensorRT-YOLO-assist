# ui/setting_page.py

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QSpinBox,
    QDoubleSpinBox,
    QCheckBox,
    QScrollArea,
    QFrame,
    QFileDialog,
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, pyqtSlot
from .threads import YamlWriter as _YamlWriter

_TEXT_STYLE = """
background-color: none;
font-family: "Source Han Sans TC", sans-serif;
font-weight: 80;
font-size: 14px;
color: #FFFFFF;
"""


class SettingPage(QWidget):
    on_exception = pyqtSignal(type, object)

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("SettingPage")
        self._widgets = {}  # path(tuple) -> widget
        self.parent = parent

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)

        title = QLabel("Setting Page")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(title, alignment=Qt.AlignmentFlag.AlignHCenter)

        # 滾動區
        self.scroll = QScrollArea(self)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidgetResizable(True)  # 讓內容撐滿寬度並自動出捲軸
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        v.addWidget(self.scroll)

        # 滾動區的實際內容容器
        self.body = QWidget()
        self.scroll.setWidget(self.body)
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(12, 12, 12, 12)
        body_layout.setSpacing(8)

        # 你的表單/設定元件都加到這裡
        self._form = QFormLayout()
        body_layout.addLayout(self._form)

        self.save_btn = QPushButton("Save")
        self.save_btn.setMaximumSize(140, 60)
        self.save_btn.setMinimumSize(70, 30)
        self.save_btn.setStyleSheet(
            "QPushButton { background:#1976D2; color:white; border:none; border-radius:6px; padding:6px 14px; }"
            "QPushButton:hover { background:#1E88E5; }"
            "QPushButton:disabled { background:#555; color:gray; }"
        )
        self.save_btn.clicked.connect(self._save)

        v.addWidget(self.save_btn, alignment=Qt.AlignmentFlag.AlignRight)

    # 對外：建立表單
    def build(self, args: dict, target_yaml: str):
        self._target_yaml = target_yaml
        self._clear_form()
        self._make_settings(self._form, args, ())

    # 對外：讀回目前值
    def values(self) -> dict:
        try:
            out = {}
            for path, w in self._widgets.items():
                if isinstance(w, list):
                    out["model"][path] = w
                    continue
                self._assign(out, path, self._get_value(w))

        except Exception as e:
            self.on_exception.emit(type(e), e)
        return out

    def _save(self):
        try:
            path = self._target_yaml
            if not path:
                path, _ = QFileDialog.getSaveFileName(
                    self, "Save config", "config.yaml", "YAML (*.yaml *.yml)"
                )
                if not path:
                    return
            data = self.values()  # 先在 UI 執行緒取快照
            self.save_btn.setEnabled(False)

            # 啟 worker 執行緒
            self._th = QThread(self)
            self._worker = _YamlWriter(path, data)
            self._worker.moveToThread(self._th)

            self._th.started.connect(self._worker.run)
            self._worker.finished.connect(self._on_saved)
            self._worker.error.connect(self.on_exception)

            # 清理
            self._worker.finished.connect(self._th.quit)
            self._worker.error.connect(self._th.quit)
            self._th.finished.connect(self._worker.deleteLater)
            self._th.finished.connect(self._th.deleteLater)

            self._th.start()
        except Exception as e:
            self.on_exception.emit(type(e), e)

    @pyqtSlot(str)
    def _on_saved(self, path: str):
        self.save_btn.setEnabled(True)
        self.parent.toast.show_notice(
            "info", "Config Saved.", "Config Saved. Restart Aim Sys to apply settings."
        )

    # -------- 內部 --------
    def _clear_form(self):
        self._widgets.clear()
        while self._form.count():
            item = self._form.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            if item.layout():
                while item.layout().count():
                    it2 = item.layout().takeAt(0)
                    if it2.widget():
                        it2.widget().deleteLater()

    def _make_settings(self, layout: QFormLayout, args: dict, path: tuple):
        for key, val in args.items():
            p = path + (key,)
            # dict -> 群組遞迴
            if isinstance(val, dict) and not {"value", "options"} <= set(val.keys()):
                box = QGroupBox(key)
                box.setStyleSheet("QGroupBox{color:#ddd; font-weight:600;}")
                inner = QFormLayout(box)
                inner.setSpacing(8)
                layout.addRow(box)
                self._make_settings(inner, val, p)
                continue

            label = QLabel(key)
            label.setStyleSheet(_TEXT_STYLE)

            # list -> 下拉；也支援 {"value":cur, "options":[...]}
            if isinstance(val, list) or (isinstance(val, dict) and "options" in val):
                # options = val if isinstance(val, list) else val.get("options", [])
                # cur = options[0] if isinstance(val, list) else val.get("value", options[0] if options else "")
                # w = QComboBox(); [w.addItem(str(x)) for x in options]
                # if options:
                #     try: w.setCurrentIndex(options.index(cur))
                #     except ValueError: pass
                # # w.currentIndexChanged.connect(lambda *_: self.valueChanged.emit(self.values()))
                self._widgets[key] = val
                # w.hide()
                # layout.addRow(label, w)
                continue

            # 數值
            if isinstance(val, bool):
                w = QCheckBox()
                w.setChecked(bool(val))
                # w.stateChanged.connect(lambda *_: self.valueChanged.emit(self.values()))
                self._widgets[p] = w
                layout.addRow(label, w)

            elif isinstance(val, int):
                w = QSpinBox()
                w.setRange(min(-(10**9), val - 10**6), max(10**9, val + 10**6))
                w.setValue(
                    val
                )  # ; w.valueChanged.connect(lambda *_: self.valueChanged.emit(self.values()))
                self._widgets[p] = w
                layout.addRow(label, w)
            elif isinstance(val, float):
                w = QDoubleSpinBox()
                w.setDecimals(6)
                w.setSingleStep(0.1)
                lo = -1e12 if val >= 0 else val * 10
                hi = 1e12 if val <= 0 else val * 10
                w.setRange(lo, hi)
                w.setValue(val)
                # w.valueChanged.connect(lambda *_: self.valueChanged.emit(self.values()))
                self._widgets[p] = w
                layout.addRow(label, w)
            else:  # str/其他 -> 輸入框
                w = QLineEdit(str(val))
                # w.textChanged.connect(lambda *_: self.valueChanged.emit(self.values()))
                self._widgets[p] = w
                layout.addRow(label, w)
            w.setStyleSheet("color: #FFFFFF;")

    def _get_value(self, w):
        # combo 需要還原成 {"value": cur, "options": [...]}
        if isinstance(w, tuple) and w[1] == "combo":
            combo, _, options = w
            cur = combo.currentText()
            # 嘗試轉回數字
            try:
                cur_cast = float(cur)
                cur = int(cur_cast) if cur_cast.is_integer() else cur_cast
            except Exception:
                pass
            return {"value": cur, "options": options}
        if isinstance(w, QCheckBox):
            return w.isChecked()
        if isinstance(w, QSpinBox):
            return int(w.value())
        if isinstance(w, QDoubleSpinBox):
            return float(w.value())
        if isinstance(w, QLineEdit):
            return w.text()
        return None

    def _assign(self, root: dict, path: tuple, value):
        d = root
        for k in path[:-1]:
            d = d.setdefault(k, {})
        d[path[-1]] = value
