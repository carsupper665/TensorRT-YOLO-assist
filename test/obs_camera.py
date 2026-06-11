import cv2
import time
from collections import deque


CAM_INDEX = 1       # 找不到就改 1 / 2 / 3
WIDTH = 1920
HEIGHT = 1080
TARGET_FPS = 240

SHOW_WINDOW_NAME = "OBS CAM + High Quality Timer"


class HighQualityTimer:
    def __init__(self, avg_size=120):
        self.start_ns = time.perf_counter_ns()
        self.last_ns = self.start_ns
        self.frame_times_ms = deque(maxlen=avg_size)
        self.frame_count = 0

    def update(self):
        now_ns = time.perf_counter_ns()

        dt_ms = (now_ns - self.last_ns) / 1_000_000.0
        elapsed_s = (now_ns - self.start_ns) / 1_000_000_000.0

        self.last_ns = now_ns
        self.frame_count += 1

        if dt_ms > 0:
            self.frame_times_ms.append(dt_ms)

        avg_ms = sum(self.frame_times_ms) / len(self.frame_times_ms) if self.frame_times_ms else 0
        fps = 1000.0 / avg_ms if avg_ms > 0 else 0

        return {
            "elapsed_s": elapsed_s,
            "dt_ms": dt_ms,
            "avg_ms": avg_ms,
            "fps": fps,
            "frame": self.frame_count,
        }


def format_time(seconds: float) -> str:
    ms = int((seconds % 1) * 1000)
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def draw_text_hq(img, text, x, y, scale=0.8):
    font = cv2.FONT_HERSHEY_SIMPLEX
    thickness = 2

    # 黑色描邊
    cv2.putText(
        img,
        text,
        (x, y),
        font,
        scale,
        (0, 0, 0),
        thickness + 4,
        cv2.LINE_AA,
    )

    # 白色文字
    cv2.putText(
        img,
        text,
        (x, y),
        font,
        scale,
        (255, 255, 255),
        thickness,
        cv2.LINE_AA,
    )


def draw_timer_panel(frame, timer_data):
    x, y = 24, 36
    line_gap = 32

    lines = [
        f"TIME  {format_time(timer_data['elapsed_s'])}",
        f"FPS   {timer_data['fps']:.2f}",
        f"FRAME {timer_data['frame']}",
        f"DT    {timer_data['dt_ms']:.3f} ms",
        f"AVG   {timer_data['avg_ms']:.3f} ms",
    ]

    # 半透明背景
    overlay = frame.copy()
    panel_w = 360
    panel_h = 170
    cv2.rectangle(overlay, (12, 12), (12 + panel_w, 12 + panel_h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.45, frame, 0.55, 0, frame)

    for i, line in enumerate(lines):
        draw_text_hq(frame, line, x, y + i * line_gap, scale=0.75)


def open_obs_camera():
    cap = cv2.VideoCapture(CAM_INDEX, cv2.CAP_DSHOW)

    if not cap.isOpened():
        raise RuntimeError(
            f"開不了 CAM_INDEX={CAM_INDEX}，把 CAM_INDEX 改成 1 / 2 / 3 試。"
        )

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, TARGET_FPS)

    # 降低 OpenCV buffer 延遲，有些裝置不一定吃這個設定
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    return cap


def main():
    cap = open_obs_camera()
    timer = HighQualityTimer()

    while True:
        ok, frame = cap.read()
        if not ok:
            print("讀取 OBS Virtual Camera 失敗")
            break

        timer_data = timer.update()
        draw_timer_panel(frame, timer_data)

        cv2.imshow(SHOW_WINDOW_NAME, frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q") or key == 27:
            break

    cap.release()
    cv2.destroyAllWindows()

def speed_test():
    cap = open_obs_camera()
    timer = HighQualityTimer()
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue

            timer_data = timer.update()
            print(timer_data, flush=True, end=" ")
    except KeyboardInterrupt:
        cap.release()
        cv2.destroyAllWindows()



if __name__ == "__main__":
    # main()
    speed_test()