from utils.mouse_mode import MouseMode
from utils.osd_layout import compute_osd_pos
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot, QTimer
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout
from PyQt6.QtGui import QMouseEvent, QScreen

from .theme import MODE_COLORS

_MODE_TEXT = ["Aim Bot: OFF", "Aim Bot: On", "Jitter: On", "Mix Mode: On"]

_BASE_STYLE = """
QWidget { background-color: rgba(34, 34, 34, 180); border:1px solid #444; border-radius:8px; }
QLabel#title { color:#fff; font-weight:600; font-family: "Source Han Sans TC"; font-size:22px; }
QLabel#msg { color:#ddd; font-family: "Source Han Sans TC"; font-size:18px; }

QPushButton#ok {
    background:rgba(34, 34, 34, 180); color:%(accent)s; border:1px solid %(accent)s;
    border-radius:6px; padding:4px 10px;
}
QPushButton#ok:hover { background:rgba(255,255,255,0.06); }

QPushButton#details:hover { color:#fff; }
"""


class OSD(QWidget):
    stop_aim_sys = pyqtSignal()

    def __init__(self, parent):
        super().__init__(parent)

        self.mouse_mode = MouseMode.Off
        self._running = False  # 主系統執行中 (非預覽)
        self._placement: tuple[QScreen, str, int, int] | None = None

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._end_preview)

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.ToolTip)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # self.setAttribute(Qt.WA_TranslucentBackground, True)

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)

        self.lt = QLabel(objectName="title")
        self.msg = QLabel(objectName="msg")
        self.msg.setWordWrap(True)
        self.fps_msg = QLabel(objectName="msg")
        self.fps_msg.setWordWrap(True)

        # 行內按鈕列：Details 在左，OK 在右
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.stop = QPushButton("close", objectName="ok")
        self.stop.setToolTip("Stop Aim Bot")
        self.stop.clicked.connect(self._stop_aim_bot)
        # row.addWidget(self.details_btn)
        row.addStretch(1)
        # row.addWidget(self.stop)

        self._accent = "#ff4d4d"

        v.addWidget(self.lt)
        v.addWidget(self.msg)
        v.addWidget(self.fps_msg)
        v.addWidget(self.stop)
        self._apply_style()

    def _apply_style(self):
        self.setStyleSheet(_BASE_STYLE % {"accent": self._accent})

    def _stop_aim_bot(self):
        self.hide_osd()
        self.stop_aim_sys.emit()

    def show_osd(self, mode: int = MouseMode.Off):
        self._preview_timer.stop()
        self._running = True
        self.lt.setText("Aim Bot")
        self.fps_msg.setText("FPS: n/a")
        self.set_mode(mode)
        self._apply_placement()
        self.show()
        self._apply_placement()  # show 之後尺寸才確定，再對齊一次

    def hide_osd(self):
        self._running = False
        self._preview_timer.stop()
        self.hide()

    def preview(self, ms: int = 3000):
        """未執行時暫時顯示 OSD 讓使用者確認位置；執行中只重新定位。"""
        if self._running:
            self._apply_placement()
            return
        self.lt.setText("Aim Bot")
        self.fps_msg.setText("FPS: preview")
        self.set_mode(self.mouse_mode)
        self._apply_placement()
        self.show()
        self._apply_placement()
        self._preview_timer.start(ms)

    def _end_preview(self):
        if not self._running:
            self.hide()

    def set_placement(self, screen: QScreen | None, corner: str, ox: int, oy: int):
        self._placement = (screen, corner, ox, oy) if screen is not None else None
        if self.isVisible():
            self._apply_placement()

    def _apply_placement(self):
        if self._placement is None:
            return
        screen, corner, ox, oy = self._placement
        if self.screen() is not screen:
            self.setScreen(screen)
        # 不同 DPI 螢幕間移動時尺寸可能改變，尺寸變了就再算一次
        for _ in range(2):
            self.adjustSize()
            size = self.size()
            g = screen.geometry()
            x, y = compute_osd_pos(
                (g.x(), g.y(), g.width(), g.height()),
                (size.width(), size.height()),
                corner, ox, oy,
            )
            self.move(x, y)
            if self.size() == size:
                break

    @pyqtSlot(int)
    def set_mode(self, mode: int):
        if not 0 <= mode < len(_MODE_TEXT):
            mode = MouseMode.Off
        self.mouse_mode = mode
        self.msg.setStyleSheet(f"color: {MODE_COLORS[mode]}")
        self.msg.setText(_MODE_TEXT[mode])

    @pyqtSlot(str)
    def _on_fps(self, fps: str):
        self.fps_msg.setText(fps)

    def enable_drag(self, enabled=True):
        if enabled:
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.Tool
                | Qt.WindowType.WindowStaysOnTopHint
            )
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self.show()

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_active = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self._drag_offset = (
                e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )

    def mouseMoveEvent(self, e: QMouseEvent):
        if getattr(self, "_drag_active", False) and (
            e.buttons() & Qt.MouseButton.LeftButton
        ):
            self.move(e.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_active = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
