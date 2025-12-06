# ui/home_page.py
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout
from PyQt6.QtCore import Qt, pyqtSignal, QTimer


class HomePage(QWidget):
    on_exception = pyqtSignal(type, object)
    startRequested = pyqtSignal()
    stopRequested = pyqtSignal()
    restartRequested = pyqtSignal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("HomePage")
        self._running = False

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(20)

        title = QLabel("Home Page", self)
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        title.setStyleSheet(
            """
            background-color: none;
            font-family: "Source Han Sans TC", sans-serif;
            font-weight: 500;
            font-size: 20px;
            color: #FFFFFF;
            """
        )
        v.addWidget(title, alignment=Qt.AlignmentFlag.AlignHCenter)

        # 控制列：Start/Stop + 狀態
        # 控制列：Start/Stop + 狀態（置中，間距 20px）
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(50)
        row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.btn = QPushButton("Start")
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.setFixedHeight(32)
        self.btn.clicked.connect(self._toggle)
        self._apply_btn_style(running=False)

        self.restart_btn = QPushButton("Restart")
        self.restart_btn.setFixedHeight(32)
        self.restart_btn.setStyleSheet(
            "QPushButton { background:#1976D2; color:white; border:none; border-radius:6px; padding:6px 14px; }"
            "QPushButton:hover { background:#1E88E5; }"
            "QPushButton:disabled { background:#555; color:gray; }"
        )
        self.restart_btn.clicked.connect(self._on_restart_requested)

        self.status = QLabel()
        self.status.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )
        self.status.setStyleSheet(
            "font-family:Inter, 'Segoe UI', sans-serif; font-size:14px; color:#ddd;"
        )
        # self.status.setMinimumWidth(120)
        self._set_status(False)

        row.addWidget(self.btn)
        row.addWidget(self.status)
        row.addWidget(self.restart_btn)
        v.addLayout(row)
        v.addStretch(1)

    # 公開 API：外部可直接設狀態
    def set_running(self, running: bool):
        if self._running == running:
            return
        self._running = running
        self._sync_ui()

    def _on_restart_requested(self):
        self.restart_btn.setDisabled(True)
        QTimer.singleShot(100, self.restartRequested.emit)
        # self.restartRequested.emit()

    def set_restart_enabled(self, enabled: bool):
        self.restart_btn.setEnabled(enabled)

    def set_start_enabled(self, enabled: bool):
        self.btn.setEnabled(enabled) 

    # 內部：按鈕切換
    def _toggle(self):
        if self._running:
            self.stopRequested.emit()
            self.set_running(False)
        else:
            self.startRequested.emit()
            self.set_running(True)

    def _sync_ui(self):
        self.btn.setText("Stop" if self._running else "Start")
        self._apply_btn_style(self._running)
        self._set_status(self._running)

    def _apply_btn_style(self, running: bool):
        # 移除不支援的 filter，用不同底色表現 hover
        if running:
            base = "#C62828"  # Stop
            hover = "#D32F2F"
        else:
            base = "#2E7D32"  # Start
            hover = "#388E3C"
        self.btn.setStyleSheet(
            f"""
            QPushButton {{ background:{base}; color:white; border:none; border-radius:6px; padding:6px 14px; }}
            QPushButton:hover {{ background:{hover}; }}
            QPushButton:disabled {{ background:#555; color:#aaa; }}
            """
        )

    def _set_status(self, running: bool):
        dot = "\u25cf"  # ●
        color = "#4CAF50" if running else "#9E9E9E"
        text = "Running" if running else "Stopped"
        # 使用 <br/> 比 \n 更穩定
        self.status.setText(
            f"<span style='color:{color}; font-size:14px;'>{dot}</span><span>{text}</span>"
        )
