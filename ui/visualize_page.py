#ui/visualize_page.py
# import numpy as np
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QToolButton,
    QWidget,
    QStackedLayout,
    QVBoxLayout,
    QProgressBar,
)
from PyQt6.QtCore import Qt, QTimer, QDateTime, pyqtSlot, pyqtSignal, QRect
from PyQt6.QtGui import QImage, QPixmap, QPainter, QPen, QColor, QFont, QFontMetrics
import cv2

class VisualizePage(QWidget):
    on_exception = pyqtSignal(object, object)
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("VisualizePage")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        # v.addStretch()

        self.label = QLabel("Visualize", self)
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.label.setStyleSheet("""
                background-color: none;
                font-family: "Inter";
                font-style: normal;
                font-weight: 500;
                font-size: 20px;
                color: #FFFFFF;     
            """)
        
        v.addWidget(self.label, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.view = QLabel("No signal", self)
        self.view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.view.setStyleSheet("color: #FFFFFF; font-size:18px; font-family: Inter; background-color: #1E1E1E; border: 2px dashed #444;")
        # self.view.setMinimumSize(640, 640)
        self._pix = None
        self._last_update = None

        v.addWidget(self.view, alignment=Qt.AlignmentFlag.AlignCenter)
        v.addStretch()
        self.view.setMinimumSize(160, 160)
        self.view.setMaximumSize(960, 960)
        self.view.setBaseSize(640, 640)  # for layout stable

        # 監測 3 秒未更新
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(500)  # 0.5s 檢查一次
        self._watchdog.timeout.connect(self._check_signal)
        self._watchdog.start()

    @pyqtSlot(object, object, object, object)
    def on_image(self, img, boxes=None, scores=None, cls_inds=None):
        """
        img: numpy ndarray (H,W,3|4, BGR/BGRA) 或 QImage
        """
        self._last_update = QDateTime.currentDateTimeUtc()
        try:
            if isinstance(img, QImage):
                qimg = img
            else:
            # numpy -> QImage (假設 BGRA 或 BGR)
            
                # import numpy as np
                if img.ndim == 3 and img.shape[2] == 4:            # BGRA uint8
                    h, w = img.shape[:2]
                    if hasattr(QImage.Format, "Format_BGRA8888"):   # 新版可直用
                        qimg = QImage(img.data, w, h, w*4, QImage.Format.Format_BGRA8888).copy()
                    else:                                           # 舊版無 BGRA8888，改用 RGBA8888
                        rgba = img[:, :, [2,1,0,3]].copy()         # BGRA -> RGBA
                        qimg = QImage(rgba.data, w, h, w*4, QImage.Format.Format_RGBA8888).copy()
                elif img.ndim == 3 and img.shape[2] == 3:          # BGR uint8
                    h, w = img.shape[:2]
                    rgb = img[:, :, ::-1].copy()                    # BGR -> RGB
                    qimg = QImage(rgb.data, w, h, w*3, QImage.Format.Format_RGB888).copy()
                else:
                    return
                
            # 這裡畫框與標籤
            if boxes is not None and len(boxes):
                self._draw_dets(qimg, boxes, scores, cls_inds)
        except Exception as e:
                self.on_exception.emit(type(e), e)
                return

        self._pix = QPixmap.fromImage(qimg)
        self._render_pix()

    def resizeEvent(self, e):
        self._render_pix()
        return super().resizeEvent(e)

    def _render_pix(self):
        if self._pix is None:
            self.view.setText("No signal")
            self.view.setPixmap(QPixmap())
            return
        scaled = self._pix.scaled(self.view.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
        self.view.setPixmap(scaled)
        self.view.setText("")

    def _check_signal(self):
        if self._last_update is None:
            self.view.setText("No signal")
            if self.view.pixmap() is not None:
                self.view.setPixmap(QPixmap())
            return
        if self._last_update.msecsTo(QDateTime.currentDateTimeUtc()) > 3000:
            self._pix = None
            self.view.setText("No signal")
            self.view.setPixmap(QPixmap())

    def _draw_dets(self, qimg: QImage, boxes, scores=None, cls_inds=None):
        # 取閾值與標籤（可選）
        conf_thr = getattr(getattr(self, "args", None), "conf", 0.4) if hasattr(self, "args") else 0.0
        labels = getattr(getattr(self, "args", None), "label_list", [])

        p = QPainter(qimg)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        W, H = qimg.width(), qimg.height()
        cols = [(255,99,132),(54,162,235),(255,206,86),(75,192,192),(153,102,255),(255,159,64)]
        thickness = max(2, int(min(W, H) * 0.003))
        font = QFont("Inter", 10)

        n = len(boxes)
        for i in range(n):
            # 信心值過濾
            if scores is not None and float(scores[i]) < float(conf_thr):
                continue

            b = boxes[i]
            try:
                x1, y1, x2, y2 = map(int, b[:4])
            except Exception:
                continue
            if (x1, y1, x2, y2) == (0, 0, 0, 0):
                break
            if x2 <= x1 or y2 <= y1:
                continue

            # 類別與顏色
            ci = int(cls_inds[i]) if cls_inds is not None else 0
            r, g, b = cols[ci % len(cols)]

            # 矩形（空心）
            p.setPen(QPen(QColor(r, g, b), thickness))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(x1, y1, x2 - x1, y2 - y1)

            # 標籤文字
            lbl = labels[ci] if labels and 0 <= ci < len(labels) else str(ci)
            if scores is not None:
                lbl = f"{lbl} {float(scores[i]):.2f}"

            p.setFont(font)
            fm = QFontMetrics(font)
            tw = fm.horizontalAdvance(lbl) + 8
            th = fm.height() + 4
            rect = QRect(x1, max(0, y1 - th), tw, th)

            # 背板 + 文字
            p.fillRect(rect, QColor(r, g, b, 160))
            p.setPen(Qt.GlobalColor.white)
            p.drawText(rect.adjusted(4, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, lbl)

        p.end()
