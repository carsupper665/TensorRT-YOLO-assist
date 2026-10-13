# utils/mouse_mode.py
# 獨立出來，讓 UI 不用為了這幾個常數 import tensorrt
import dataclasses


@dataclasses.dataclass
class MouseMode:
    Off:    int = 0
    AimBot: int = 1
    Jitter: int = 2
    Mix:    int = 3

MODE_TO_STR = {0: "Off", 1: "AimBot", 2: "Jitter", 3: "Mix"}
