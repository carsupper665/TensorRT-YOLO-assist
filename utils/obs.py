# def get_latest_frame(self) -> ndarray[tuple[int, ...], dtype[Any]]
import cv2

import numpy as np

from typing import Any
from utils.common import HighQualityTimer


class OBSCapture:
    def __init__(self ,w: int , h: int, id: int = 1, frame_rate: int = 60):
        self.timer = HighQualityTimer(240)
        self.camera_id = id
        self.frame_rate = frame_rate
        self.width = w
        self.height = h
        self.region = None
        self.cam = cv2.VideoCapture(id)
        if not self.cam.isOpened():
            raise RuntimeError('Failed to open camera')
        self.cam.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cam.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.cam.set(cv2.CAP_PROP_FPS, self.frame_rate)

    def start(self, region=None, target_fps: int | None = None, video_mode: bool = False):
        self.region = region
        if target_fps is not None:
            self.frame_rate = target_fps
            self.cam.set(cv2.CAP_PROP_FPS, self.frame_rate)
        return self

    def is_capturing(self) -> bool:
        return self.cam.isOpened()

    def get_latest_frame(self) -> np.ndarray[tuple[int, ...], np.dtype[Any]]:
        for _ in range(20):
            ret, frame = self.cam.read()
            if ret:
                if self.region is not None:
                    left, top, right, bottom = self.region
                    return frame[top:bottom, left:right]
                return frame
        raise RuntimeError('Failed to get latest frame')
