# ui/widgets.py
# 共用小元件：卡片、開關、分段按鈕、資訊欄位
from PyQt6.QtCore import Qt, QSize, QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import theme as T


class Card(QFrame):
    """深色圓角卡片，內容放在 self.body (QVBoxLayout)。"""

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#Card {{ background:{T.CARD_BG}; border:1px solid {T.CARD_BORDER}; border-radius:12px; }}"
        )
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 12)
        v.setSpacing(8)

        if title:
            self.title = QLabel(title)
            self.title.setStyleSheet(
                f"color:{T.TEXT_DIM}; font-family:{T.FONT}; font-size:12px; font-weight:600;"
                "background:transparent; border:none;"
            )
            v.addWidget(self.title)

        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(8)
        v.addLayout(self.body, 1)


class ToggleSwitch(QAbstractButton):
    """iOS 風格開關，用 toggled(bool) 取值。"""

    def __init__(self, parent=None, checked: bool = False):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(40, 22)

    def sizeHint(self):
        return QSize(40, 22)

    def set_checked_silent(self, checked: bool):
        self.blockSignals(True)
        self.setChecked(checked)
        self.blockSignals(False)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        on = self.isChecked()
        track = QColor(T.ACCENT if on else T.SURFACE_HOVER)
        if not self.isEnabled():
            track = QColor(T.DISABLED)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)

        d = r.height() - 6
        x = r.right() - d - 3 if on else r.left() + 3
        p.setBrush(QColor("#FFFFFF" if self.isEnabled() else "#999999"))
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))


class SegmentedControl(QWidget):
    """一排互斥按鈕，取代下拉選單。使用者點擊時發出 changed(index)。"""

    changed = pyqtSignal(int)

    def __init__(self, options: list[str], parent=None, accent_colors: list[str] | None = None):
        super().__init__(parent)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        n = len(options)
        for i, text in enumerate(options):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setMinimumHeight(28)
            accent = accent_colors[i] if accent_colors else T.ACCENT
            left = "8px" if i == 0 else "0px"
            right = "8px" if i == n - 1 else "0px"
            # 被選中時用 accent 底色；分隔線用左邊框
            b.setStyleSheet(
                f"""
                QPushButton {{
                    background:{T.SURFACE}; color:{T.TEXT}; font-family:{T.FONT}; font-size:12px;
                    border:1px solid {T.CARD_BORDER}; {'' if i == 0 else 'border-left:none;'}
                    border-top-left-radius:{left}; border-bottom-left-radius:{left};
                    border-top-right-radius:{right}; border-bottom-right-radius:{right};
                    padding:4px 10px;
                }}
                QPushButton:hover {{ background:{T.SURFACE_HOVER}; }}
                QPushButton:checked {{ background:{accent}; color:#FFFFFF; font-weight:600; }}
                QPushButton:disabled {{ color:#6A6A6A; }}
                QPushButton:checked:disabled {{ background:#3C3C3C; color:#9E9E9E; }}
                """
            )
            self._group.addButton(b, i)
            h.addWidget(b)

        self._group.idClicked.connect(self.changed.emit)

    def index(self) -> int:
        return self._group.checkedId()

    def set_index(self, i: int):
        """程式設定選取，不發出 changed。"""
        b = self._group.button(i)
        if b is not None:
            b.setChecked(True)


class InfoItem(QWidget):
    """上面小字標籤、下面數值，系統資訊 / 即時數據用。"""

    def __init__(self, label: str, value: str = "—", parent=None, value_size: int = 13):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(1)
        self._label = QLabel(label)
        self._label.setStyleSheet(
            f"color:{T.TEXT_DIM}; font-family:{T.FONT}; font-size:11px; background:transparent; border:none;"
        )
        self._value = QLabel(value)
        self._value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._value_style = (
            f"font-family:{T.FONT}; font-size:{value_size}px; font-weight:600; background:transparent; border:none;"
        )
        self.set_value(value)
        v.addWidget(self._label)
        v.addWidget(self._value)

    def set_value(self, value: str, color: str = T.TEXT):
        self._value.setText(value)
        self._value.setToolTip(value)
        self._value.setStyleSheet(f"color:{color}; {self._value_style}")


def field_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color:{T.TEXT}; font-family:{T.FONT}; font-size:13px; background:transparent; border:none;"
    )
    return lbl


def hint_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color:{T.TEXT_DIM}; font-family:{T.FONT}; font-size:11px; background:transparent; border:none;"
    )
    return lbl
