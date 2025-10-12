from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout
from PyQt6.QtGui import QMouseEvent

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

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.ToolTip)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # self.setAttribute(Qt.WA_TranslucentBackground, True)


        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)

        self.lt  = QLabel(objectName="title")
        self.msg = QLabel(objectName="msg"); self.msg.setWordWrap(True)
        self.fps_msg = QLabel(objectName="msg"); self.fps_msg.setWordWrap(True)

        # 行內按鈕列：Details 在左，OK 在右
        row = QHBoxLayout(); row.setContentsMargins(0,0,0,0); row.setSpacing(8)
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
        self.hide()
        self.stop_aim_sys.emit()

    def show_osd(self, px=None, py=None):
        self.move(0, 0)
        self.lt.setText('Aim Bot')
        self.msg.setText('Aim Bot: OFF')
        self.msg.setStyleSheet("color: red")
        self.fps_msg.setText('FPS: n/a')
        self.show()

    @pyqtSlot(bool)
    def on_trigger(self, b: bool):
        self.msg.setStyleSheet(f"color: {'green' if b else 'red'}")
        self.msg.setText(f"Aim Bot: {'ON' if b else 'OFF'}")

    @pyqtSlot(str)
    def _on_fps(self, fps: str):
        self.fps_msg.setText(fps)

    def enable_drag(self, enabled=True):
        if enabled:
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint |
                Qt.WindowType.Tool |
                Qt.WindowType.WindowStaysOnTopHint
            )
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self.show()

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_active = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e: QMouseEvent):
        if getattr(self, "_drag_active", False) and (e.buttons() & Qt.MouseButton.LeftButton):
            self.move(e.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_active = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)