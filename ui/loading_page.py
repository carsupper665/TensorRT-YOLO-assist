# ui/loading_page.py
from PyQt6.QtWidgets import (
    QLabel,
    QWidget,
    QVBoxLayout,
    QProgressBar,
)
from PyQt6.QtCore import Qt, pyqtSlot, pyqtSignal


class LoadingPage(QWidget):
    on_exception = pyqtSignal(type, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LoadingPage")
        self.setObjectName(self.__class__.__name__)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        v.addStretch()

        self.label = QLabel("Loading...", self)
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.label.setStyleSheet("""
                background-color: none;
                font-family: "Source Han Sans TC";
                font-style: normal;
                font-weight: 500;
                font-size: 20px;
                color: #FFFFFF;
                                 
            """)

        self.bar = QProgressBar(self)
        self.bar.setRange(0, 100)  # 不定長度可改成 (0,0)
        # self.bar.setValue(20)
        self.bar.setTextVisible(False)
        self.bar.setFixedSize(500, 42)

        self.bar.setStyleSheet("""
            QProgressBar {
                background-color: #2A3448;
                border: 2px solid #CFD9FB;
                border-radius: 5px;
            }
            QProgressBar::chunk {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #D6D0FA,
                    stop: 1 #657EAE
                );
                border-radius: 5px;
            }
        """)

        v.addWidget(self.label)
        v.addWidget(self.bar, alignment=Qt.AlignmentFlag.AlignHCenter)

        v.addStretch()

    @pyqtSlot(dict)
    def update_progress(self, data: dict):
        id = data.get("signalId")
        value = data.get("value")
        status_text = data.get("status")

        if (value is None) and (status_text is None) or (id is None):
            if id is None:
                print("No signalId in progress data")
            return
        try:
            if value is not None and type(value) == int:
                self.bar.setValue(value)
            if status_text is not None:
                self.label.setText(status_text)
        except Exception as e:
            print(f"UI update progress error: \n {e.with_traceback()}")
            return
