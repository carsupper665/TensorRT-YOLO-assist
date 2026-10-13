# ui/home_page.py
import os

from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer

from . import theme as T
from .widgets import Card, InfoItem, SegmentedControl, ToggleSwitch, field_label, hint_label
from .osd_page import short_screen_name

_CAMERAS = ["dxcam", "mss", "obs"]


class HomePage(QWidget):
    on_exception = pyqtSignal(type, object)
    startRequested = pyqtSignal()
    stopRequested = pyqtSignal()
    restartRequested = pyqtSignal()
    modeRequested = pyqtSignal(int)

    def __init__(self, parent, store, version: str = ""):
        super().__init__(parent)
        self.setObjectName("HomePage")
        self.store = store
        self._running = False
        self._mode = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # --- 標題列 ---
        head = QHBoxLayout()
        head.setSpacing(10)
        title = QLabel("手殘黨")
        title.setStyleSheet(
            f"color:{T.TEXT_WHITE}; font-family:{T.FONT}; font-size:22px; font-weight:700;"
        )
        head.addWidget(title, alignment=Qt.AlignmentFlag.AlignBottom)
        ver = hint_label(f"v{version}" if version else "")
        head.addWidget(ver, alignment=Qt.AlignmentFlag.AlignBottom)
        head.addStretch(1)
        self.status = QLabel()
        head.addWidget(self.status)
        root.addLayout(head)

        # --- 第一排：控制 + 快速開關 ---
        row = QHBoxLayout()
        row.setSpacing(14)
        row.addWidget(self._build_control_card(), 1)
        row.addWidget(self._build_toggle_card(), 1)
        root.addLayout(row, 1)

        # --- 第二排：系統資訊 ---
        root.addWidget(self._build_info_card())

        self._sync_ui()
        self.set_stats(None)
        self._sync_from_cfg()
        self.store.changed.connect(lambda *_: self._sync_from_cfg())

    # ------------------------------------------------------------------
    # 建立區塊
    # ------------------------------------------------------------------

    def _build_control_card(self) -> Card:
        card = Card("控制")

        btns = QHBoxLayout()
        btns.setSpacing(10)
        self.btn = QPushButton("啟動")
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.setFixedHeight(44)
        self.btn.clicked.connect(self._toggle)
        btns.addWidget(self.btn, 1)

        self.restart_btn = QPushButton("重啟")
        self.restart_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.restart_btn.setFixedHeight(44)
        self.restart_btn.setToolTip("重新載入設定並重建系統")
        self.restart_btn.setStyleSheet(T.button_style(T.BLUE, T.BLUE_HOVER, pad="6px 18px", size=14))
        self.restart_btn.clicked.connect(self._on_restart_requested)
        btns.addWidget(self.restart_btn)
        card.body.addLayout(btns)

        stats = QGridLayout()
        stats.setHorizontalSpacing(16)
        stats.setVerticalSpacing(8)
        self.fps_item = InfoItem("推論 FPS", value_size=18)
        self.frame_item = InfoItem("幀時間", value_size=18)
        self.loop_item = InfoItem("控制迴圈", value_size=18)
        self.mode_item = InfoItem("目前模式", value_size=18)
        stats.addWidget(self.fps_item, 0, 0)
        stats.addWidget(self.frame_item, 0, 1)
        stats.addWidget(self.loop_item, 1, 0)
        stats.addWidget(self.mode_item, 1, 1)
        card.body.addLayout(stats)

        keys = QHBoxLayout()
        keys.setSpacing(16)
        self.switch_key = InfoItem("切換模式鍵")
        self.aim_key = InfoItem("瞄準鍵")
        self.silent_key = InfoItem("靜默瞄準鍵")
        for w in (self.switch_key, self.aim_key, self.silent_key):
            keys.addWidget(w, 1)
        card.body.addSpacing(4)
        card.body.addLayout(keys)
        card.body.addStretch(1)
        return card

    def _build_toggle_card(self) -> Card:
        card = Card("快速開關")
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)

        self.mode_seg = SegmentedControl(T.MODE_LABELS)
        self.mode_seg.changed.connect(self._on_mode_clicked)
        grid.addWidget(field_label("滑鼠模式"), 0, 0)
        grid.addWidget(self.mode_seg, 0, 1)

        self.cam_seg = SegmentedControl(_CAMERAS)
        self.cam_seg.changed.connect(lambda i: self.store.set(("camera",), _CAMERAS[i]))
        grid.addWidget(field_label("擷取來源"), 1, 0)
        cam_box = QVBoxLayout()
        cam_box.setSpacing(2)
        cam_box.addWidget(self.cam_seg)
        cam_box.addWidget(hint_label("重啟後生效"))
        grid.addLayout(cam_box, 1, 1)

        self.osd_sw = ToggleSwitch()
        self.osd_sw.toggled.connect(lambda b: self.store.set(("osd", "enabled"), bool(b)))
        grid.addWidget(field_label("顯示 OSD"), 2, 0)
        grid.addWidget(self.osd_sw, 2, 1, alignment=Qt.AlignmentFlag.AlignLeft)

        self.update_sw = ToggleSwitch()
        self.update_sw.toggled.connect(lambda b: self.store.set(("auto_update",), bool(b)))
        grid.addWidget(field_label("自動更新"), 3, 0)
        grid.addWidget(self.update_sw, 3, 1, alignment=Qt.AlignmentFlag.AlignLeft)

        card.body.addLayout(grid)
        card.body.addStretch(1)
        return card

    def _build_info_card(self) -> Card:
        card = Card("系統資訊")
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        self.info = {
            "gpu": InfoItem("GPU"),
            "cuda": InfoItem("CUDA"),
            "trt": InfoItem("TensorRT"),
            "model": InfoItem("模型"),
            "res": InfoItem("解析度"),
            "serial": InfoItem("序列埠"),
            "camera": InfoItem("擷取來源"),
            "osd": InfoItem("OSD 顯示器"),
        }
        for i, w in enumerate(self.info.values()):
            grid.addWidget(w, i // 4, i % 4)
        for c in range(4):
            grid.setColumnStretch(c, 1)
        card.body.addLayout(grid)
        return card

    # ------------------------------------------------------------------
    # 對外 API (MainUI 呼叫)
    # ------------------------------------------------------------------

    def set_running(self, running: bool):
        if self._running == running:
            return
        self._running = running
        self._sync_ui()

    def set_restart_enabled(self, enabled: bool):
        self.restart_btn.setEnabled(enabled)

    def set_start_enabled(self, enabled: bool):
        self.btn.setEnabled(enabled)

    def set_mode(self, mode: int):
        self._mode = mode
        self.mode_seg.set_index(mode)
        if 0 <= mode < len(T.MODE_LABELS):
            self.mode_item.set_value(T.MODE_LABELS[mode], T.MODE_COLORS[mode])

    def set_stats(self, stats: dict | None):
        """stats: {fps, frame_ms, loop_hz}；None 表示未執行。"""
        if not stats:
            for w in (self.fps_item, self.frame_item, self.loop_item):
                w.set_value("—", T.TEXT_DIM)
            if not self._running:
                self.mode_item.set_value("—", T.TEXT_DIM)
            return
        fps, frame_ms, loop_hz = stats.get("fps"), stats.get("frame_ms"), stats.get("loop_hz")
        self.fps_item.set_value(f"{fps:.0f}" if fps else "—", T.TEXT if fps else T.TEXT_DIM)
        self.frame_item.set_value(f"{frame_ms:.1f} ms" if frame_ms else "—", T.TEXT if frame_ms else T.TEXT_DIM)
        self.loop_item.set_value(f"{loop_hz:.0f} Hz" if loop_hz else "—", T.TEXT if loop_hz else T.TEXT_DIM)

    def set_sys_info(self, info: dict):
        for key in ("gpu", "cuda", "trt"):
            if key in info:
                self.info[key].set_value(info[key] or "—")

    # ------------------------------------------------------------------
    # 內部
    # ------------------------------------------------------------------

    def _on_mode_clicked(self, mode: int):
        if not self._running:
            self.mode_seg.set_index(self._mode)
            return
        self.modeRequested.emit(mode)

    def _sync_from_cfg(self):
        s = self.store
        cam = s.get(("camera",), "")
        if cam in _CAMERAS:
            self.cam_seg.set_index(_CAMERAS.index(cam))
        self.osd_sw.set_checked_silent(bool(s.get(("osd", "enabled"), True)))
        self.update_sw.set_checked_silent(bool(s.get(("auto_update",), False)))

        model = s.get(("model", "file_path"), "")
        self.info["model"].set_value(os.path.basename(str(model)) or "—")
        rx, ry = s.get(("resolution_x",)), s.get(("resolution_y",))
        self.info["res"].set_value(f"{rx}×{ry}" if rx and ry else "—")
        self.info["serial"].set_value(str(s.get(("mouse", "serial_port"), "")) or "—")
        self.info["camera"].set_value(str(cam) or "—")
        self.switch_key.set_value(str(s.get(("mouse", "switch_button"), "")) or "—")
        self.aim_key.set_value(str(s.get(("mouse", "aimbot_button"), "")) or "—")
        self.silent_key.set_value(str(s.get(("mouse", "silent_aim"), "")) or "—")
        mon = str(s.get(("osd", "monitor"), ""))
        self.info["osd"].set_value(short_screen_name(mon) or "—")

    def _on_restart_requested(self):
        self.restart_btn.setDisabled(True)
        QTimer.singleShot(100, self.restartRequested.emit)

    def _toggle(self):
        if self._running:
            self.stopRequested.emit()
            self.set_running(False)
        else:
            self.startRequested.emit()
            self.set_running(True)

    def _sync_ui(self):
        self.btn.setText("■  停止" if self._running else "▶  啟動")
        self._apply_btn_style(self._running)
        self._set_status(self._running)
        self.mode_seg.setEnabled(self._running)
        if not self._running:
            self.set_stats(None)

    def _apply_btn_style(self, running: bool):
        if running:
            self.btn.setStyleSheet(T.button_style(T.RED, T.RED_HOVER, size=15))
        else:
            self.btn.setStyleSheet(T.button_style(T.GREEN, T.GREEN_HOVER, size=15))

    def _set_status(self, running: bool):
        color = T.OK if running else T.TEXT_DIM
        text = "執行中" if running else "已停止"
        self.status.setText(f"<span style='color:{color};'>●</span>&nbsp;{text}")
        self.status.setStyleSheet(
            f"color:{T.TEXT}; font-family:{T.FONT}; font-size:13px;"
            f"background:{T.CARD_BG}; border:1px solid {T.CARD_BORDER}; border-radius:12px; padding:3px 12px;"
        )
