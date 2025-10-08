# toast.py
from PyQt6.QtCore import Qt, QTimer, QElapsedTimer, QCoreApplication, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QProgressBar, QPushButton, QDialog, QHBoxLayout, QPlainTextEdit
from PyQt6.QtGui import QMouseEvent
import traceback as _tb
import time

_BASE_STYLE = """
QWidget { background:#222; border:1px solid #444; border-radius:8px; }
QLabel#title { color:#fff; font-weight:600; font-family: "Inter"; font-size:16px; }
QLabel#msg { color:#ddd; font-family: "Inter"; font-size:14px; }
QProgressBar {
    background:#2a2a2a; border:1px solid #444; border-radius:4px; height:6px;
}
QProgressBar::chunk { background:%(accent)s; border-radius:4px; }
QPushButton#ok {
    background:transparent; color:%(accent)s; border:1px solid %(accent)s;
    border-radius:6px; padding:4px 10px;
}
QPushButton#ok:hover { background:rgba(255,255,255,0.06); }
QPushButton#details {
    background:transparent; color:#bbb; border:none; padding:0 6px;
    text-decoration: underline;
}
QPushButton#details:hover { color:#fff; }
"""

class _DetailDialog(QDialog):
    def __init__(self, parent: QWidget | None, title: str, details: str):
        super().__init__(parent)
        self.setWindowTitle(f"{title} — Details")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.resize(720, 420)
        lay = QVBoxLayout(self); lay.setContentsMargins(10,10,10,10); lay.setSpacing(8)
        edit = QPlainTextEdit(self)
        edit.setStyleSheet("font-family: 'Inter'; font-size: 14px; color: white")
        edit.setReadOnly(True)
        edit.setPlainText(details)
        lay.addWidget(edit)
        btns = QHBoxLayout(); btns.addStretch(1)
        ok = QPushButton("Close"); ok.clicked.connect(self.accept)
        ok.setStyleSheet("font-family: 'Inter'; color: white")
        btns.addWidget(ok)
        lay.addLayout(btns)

class Toast(QWidget):
    fatalTriggered = pyqtSignal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.ToolTip)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)

        self.lt  = QLabel(objectName="title")
        self.msg = QLabel(objectName="msg"); self.msg.setWordWrap(True)

        # 行內按鈕列：Details 在左，OK 在右
        row = QHBoxLayout(); row.setContentsMargins(0,0,0,0); row.setSpacing(8)
        self.details_btn = QPushButton("Details", objectName="details")
        self.details_btn.clicked.connect(self._open_details)
        self.details_btn.hide()  # 預設隱藏
        self.ok = QPushButton("確定", objectName="ok")
        self.ok.clicked.connect(self._confirm)
        row.addWidget(self.details_btn)
        row.addStretch(1)
        row.addWidget(self.ok)

        self.bar = QProgressBar(); self.bar.setTextVisible(False); self.bar.setRange(0, 1000); self.bar.setFixedHeight(6)

        v.addWidget(self.lt)
        v.addWidget(self.msg)
        v.addLayout(row)
        v.addWidget(self.bar)

        self._hide_timer = QTimer(self); self._hide_timer.timeout.connect(self.hide)
        self._tick = QTimer(self); self._tick.setInterval(16); self._tick.timeout.connect(self._update_bar)  # ~60FPS
        self._elapsed = QElapsedTimer()
        self._ms = 0
        self._accent = "#4dff59"
        self._is_fatal = False
        self._detail_text = ""

        self._apply_style()

        self.fatal_heads = ["Oh no!, Look What You've Done!", 
                            "Well, This is Embarrassing!", 
                            "Boss fight unlocked: Debug Dragon appears!", 
                            "Brace Yourself, It's a Fatal Error!", 
                            "Yikes! That Was Unexpected!", 
                            "Whoops! That Didn't Work Out!",
                            "The program is tired. Taking a quick nap—try again.",
                            "It's not you, it's me. Just kidding, it's definitely you.",
                            "I swear I was working fine 5 minutes ago.",
                            "You found a rare bug. Loot: +1 XP.",
                            "You know what? It's All Your Fault!",
                            "... Fine. You Win.",
                            "I can't believe you've done this.",
                            "Hi again. Fatal Error reporting in. Miss me?",
                            "Hi! Guess who. Fatal Error. Miss me?",
                            "Cache found ancient memes. Became sentient.",
                            "The cake is a lie, and so is this program.",
                            "UI tripped on QSS shoelaces.",
                            "You break new record. Crash Speedrun!",
                            "[Python]: Too scary. (running away at lightspeed)",
                            "Good night, Have sweet dreams! (•̀ᴗ•́)",]

    def _apply_style(self):
        self.setStyleSheet(_BASE_STYLE % {"accent": self._accent})

    def show_notice(
        self,
        level: str,
        title: str,
        message: str | Exception,
        ms: int = 3000,
        px: int | None = None,
        py: int | None = None,
        traceback: object | None = None,
        allow_multiple: bool = True,
    ):
        # 多通知：可同時開新 toast
        if self._is_fatal:
            return
        if allow_multiple and self.isVisible():
            twin = Toast(self.parent())
            twin.fatalTriggered.connect(self.fatalTriggered) # 轉發
            if py:
                py -= self.height()
            return twin.show_notice(level, title, message, ms, px, py, traceback, allow_multiple=False)

        colors = {"info": "#38c942", "warn": "#ffbd4a", "error": "#ff5c5c", "debug": "#11a4f3", "fatal": "#ff00ea"}
        self._accent = colors.get(level.lower(), "#11a4f3")
        self._apply_style()

        # 組合詳情
        if isinstance(message, Exception):
            base = f"{message.__class__.__name__}: {message}"
        else:
            base = str(message)

        if traceback:
            if isinstance(traceback, str):
                tb_text = traceback
            else:
                tb_text = _tb.format_exc()
            self._detail_text = tb_text
        else:
            self._detail_text = base

        self.lt.setText(title)
        self.msg.setText(base)
        self.adjustSize()
        self.details_btn.setVisible(False)

        self._is_fatal = (level.lower() == "fatal")
        if self._is_fatal:
            t_head = ""
            import random
            t_head = random.choice(self.fatal_heads) + "\n\n" + time.strftime("%Y-%m-%d %H:%M:%S")
            self._detail_text = f"{t_head}\n\n{self._detail_text}"
            self.details_btn.setVisible(True)
            self.ok.setText("Exit")
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint |
                Qt.WindowType.Tool |
                Qt.WindowType.WindowStaysOnTopHint
            )
            self.fatalTriggered.emit()

        if px is not None and py is not None:
            # 右下對齊父座標基準
            self.move(px + 20, py + (self.parent().height() - self.height() - 20))

        self._ms = max(200, int(ms))
        self.bar.setValue(1000)
        self._elapsed.restart()
        self._tick.start()
        self._hide_timer.start(self._ms)
        self.show()

    def _open_details(self):
        dlg = _DetailDialog(self.window(), self.lt.text() or "Details", self._detail_text)
        dlg.open()  # 非阻塞

    def _update_bar(self):
        elapsed = self._elapsed.elapsed()
        remain = max(0, self._ms - elapsed)
        self.bar.setValue(int(remain / self._ms * 1000)) 

        if remain <= 0:
            self._tick.stop()
            if self._is_fatal:
                self._do_fatal()
            else:
                self.hide()

    def _confirm(self):
        self._tick.stop()
        self._hide_timer.stop()
        self.hide()
        if self._is_fatal:
            self._do_fatal()

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

    def _do_fatal(self):
        try:
            pass
        finally:
            QCoreApplication.quit()
