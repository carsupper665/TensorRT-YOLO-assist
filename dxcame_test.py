import time, dxcam
cam = dxcam.create(output_idx=0, output_color="BGRA",)
w, h = 1920, 1080  # 你的螢幕解析度
left  = (w - 640) // 2
top   = (h - 640) // 2
box   = (left, top, left + 640, top + 640)
cam.start(region=box, target_fps=240, video_mode=False)
get = cam.get_latest_frame
n=0; t0=time.perf_counter()
while n<500:
    if get() is not None:
        n+=1
t = time.perf_counter()-t0
print("Capture FPS:", n/t)
cam.stop()
