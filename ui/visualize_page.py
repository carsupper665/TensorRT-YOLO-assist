# ui/visualize_page.py
from PyQt6.QtWidgets import (
    QLabel,
    QWidget,
    QVBoxLayout,
)
from PyQt6.QtCore import (
    Qt,
    QTimer,
    pyqtSlot,
    pyqtSignal,
    QRect,
    QElapsedTimer,
)
from PyQt6.QtGui import QImage, QPixmap, QPainter, QPen, QColor, QFont, QFontMetrics
import math


class VisualizePage(QWidget):
    on_exception = pyqtSignal(object, object)
    osd_fps = pyqtSignal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("VisualizePage")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)

        self.parent = parent

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
        self.view.setStyleSheet(
            "color: #FFFFFF; font-size:18px; font-family: Inter; "
            "background-color: #1E1E1E; border: 2px dashed #444;"
        )
        self.view.setMinimumSize(160, 160)
        self.view.setMaximumSize(960, 960)
        self.view.setBaseSize(640, 640)

        v.addWidget(self.view, alignment=Qt.AlignmentFlag.AlignCenter)
        v.addStretch()

        # 目前顯示中的 pixmap
        self._pix: QPixmap | None = None

        # FPS 計算（輸入訊號的實際 FPS）
        self._fps_tau = 0.5
        self._dt_ema = None
        self._fps = 0.0
        self._fps_text = "FPS: --"

        self._fps_timer = QElapsedTimer()
        self._fps_timer.start()

        # 控制 FPS 文字更新頻率（避免數字抖動）
        self._fps_ui_timer = QElapsedTimer()
        self._fps_ui_timer.start()

        # 控制實際畫面重繪頻率（限制 UI FPS）
        self._display_timer = QElapsedTimer()
        self._display_timer.start()
        self._min_redraw_interval_ms = 50  # 約 30 FPS，視需要可調整

        # 最後一次收到畫面的時間，用於 watchdog
        self._last_update_timer = QElapsedTimer()
        self._last_update_timer.invalidate()

        # -------- 繪圖資源緩存，避免每幀新建 --------
        self._fps_font = QFont("Inter", 12)
        self._fps_pen = QPen(Qt.GlobalColor.white)
        self._fps_bg_color = QColor(0, 0, 0, 120)

        self._bbox_font = QFont("Source Han Sans TC", 10)
        self._det_colors = [
            QColor(255, 99, 132),
            QColor(54, 162, 235),
            QColor(255, 206, 86),
            QColor(75, 192, 192),
            QColor(153, 102, 255),
            QColor(255, 159, 64),
        ]

        # 是否使用高品質縮放（CPU 負載高），預設 False 走 FastTransformation
        self._use_smooth_scale = False

        # 監測未更新（watchdog）
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(1500)  # 0.5s 檢查一次
        self._watchdog.timeout.connect(self._check_signal)
        self._watchdog.start()

    # ---------------- 信號處理 ----------------

    @pyqtSlot(object, object, object, object)
    def on_image(self, img, boxes=None, scores=None, cls_inds=None, conf=None):
        """
        img: numpy ndarray (H,W,3|4, BGR/BGRA) 或 QImage
        """
        # 更新「最後一次收到畫面」的時間
        if not self._last_update_timer.isValid():
            self._last_update_timer.start()
        else:
            self._last_update_timer.restart()

        # 更新輸入 FPS（訊號真正的 FPS，而不是 UI FPS）
        dt = self._fps_timer.restart() / 1000.0
        if dt > 0:
            alpha = 1.0 - math.exp(-dt / self._fps_tau)
            self._dt_ema = dt if self._dt_ema is None else (
                (1 - alpha) * self._dt_ema + alpha * dt
            )
            self._fps = 1.0 / self._dt_ema

        # 每 250ms 才更新一次文字（減少 UI 抖動）
        if self._fps_ui_timer.elapsed() >= 250:
            self._fps_text = f"FPS: {self._fps:.1f}"
            self._fps_ui_timer.restart()

        # 限制 UI 重繪 FPS（如果訊號太快就丟幀）
        if self._display_timer.elapsed() < self._min_redraw_interval_ms:
            return
        self._display_timer.restart()

        # 如果 widget 是隱藏的，其實可以直接 return（完全不畫）
        if not self.isVisible():
            return

        # numpy -> QImage + 繪製 detection
        try:
            qimg = self._to_qimage(img)
            if qimg is None:
                return

            # 畫框與標籤
            if boxes is not None and len(boxes):
                self._draw_dets(qimg, boxes, scores, cls_inds)
        except Exception as e:
            self.on_exception.emit(type(e), e)
            return

        # 先縮放到 QLabel 大小（只縮放一次）
        if self.view.width() > 0 and self.view.height() > 0:
            target_size = self.view.size()
            transform_mode = (
                Qt.TransformationMode.SmoothTransformation
                if self._use_smooth_scale
                else Qt.TransformationMode.FastTransformation
            )
            qimg = qimg.scaled(
                target_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                transform_mode,
            )

        self._pix = QPixmap.fromImage(qimg)

        # FPS 文字疊在右上角
        try:
            if self._fps_text:
                painter = QPainter(self._pix)
                painter.setRenderHint(
                    QPainter.RenderHint.TextAntialiasing, True
                )
                painter.setPen(self._fps_pen)
                painter.setFont(self._fps_font)

                fm = QFontMetrics(self._fps_font)
                txt = self._fps_text
                self.osd_fps.emit(txt)

                text_w = fm.horizontalAdvance(txt)
                text_h = fm.height()
                x = max(8, self._pix.width() - text_w - 12)
                y = fm.ascent() + 8

                bg_rect_w = text_w + 8
                bg_rect_h = text_h + 4

                painter.fillRect(
                    x - 4,
                    y - fm.ascent() - 2,
                    bg_rect_w,
                    bg_rect_h,
                    self._fps_bg_color,
                )
                painter.drawText(x, y, txt)
                painter.end()
        except Exception:
            # 不讓 FPS 繪製錯誤影響主流程
            pass

        self._render_pix()

    # ---------------- Qt 事件 ----------------

    def resizeEvent(self, e):
        # 視窗大小改變時，重新縮放目前這張圖即可
        self._render_pix()
        return super().resizeEvent(e)

    # ---------------- 私有輔助函式 ----------------

    def _render_pix(self):
        if self._pix is None:
            self.view.setText("No signal")
            self.view.setPixmap(QPixmap())
            return

        if self.view.width() <= 0 or self.view.height() <= 0:
            return

        # 如果大小剛好就直接用，不再重複縮放
        if (
            self._pix.width() == self.view.width()
            and self._pix.height() == self.view.height()
        ):
            scaled = self._pix
        else:
            transform_mode = (
                Qt.TransformationMode.SmoothTransformation
                if self._use_smooth_scale
                else Qt.TransformationMode.FastTransformation
            )
            scaled = self._pix.scaled(
                self.view.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                transform_mode,
            )

        self.view.setPixmap(scaled)
        self.view.setText("")

    def _check_signal(self):
        # 還沒收過畫面
        if not self._last_update_timer.isValid():
            self.view.setText("No signal")
            if self.view.pixmap() is not None:
                self.view.setPixmap(QPixmap())
            return

        # 超過 3 秒沒更新視為斷訊
        if self._last_update_timer.elapsed() > 3000:
            self._pix = None
            self.view.setText("No signal")
            self.view.setPixmap(QPixmap())

    # numpy / QImage 轉換
    def _to_qimage(self, img) -> QImage | None:
        if isinstance(img, QImage):
            return img

        # 假設是 numpy ndarray uint8
        #   H, W, 4: BGRA
        #   H, W, 3: BGR
        if not hasattr(img, "ndim"):
            return None

        if img.ndim == 3 and img.shape[2] == 4:
            h, w = img.shape[:2]
            if hasattr(QImage.Format, "Format_BGRA8888"):
                qimg = QImage(
                    img.data, w, h, w * 4, QImage.Format.Format_BGRA8888
                ).copy()
            else:
                rgba = img[:, :, [2, 1, 0, 3]].copy()
                qimg = QImage(
                    rgba.data, w, h, w * 4, QImage.Format.Format_RGBA8888
                ).copy()
            return qimg

        if img.ndim == 3 and img.shape[2] == 3:
            h, w = img.shape[:2]
            rgb = img[:, :, ::-1].copy()
            qimg = QImage(
                rgb.data, w, h, w * 3, QImage.Format.Format_RGB888
            ).copy()
            return qimg

        return None

    def _draw_dets(self, qimg: QImage, boxes, scores=None, cls_inds=None, conf=0.5):
        # conf 閾值從 parent 設定取得
        conf_thr = float(self.parent.args["model"]["conf"])

        p = QPainter(qimg)
        # 不需要幾何抗鋸齒，可以關掉減少 CPU（文字 antialias 仍在 on_image 畫 FPS 時開啟）
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        W, H = qimg.width(), qimg.height()
        thickness = max(2, int(min(W, H) * 0.003))

        p.setFont(self._bbox_font)
        fm = QFontMetrics(self._bbox_font)

        n = len(boxes)
        for i in range(n):
            # 信心值過濾
            if scores is not None and float(scores[i]) < conf_thr:
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

            ci = int(cls_inds[i]) if cls_inds is not None else 0
            color = self._det_colors[ci % len(self._det_colors)]

            # 外框
            p.setPen(QPen(color, thickness))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(x1, y1, x2 - x1, y2 - y1)

            # 標籤文字：預設用類別 index + score
            lbl = str(ci)
            if scores is not None:
                lbl = f"{lbl} {float(scores[i]):.2f}"

            tw = fm.horizontalAdvance(lbl) + 8
            th = fm.height() + 4
            rect = QRect(x1, max(0, y1 - th), tw, th)

            # 背板 + 文字
            bg_color = QColor(color)
            bg_color.setAlpha(160)
            p.fillRect(rect, bg_color)
            p.setPen(Qt.GlobalColor.white)
            p.drawText(
                rect.adjusted(4, 0, 0, 0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                lbl,
            )

        p.end()
