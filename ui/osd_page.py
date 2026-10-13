# ui/osd_page.py
# OSD 設定頁：選顯示器 (仿 Windows 排列圖) + 選角落 + 偏移
import sys
from PyQt6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen, QScreen
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from utils.osd_layout import (
    CORNERS,
    OFFSET_MAX,
    display_numbers,
    layout_tiles,
    normalize_osd_cfg,
    resolve_monitor,
)

from . import theme as T
from .widgets import Card, ToggleSwitch, field_label, hint_label

_CORNER_TEXT = {
    "top_left": "左上",
    "top_right": "右上",
    "bottom_left": "左下",
    "bottom_right": "右下",
}


def _win_display_devices() -> dict[tuple[int, int], str]:
    """{(左上 x, 左上 y): Windows 裝置名稱 (例如 DISPLAY1 的完整路徑)}，用 EnumDisplayMonitors 取得。"""
    if sys.platform != "win32":
        return {}
    try:
        import ctypes
        from ctypes import wintypes

        class MONITORINFOEXW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD),
                ("szDevice", wintypes.WCHAR * 32),
            ]

        user32 = ctypes.windll.user32
        out = {}
        proc_t = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM
        )

        def _cb(hmon, _hdc, _rc, _lp):
            mi = MONITORINFOEXW()
            mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
            if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                out[(mi.rcMonitor.left, mi.rcMonitor.top)] = mi.szDevice
            return True

        user32.EnumDisplayMonitors(None, None, proc_t(_cb), 0)
        return out
    except Exception:
        return {}


def _screens() -> list[QScreen]:
    return list(QGuiApplication.screens())


def screen_id(s: QScreen, devices: dict | None = None) -> str:
    """
    顯示器識別字串。Qt 6 的 QScreen.name() 在 Windows 回傳型號 (同型號螢幕會重複)，
    所以優先用 Windows 裝置名稱 (DISPLAYn，以左上角座標對應)。
    """
    if devices is None:
        devices = _win_display_devices()
    g = s.geometry()
    return devices.get((g.x(), g.y()), s.name())


def _screen_ids() -> list[tuple[str, QScreen]]:
    devices = _win_display_devices()
    return [(screen_id(s, devices), s) for s in _screens()]


def _numbers(ids: list[tuple[str, QScreen]]) -> dict:
    primary = QGuiApplication.primaryScreen()
    pid = next((sid for sid, s in ids if s is primary), None)
    return display_numbers([sid for sid, _ in ids], pid)


def _screen_by_name(name: str) -> QScreen | None:
    for sid, s in _screen_ids():
        if sid == name:
            return s
    return None


def _native_rect(s: QScreen) -> tuple[int, int, int, int]:
    """排列圖用：Windows 上 QScreen 左上角是原生座標，寬高是邏輯尺寸，乘回 DPR 才是實際比例。"""
    g = s.geometry()
    dpr = s.devicePixelRatio()
    return g.x(), g.y(), round(g.width() * dpr), round(g.height() * dpr)


def short_screen_name(name: str) -> str:
    return name.replace("\\\\.\\", "").replace("\\", "") or name


def describe_screen(s: QScreen) -> str:
    _, _, w, h = _native_rect(s)
    sid = screen_id(s)
    head = [short_screen_name(sid)]
    if s.name() != sid:
        head.append(s.name())  # 型號
    parts = [f"{w}×{h}"]
    hz = s.refreshRate()
    if hz:
        parts.append(f"{hz:.0f}Hz")
    dpr = s.devicePixelRatio()
    if abs(dpr - 1.0) > 0.01:
        parts.append(f"縮放 {dpr * 100:.0f}%")
    if s is QGuiApplication.primaryScreen():
        parts.append("主顯示器")
    return " · ".join(head) + "\n" + " · ".join(parts)


# ---------------------------------------------------------------------------
# Controller：解析顯示器、fallback、把設定套到 OSD
# ---------------------------------------------------------------------------


class OsdController(QObject):
    screensChanged = pyqtSignal()

    def __init__(self, store, osd, window: QWidget, notify=None):
        super().__init__(window)
        self.store = store
        self.osd = osd
        self.window = window
        self.notify = notify  # notify(level, title, message)
        self.running = False

        # 舊設定檔沒有 osd 區塊 / 值不合法 -> 補齊並存檔
        cfg = normalize_osd_cfg(self.store.get(("osd",)))
        if self.store.get(("osd",)) != cfg:
            self.store.set(("osd",), cfg)

        app = QGuiApplication.instance()
        app.screenAdded.connect(self._on_screens_changed)
        app.screenRemoved.connect(self._on_screens_changed)
        app.primaryScreenChanged.connect(self._on_screens_changed)
        for s in _screens():
            self._watch(s)

        self.store.changed.connect(self._on_cfg_changed)

    def cfg(self) -> dict:
        return normalize_osd_cfg(self.store.get(("osd",)))

    def current_screen(self) -> QScreen | None:
        s = self.window.screen() if self.window is not None else None
        return s or QGuiApplication.primaryScreen()

    def resolve(self) -> QScreen | None:
        """確認設定的顯示器存在，不存在就 fallback 到當前顯示器並自動存檔。"""
        saved = self.cfg()["monitor"]
        names = [sid for sid, _ in _screen_ids()]
        cur = self.current_screen()
        name, changed = resolve_monitor(saved, names, screen_id(cur) if cur else None)
        if changed:
            self.store.set(("osd", "monitor"), name)
            if saved and self.notify:
                self.notify(
                    "warn",
                    "OSD 顯示器已切換",
                    f"找不到顯示器 {short_screen_name(saved)}，OSD 已改到 {short_screen_name(name)} 並自動儲存。",
                )
        return _screen_by_name(name)

    def apply(self):
        screen = self.resolve()
        cfg = self.cfg()
        self.osd.set_placement(screen, cfg["corner"], cfg["offset_x"], cfg["offset_y"])

    def start(self):
        self.running = True
        self.apply()
        if self.cfg()["enabled"]:
            self.osd.show_osd()

    def stop(self):
        self.running = False
        self.osd.hide_osd()

    def preview(self, ms: int = 3000):
        self.apply()
        self.osd.preview(ms)

    def _watch(self, s: QScreen):
        s.geometryChanged.connect(self._on_screens_changed)

    def _on_screens_changed(self, *args):
        if args and isinstance(args[0], QScreen) and args[0] in _screens():
            self._watch(args[0])
        # screenRemoved 發出時清單可能還沒更新，延到下一輪事件迴圈再處理
        QTimer.singleShot(0, self._after_screens_changed)

    def _after_screens_changed(self):
        self.apply()
        self.screensChanged.emit()

    def _on_cfg_changed(self, path: tuple, value):
        if not path or path[0] != "osd":
            return
        if path == ("osd", "enabled") and self.running:
            if value:
                self.apply()
                self.osd.show_osd(self.osd.mouse_mode)
            else:
                self.osd.hide_osd()
            return
        self.apply()


# ---------------------------------------------------------------------------
# 顯示器排列圖
# ---------------------------------------------------------------------------


class MonitorArrangement(QWidget):
    monitorSelected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(150)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._selected = ""
        self._hover = -1
        self._tiles: list[tuple[QRectF, str]] = []

    def set_selected(self, name: str):
        self._selected = name
        self.update()

    def _layout(self):
        ids = _screen_ids()
        rects = [_native_rect(s) for _, s in ids]
        tiles = layout_tiles(rects, self.width(), self.height(), margin=10, gap=4)
        self._tiles = [(QRectF(*t), sid) for t, (sid, _) in zip(tiles, ids)]
        self._nums = _numbers(ids)

    def _index_at(self, pos: QPointF) -> int:
        for i, (r, _) in enumerate(self._tiles):
            if r.contains(pos):
                return i
        return -1

    def paintEvent(self, _):
        self._layout()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        for i, (r, sid) in enumerate(self._tiles):
            selected = sid == self._selected
            if selected:
                fill = QColor(T.ACCENT_HOVER if i == self._hover else T.ACCENT)
                pen = QPen(QColor(T.BORDER_LIGHT), 1.5)
            else:
                fill = QColor("#3A3A3A" if i == self._hover else "#2E2E2E")
                pen = QPen(QColor("#8A8A8A"), 1.2)
            p.setPen(pen)
            p.setBrush(fill)
            p.drawRect(r)

            num = self._nums.get(sid, i + 1)
            f = QFont("Segoe UI Light")
            f.setPixelSize(max(12, min(48, int(r.height() * 0.45))))
            p.setFont(f)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, str(num))

    def mouseMoveEvent(self, e):
        i = self._index_at(e.position())
        if i != self._hover:
            self._hover = i
            self.update()

    def leaveEvent(self, _):
        self._hover = -1
        self.update()

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        i = self._index_at(e.position())
        if i >= 0:
            name = self._tiles[i][1]
            self.set_selected(name)
            self.monitorSelected.emit(name)


class _IdentifyBadge(QLabel):
    """「識別」時顯示在每個螢幕左下角的大號碼 (同 Windows)。"""

    def __init__(self, num: int, screen: QScreen):
        super().__init__(str(num))
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(150, 150)
        self.setStyleSheet(
            "background:#1F1F1F; color:#FFFFFF; border:1px solid #6A6A6A;"
            "font-family:'Segoe UI Light'; font-size:96px;"
        )
        self.setScreen(screen)
        g = screen.geometry()
        self.move(g.x() + 40, g.y() + g.height() - 150 - 60)


# ---------------------------------------------------------------------------
# 四角選擇器
# ---------------------------------------------------------------------------


class CornerPicker(QWidget):
    cornerSelected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(150)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._corner = "top_left"
        self._aspect = 16 / 9
        self._hover = ""
        self._tiles: dict[str, QRectF] = {}

    def set_corner(self, corner: str):
        self._corner = corner
        self.update()

    def set_aspect(self, w: int, h: int):
        if w > 0 and h > 0:
            self._aspect = w / h
            self.update()

    def _frame(self) -> QRectF:
        m = 6
        aw, ah = self.width() - 2 * m, self.height() - 2 * m
        if aw / max(1, ah) > self._aspect:
            h = ah
            w = h * self._aspect
        else:
            w = aw
            h = w / self._aspect
        return QRectF(m + (aw - w) / 2, m + (ah - h) / 2, w, h)

    def _layout(self):
        f = self._frame()
        pad = 8
        tw, th = f.width() * 0.36, f.height() * 0.36
        self._tiles = {
            "top_left": QRectF(f.left() + pad, f.top() + pad, tw, th),
            "top_right": QRectF(f.right() - pad - tw, f.top() + pad, tw, th),
            "bottom_left": QRectF(f.left() + pad, f.bottom() - pad - th, tw, th),
            "bottom_right": QRectF(f.right() - pad - tw, f.bottom() - pad - th, tw, th),
        }

    def _corner_at(self, pos: QPointF) -> str:
        for c, r in self._tiles.items():
            if r.contains(pos):
                return c
        return ""

    def paintEvent(self, _):
        self._layout()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 螢幕外框
        f = self._frame()
        p.setPen(QPen(QColor("#5A5A5A"), 1.2))
        p.setBrush(QColor("#151515"))
        p.drawRoundedRect(f, 8, 8)

        font = QFont("Source Han Sans TC")
        font.setPixelSize(12)
        p.setFont(font)

        for c, r in self._tiles.items():
            selected = c == self._corner
            if selected:
                p.setPen(QPen(QColor(T.ACCENT), 2))
                p.setBrush(QColor(0, 120, 212, 45))
            else:
                hover = c == self._hover
                p.setPen(QPen(QColor("#4A4A4A" if hover else T.CARD_BORDER), 1))
                p.setBrush(QColor(T.SURFACE_HOVER if hover else "#1E1E1E"))
            p.drawRoundedRect(r, 8, 8)

            if selected:
                self._draw_mini_osd(p, r, c)
            else:
                p.setPen(QColor(T.TEXT_DIM))
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, _CORNER_TEXT[c])

    def _draw_mini_osd(self, p: QPainter, r: QRectF, corner: str):
        w, h = r.width() * 0.5, r.height() * 0.42
        m = 7
        x = r.right() - m - w if "right" in corner else r.left() + m
        y = r.bottom() - m - h if "bottom" in corner else r.top() + m
        box = QRectF(x, y, w, h)
        p.setPen(QPen(QColor("#6A6A6A"), 1))
        p.setBrush(QColor(34, 34, 34, 220))
        p.drawRoundedRect(box, 4, 4)
        # 三行文字示意
        line_h = max(2.0, h * 0.12)
        colors = [QColor("#FFFFFF"), QColor(T.MODE_COLORS[1]), QColor("#BBBBBB")]
        widths = [0.55, 0.7, 0.45]
        p.setPen(Qt.PenStyle.NoPen)
        for i, (col, wf) in enumerate(zip(colors, widths)):
            ly = box.top() + h * (0.2 + i * 0.25)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(box.left() + w * 0.12, ly, w * wf, line_h), 1, 1)

        p.setPen(QColor(T.TEXT))
        label_rect = QRectF(r.left(), r.top(), r.width(), r.height())
        align = Qt.AlignmentFlag.AlignBottom if "top" in corner else Qt.AlignmentFlag.AlignTop
        align |= Qt.AlignmentFlag.AlignLeft if "right" in corner else Qt.AlignmentFlag.AlignRight
        p.drawText(label_rect.adjusted(8, 6, -8, -6), align, _CORNER_TEXT[corner])

    def mouseMoveEvent(self, e):
        c = self._corner_at(e.position())
        if c != self._hover:
            self._hover = c
            self.update()

    def leaveEvent(self, _):
        self._hover = ""
        self.update()

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        c = self._corner_at(e.position())
        if c in CORNERS:
            self.set_corner(c)
            self.cornerSelected.emit(c)


# ---------------------------------------------------------------------------
# 頁面
# ---------------------------------------------------------------------------


class OsdPage(QWidget):
    on_exception = pyqtSignal(type, object)

    def __init__(self, parent, store, controller: OsdController):
        super().__init__(parent)
        self.setObjectName("OsdPage")
        self.store = store
        self.ctrl = controller
        self._badges: list[_IdentifyBadge] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # --- 標題列 ---
        head = QHBoxLayout()
        head.setSpacing(10)
        title = QLabel("OSD 設定")
        title.setStyleSheet(
            f"color:{T.TEXT_WHITE}; font-family:{T.FONT}; font-size:20px; font-weight:600;"
        )
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(field_label("啟用 OSD"))
        self.enable_sw = ToggleSwitch()
        head.addWidget(self.enable_sw)
        head.addSpacing(8)
        self.preview_btn = QPushButton("預覽 3 秒")
        self.preview_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.preview_btn.setStyleSheet(T.button_style(T.BLUE, T.BLUE_HOVER, pad="5px 14px"))
        head.addWidget(self.preview_btn)
        root.addLayout(head)

        # --- 兩張卡片 ---
        row = QHBoxLayout()
        row.setSpacing(14)

        mon = Card("顯示器")
        mon.body.addWidget(hint_label("點選要顯示 OSD 的螢幕"))
        self.arrangement = MonitorArrangement()
        mon.body.addWidget(self.arrangement, 1)
        info_row = QHBoxLayout()
        self.screen_info = QLabel()
        self.screen_info.setStyleSheet(
            f"color:{T.TEXT}; font-family:{T.FONT}; font-size:12px; background:transparent; border:none;"
        )
        self.screen_info.setWordWrap(True)
        info_row.addWidget(self.screen_info, 1)
        self.identify_btn = QPushButton("識別")
        self.identify_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.identify_btn.setStyleSheet(T.ghost_button_style())
        info_row.addWidget(self.identify_btn)
        mon.body.addLayout(info_row)
        row.addWidget(mon, 1)

        pos = Card("位置")
        pos.body.addWidget(hint_label("點選 OSD 要貼齊的角落"))
        self.corner_picker = CornerPicker()
        pos.body.addWidget(self.corner_picker, 1)
        off_row = QHBoxLayout()
        off_row.setSpacing(8)
        self.off_x = self._make_spin()
        self.off_y = self._make_spin()
        off_row.addWidget(field_label("水平偏移"))
        off_row.addWidget(self.off_x)
        off_row.addSpacing(10)
        off_row.addWidget(field_label("垂直偏移"))
        off_row.addWidget(self.off_y)
        off_row.addStretch(1)
        pos.body.addLayout(off_row)
        row.addWidget(pos, 1)

        root.addLayout(row, 1)
        root.addWidget(hint_label("變更會自動儲存並立即套用；選定的顯示器中斷連線時，會自動改到目前的顯示器。"))

        # --- 訊號 ---
        self.enable_sw.toggled.connect(lambda b: self.store.set(("osd", "enabled"), bool(b)))
        self.preview_btn.clicked.connect(lambda: self.ctrl.preview(3000))
        self.identify_btn.clicked.connect(self._identify)
        self.arrangement.monitorSelected.connect(lambda n: self.store.set(("osd", "monitor"), n))
        self.corner_picker.cornerSelected.connect(lambda c: self.store.set(("osd", "corner"), c))
        self.off_x.valueChanged.connect(lambda v: self.store.set(("osd", "offset_x"), int(v)))
        self.off_y.valueChanged.connect(lambda v: self.store.set(("osd", "offset_y"), int(v)))

        self.store.changed.connect(self._on_cfg_changed)
        self.ctrl.screensChanged.connect(self.sync)

        self.sync()

    def _make_spin(self) -> QSpinBox:
        sp = QSpinBox()
        sp.setRange(0, OFFSET_MAX)
        sp.setSuffix(" px")
        sp.setFixedWidth(84)
        sp.setStyleSheet(T.SPINBOX_STYLE)
        return sp

    def _on_cfg_changed(self, path: tuple, _value):
        if path and path[0] == "osd":
            self.sync()

    def sync(self):
        """把設定值反映到畫面上 (不觸發存檔)。"""
        cfg = self.ctrl.cfg()
        for w in (self.enable_sw, self.off_x, self.off_y):
            w.blockSignals(True)
        self.enable_sw.setChecked(cfg["enabled"])
        self.enable_sw.update()
        self.off_x.setValue(cfg["offset_x"])
        self.off_y.setValue(cfg["offset_y"])
        for w in (self.enable_sw, self.off_x, self.off_y):
            w.blockSignals(False)

        self.arrangement.set_selected(cfg["monitor"])
        self.corner_picker.set_corner(cfg["corner"])

        s = _screen_by_name(cfg["monitor"])
        if s is not None:
            _, _, w, h = _native_rect(s)
            self.corner_picker.set_aspect(w, h)
            self.screen_info.setText(describe_screen(s))
        else:
            self.screen_info.setText("—")
        self.arrangement.update()

    def _identify(self):
        for b in self._badges:
            b.close()
        ids = _screen_ids()
        nums = _numbers(ids)
        self._badges = [_IdentifyBadge(nums.get(sid, i + 1), s) for i, (sid, s) in enumerate(ids)]
        for b in self._badges:
            b.show()
        QTimer.singleShot(2000, self._close_badges)

    def _close_badges(self):
        for b in self._badges:
            b.close()
        self._badges = []
