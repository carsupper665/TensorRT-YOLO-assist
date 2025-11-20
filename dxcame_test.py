import time, dxcam
from mss import mss
import numpy as np
import os


def dx_came():
    cam = dxcam.create(
        output_idx=0,
        output_color="BGRA",
    )
    w, h = 1920, 1080  # 你的螢幕解析度
    left = (w - 640) // 2
    top = (h - 640) // 2
    box = (left, top, left + 640, top + 640)
    cam.start(region=box, target_fps=240, video_mode=False)
    get = cam.get_latest_frame
    n = 0
    t0 = time.perf_counter()
    while n < 500:
        get()
        n += 1
    t = time.perf_counter() - t0
    print("Capture FPS:", n / t)
    cam.stop()


def mss_grab(box):
    with mss() as sct:
        return np.array(sct.grab(box))


def mss_came():
    w, h = 1920, 1080  # 你的螢幕解析度
    left = (w - 640) // 2
    top = (h - 640) // 2
    box = (left, top, left + 640, top + 640)
    n = 0
    t0 = time.perf_counter()
    sct = mss()
    while n < 500:
        img = sct.grab(box)
        n += 1
    t = time.perf_counter() - t0
    print("Capture FPS:", n / t)


def load_yaml(path: str) -> dict:
    import yaml

    if not os.path.exists(path):
        # copy default
        import shutil

        shutil.copy("config/default.yaml", path)
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data


if __name__ == "__main__":
    #  print("testing dxcame")
    #  dx_came()
    #  print("testing MSS")
    #  mss_came()
    cfg = load_yaml("./config/config.yaml")
    print(len(cfg))
    # for i in cfg:
    #     if isinstance(cfg[i], dict):
    #         print(f"len: {len(cfg[i])}")
    #         print(f"{i} -> {cfg[i]}")
    #     else:
    #         print(cfg[i])
    for k, i in cfg.items():
        pass
