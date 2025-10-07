# ui/home_page.py
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout
)
from PyQt6.QtCore import Qt, pyqtSignal

class SettingPage(QWidget):
    on_exception = pyqtSignal(type, object)

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("SettingPage")
        self._running = False

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)

        title = QLabel("Setting Page", self)
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        title.setStyleSheet(
            """
            background-color: none;
            font-family: "Inter", "Segoe UI", sans-serif;
            font-weight: 500;
            font-size: 20px;
            color: #FFFFFF;
            """
        )
        v.addWidget(title, alignment=Qt.AlignmentFlag.AlignHCenter)
        v.addStretch(1)