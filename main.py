# ./main.py
import sys
import os
import time
import dxcam
import numpy as np
import threading, queue
from typing import Tuple
from simple_pid import PID
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
from utils.logger import get_logger, C, LoggerConfig
from utils.mouse import USBMouse
from inference import BaseEngine
from pynput.mouse import Button, Listener
from pynput import keyboard as KB

import ctypes
from dxcam.dxcam import INFINITE, WAIT_FAILED
from serial.serialutil import PortNotOpenError, SerialException
from dxcam.util.timer import (
    create_high_resolution_timer,
    set_periodic_timer,
    wait_for_timer,
    cancel_timer,
)

def safe_stop(self, ):
    t = getattr(self, "_DXCamera__thread", None)
    if self.is_capturing:
            self._DXCamera__frame_available.set()
            self._DXCamera__stop_capture.set()
            if (
                t is not None
                and t is not threading.current_thread()
                and t.is_alive()):
                try:
                    t.join(timeout=10)
                except RuntimeError as e:
                    print(e)
    self._DXCamera__frame_buffer = None
    self._DXCamera__frame_count = 0
    self._DXCamera__frame_available.clear()
    self._DXCamera__stop_capture.clear()
    self._DXCamera__thread = None

def fixed_cap(
    self, region: Tuple[int, int, int, int], target_fps: int = 60, video_mode=False
):
    if target_fps != 0:
        period_ms = 1000 // target_fps  # millisenonds for periodic timer
        self._DXCamera__timer_handle = create_high_resolution_timer()
        set_periodic_timer(self._DXCamera__timer_handle, period_ms)

    self._DXCamera__capture_start_time = time.perf_counter()

    capture_error = None

    while not self._DXCamera__stop_capture.is_set():
        if self._DXCamera__timer_handle:
            res = wait_for_timer(self._DXCamera__timer_handle, INFINITE)
            if res == WAIT_FAILED:
                self.__stop_capture.set()
                capture_error = ctypes.WinError()
                continue
        try:
            frame = self._grab(region)
            if frame is not None:
                with self._DXCamera__lock:
                    self._DXCamera__frame_buffer[self._DXCamera__head] = frame
                    if self._DXCamera__full:
                        self._DXCamera__tail = (
                            self._DXCamera__tail + 1
                        ) % self.max_buffer_len
                    self._DXCamera__head = (
                        self._DXCamera__head + 1
                    ) % self.max_buffer_len
                    self._DXCamera__frame_available.set()
                    self._DXCamera__frame_count += 1
                    self._DXCamera__full = self._DXCamera__head == self._DXCamera__tail
            elif video_mode:
                with self.__lock:
                    self._DXCamera__frame_buffer[self._DXCamera__head] = np.array(
                        self._DXCamera__frame_buffer[
                            (self._DXCamera__head - 1) % self.max_buffer_len
                        ]
                    )
                    if self._DXCamera__full:
                        self._DXCamera__tail = (
                            self._DXCamera__tail + 1
                        ) % self.max_buffer_len
                    self._DXCamera__head = (
                        self._DXCamera__head + 1
                    ) % self.max_buffer_len
                    self._DXCamera__frame_available.set()
                    self._DXCamera__frame_count += 1
                    self._DXCamera__full = self._DXCamera__head == self._DXCamera__tail
        except Exception as e:
            import traceback

            print(traceback.format_exc())
            self._DXCamera__stop_capture.set()
            capture_error = e
            continue
    if self._DXCamera__timer_handle:
        cancel_timer(self._DXCamera__timer_handle)
        self._DXCamera__timer_handle = None
    if capture_error is not None:
        # _safe_stop
        if self.is_capturing:
            self._DXCamera__frame_available.set()
            self._DXCamera__stop_capture.set()
            t = getattr(self, "_DXCamera__thread", None)
            if t is not None and threading.current_thread() is not t:
                t.join(timeout=10)
        self.is_capturing = False
        self._DXCamera__frame_buffer = None
        self._DXCamera__frame_count = 0
        self._DXCamera__frame_available.clear()
        self._DXCamera__stop_capture.clear()
        raise capture_error
    print(
        f"Screen Capture FPS: {int(self._DXCamera__frame_count / (time.perf_counter() - self._DXCamera__capture_start_time))}"
    )


class Main(QObject):
    image_queue = pyqtSignal(
        object, object, object, object
    )  # img, boxes, scores, cls_inds
    on_exception = pyqtSignal(type, Exception)
    finished = pyqtSignal()
    on_trigger = pyqtSignal(bool)

    def __init__(self, args: dict | str, no_gui: bool = True):
        self.running = False
        self._is_cleaned = False # 管理線程狀態

        if not isinstance(args, dict) and not isinstance(args, str):
            raise TypeError("Config most be dict or str")
        if isinstance(args, dict):
            self.args = args

        if isinstance(args, str):
            self.args = self.load_yaml(path=args)

        if (l := self.args.get("log_level", None)) is not None:
            log_level = l

        if self.args["debug"]:
            log_level = "DEBUG"
        cfg = LoggerConfig(name="AimSys", level=log_level)
        self.LOGGER = get_logger(cfg)

        self.no_gui = no_gui

        self.LOGGER.info(f"{C['cyan']}Log level set to: {log_level}{C['r']}\n")

        self.LOGGER.debug(f"Arguments: {self.args}, NO GUI: {no_gui}")

        if not self.no_gui:
            super().__init__(parent=None)

            self.LOGGER.debug("Start by Main Ui Thread")
        else:
            self.init_all()

    def init_all(self):
        try:
            self.init_camera()
            self.init_parms()
            self.init_mouse()
            self.init_engine()
            self.init_listeners()

            self.LOGGER.info("All components initialized successfully. (•̀ᴗ•́)و")
            self.LOGGER.info(f"""{C["cyan"]}Welcome to use this aimbot! YOLO V8, V9, V10{C["green"]}
######## ######## ######## ######## ######## ######## ######## ######## ######## ######## ######## #########
######   #        #        #   #    ######## ######   ##     # #  ###   ######## #        ##     # #       #
#####    #   ##   #   ##   #   #    ######## #####    ###   ## #   #    ######## #   ##   #        #  # #  #
####     #   ##   #   #### ##  #  # ######## ####     ###   ## #        ######## #   #  # #   #    ###   ###
###  #   #        #     ## ###   ## ######## ###  #   ###   ## #  # #   ######## #     ## #   #    ###   ###
##       #   #### #   #### ##  #  # ######## ##       ###   ## #  ###   ######## #   #  # #   #    ###   ###
#   ##   #   #### #   ##   #   #    ######## #   ##   ###   ## #  ###   ######## #   ##   #        ###   ###
   ###   #   #### #        #   #    ########    ###   ##     # #   #    ######## #        ##     # ###   ###
######## ######## ######## ######## ######## ######## ######## ######## ######## ######## ######## #########
                           ---------------------Sucsessful---------------------{C["r"]}""")
        except SerialException as SE:
            # se = SerialPortNotFound(cause=SE)
            if not self.no_gui:
                self.on_exception.emit(type(SE), SE)
        except Exception as e:
            self.LOGGER.critical(f"Error initializing all components: {e}")
            if not self.no_gui:
                self.on_exception.emit(type(e), e)

    def load_yaml(self, path: str) -> dict:
        import yaml

        if not os.path.exists(path):
            # copy default
            import shutil

            shutil.copy("config/default.yaml", path)
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data

    def _rework_dxc(self):
        fix_dxcam: bool = self.args.get("fix_dxcam_error_hook", False)
        fix_dxcam_thread_join = self.args.get("fix_dxcam_thread_join", False)

        if fix_dxcam_thread_join:
            self.LOGGER.warning(f"Using fix_dxcam_thread_join: {fix_dxcam_thread_join}")
            dxcam.DXCamera.stop = safe_stop

        self.cam = None

        if fix_dxcam: 
            self.LOGGER.warning(f"Using fix_dxcam_error_hook: {fix_dxcam}")
            DXC = dxcam
            org_cap = DXC.DXCamera._DXCamera__capture
            DXC.DXCamera._DXCamera__capture = fixed_cap
            self.cam = DXC.create(output_idx=0, output_color="BGRA")
        else:
            self.cam = dxcam.create(output_idx=0, output_color="BGRA")

        self.grab_screen = self._dx_grab_screen

    def init_camera(self):
        self.cam_type = self.args.get("camera", "dxcam")
        self.screen_width, self.screen_height = (
            self.args.get("resolution_x", None),
            self.args.get("resolution_y", None),
        )
        self.detect_length = 640
        top = self.screen_height // 2 - self.detect_length // 2
        left = self.screen_width // 2 - self.detect_length // 2
        self.box = (left, top, left + self.detect_length, top + self.detect_length)

        if self.cam_type == "dxcam":
            self._rework_dxc()

        else:
            self.grab_screen = self._mss_grab_screen

        self.LOGGER.debug(f"Camera initialized., cam type: {self.cam_type}")

    def init_parms(self):
        self._on_dxcam_reinit = False
        self.smooth = (
            self.args.get("mouse", None).get("smooth", None)
            * 1920
            / self.args.get("resolution_x", None)
        )
        self.scale = self.args.get("resolution_x", None) / 1920
        for key, _ in self.args.items():
            if "dis" == key:
                self.args[key] *= self.scale
        pidx_kp = self.args.get("mouse", None).get("pidx_kp", None)
        pidx_kd = self.args.get("mouse", None).get("pidx_kd", None)
        pidx_ki = self.args.get("mouse", None).get("pidx_ki", None)
        pidy_kp = self.args.get("mouse", None).get("pidy_kp", None)
        pidy_kd = self.args.get("mouse", None).get("pidy_kd", None)
        pidy_ki = self.args.get("mouse", None).get("pidy_ki", None)
        self.mms = 1 / self.args["mouse"]["mag"]
        self.pidx = PID(
            pidx_kp,
            pidx_kd,
            pidx_ki,
            setpoint=0,
            sample_time=0.001,
        )
        self.pidy = PID(
            pidy_kp,
            pidy_kd,
            pidy_ki,
            setpoint=0,
            sample_time=0.001,
        )
        self.pidx(0), self.pidy(0)
        self.conf = self.args["model"]["conf"]
        self.label = self.args["model"]["label_list"]
        self.enemy_label = self.args["model"]["enemy_list"]
        self.pos_factor = self.args["mouse"]["pos_factor"]
        self.max_lock_dis = self.args["mouse"]["max_lock_dis"]
        self.max_step_dis = self.args["mouse"]["max_step_dis"]
        self.max_pid_dis = self.args["mouse"]["max_pid_dis"]
        self.detect_center_x, self.detect_center_y = (
            self.detect_length // 2,
            self.detect_length // 2,
        )
        self.LOGGER.debug(f"Parameters initialized.")

    def init_mouse(self):
        serial_port = self.args.get("mouse", None).get("serial_port", None)

        if serial_port is None:
            raise ValueError("Serial port not specified in configuration.")
        self.m = USBMouse(serial_port)
        self.LOGGER.debug(f"Mouse initialized on port {serial_port}.")

    def init_engine(self):
        path = self.args.get("model").get("file_path")
        self.engine = BaseEngine(path)
        self.LOGGER.debug(f"Engine initialized with model at {path}.")

    def init_listeners(self):
        self.down = set()
        self.kb_Listener = KB.Listener(
            on_press=self.on_press, on_release=self.on_release
        )
        self.listener = Listener(on_click=self.on_click)

        self.toggle_aim = self.args["mouse"]["switch_button"]
        self.toggle_aiming = self.args["mouse"]["aimbot_button"]
        self.toggle_silent = self.args["mouse"]["silent_button"]
        self.silent_aim_btn = self.args["mouse"]["silent_aim"]
        self.aim = False
        self.aiming = False
        self.silent_aim = False
        self.silent_aiming = False

        self.LOGGER.debug("Input listeners initialized.")

    def on_release(self, key):
        k = f"{key}"
        # self.LOGGER.debug(f"Key released: {key}")
        # if key == getattr(KB.Key, self.toggle_silent):
        #     self.silent_aim = not self.silent_aim
        #     self.LOGGER.info(f"silent aim {'ON' if self.silent_aim else 'OFF'}")

        # if k == "Key." + self.silent_aim_btn or k == self.silent_aim_btn:
        #     self.silent_aiming = not self.silent_aiming
        #     self.LOGGER.info(f"silent Shoot {'ON' if self.silent_aiming else 'OFF'}")

        if k in self.down:
            self.down.remove(k)

    def on_press(self, key):
        k = f"{key}"
        if k in self.down:
            return  # 忽略重複 press
        self.down.add(f"{k}")
        # if k == "Key." + self.silent_aim_btn or k == self.silent_aim_btn:
        #     self.silent_aiming = not self.silent_aiming
        #     self.LOGGER.info(f"silent Shoot {'ON' if self.silent_aiming else 'OFF'}")
        # self.LOGGER.debug(f"Key pressed: {key}")

    def on_click(self, x, y, button, pressed):
        # self.LOGGER.debug(
        #     f"Mouse clicked at ({x}, {y}) with {button}, pressed={pressed}"
        # )
        if button == getattr(Button, self.toggle_aim):
            if pressed:
                self.aim = not self.aim
                self.LOGGER.info(
                    f"{C['green'] if self.aim else C['red']}Aimbot toggled to {'ON' if self.aim else 'OFF'}"
                )
                if not self.no_gui:
                    self.on_trigger.emit(self.aim)

        if button == getattr(Button, self.toggle_aiming) and self.aim:
            self.aiming = pressed
            self.LOGGER.info(f"Aimbot aiming {'started' if pressed else 'stopped'}")

    # def grab_screen(self):
    #     return self.cam.get_latest_frame()

    def _dx_grab_screen(self):
        return self.cam.get_latest_frame()

    def _mss_grab_screen(self):
        return np.asarray(self.cam.grab(self.box))

    def target_list(self, boxes, confidences, classes):
        # boxes: Nx4, confidences: N, classes: N
        if len(boxes) == 0:
            return None

        conf_mask = confidences >= self.conf
        if not np.any(conf_mask):
            return None

        boxes = boxes[conf_mask]
        classes = classes[conf_mask]

        # 過濾敵對類別
        enemy_ids = np.array(
            [self.label.index(lbl) for lbl in self.enemy_label], dtype=classes.dtype
        )
        enemy_mask = np.isin(classes, enemy_ids)
        if not np.any(enemy_mask):
            return None

        boxes = boxes[enemy_mask]
        # 中心點與準星距離
        cx = (boxes[:, 0] + boxes[:, 2]) * 0.5
        cy = (boxes[:, 1] + boxes[:, 3]) * 0.5 - self.pos_factor * (
            boxes[:, 3] - boxes[:, 1]
        )
        dx = cx - self.detect_center_x
        dy = cy - self.detect_center_y
        dis = np.hypot(dx, dy)

        # 距離門檻
        ok = dis < self.max_lock_dis
        if not np.any(ok):
            return None

        # 取最近者
        idx = np.argmin(dis[ok])
        # 回傳最近者
        sel = np.flatnonzero(ok)[idx]
        return cx[sel], cy[sel], dis[sel], boxes[sel]

    def get_move_dis_fast(self, cx, cy, dis):
        rel_x = (cx - self.detect_center_x) * self.smooth
        rel_y = (cy - self.detect_center_y) * self.smooth

        if dis >= self.max_step_dis:
            k = self.max_step_dis / dis
            rel_x *= k
            rel_y *= k
        elif dis <= self.max_pid_dis:
            # 直接用誤差，不再 atan2
            rel_x = self.pidx(-rel_x)
            rel_y = self.pidy(-rel_y)
            # rel_x = self.pidx(atan2(-rel_x, self.detect_length))
            # rel_y = self.pidy(atan2(-rel_y, self.detect_length))
        return rel_x, rel_y

    def lock_target(self, T, s=0.5):
        if T is None or not self.aiming:
            self.pidx(0)
            self.pidy(0)
            return

        moveto_x, moveto_y = self.get_move_dis_fast(T[0], T[1], T[2])

        self.m.send_mouse_move(moveto_x * s, moveto_y * s, False)
        # self.LOGGER.debug(f"MOVE {int(moveto_x*s)}, {int(moveto_y*s)}")

        self.pidx(0)
        self.pidy(0)

    def silent(self, T):
        if T is None or not self.silent_aiming:
            return

        rel_x = T[0] - self.detect_center_x
        rel_y = T[1] - self.detect_center_y
        self.m.send_mouse_move(rel_x, rel_y, True)

    def forward(
        self,
    ):
        is_aim = self.aim
        is_silent = self.silent_aim
        img = self.grab_screen()

        if img is None:
            self.LOGGER.warning("No frame captured from camera.")
            return

        if is_aim or is_silent:
            boxes, confidences, classes = self.engine.forward(img)
            T = self.target_list(boxes, confidences, classes)
            if is_aim:
                self.lock_target(T, self.mms)

            # if is_silent:
            #     self.silent(T)

            if not self.no_gui:
                self.image_queue.emit(
                    img,
                    boxes,
                    confidences,
                    classes,
                )
        else:
            time.sleep(0.001)
            if not self.no_gui:
                self.image_queue.emit(
                    img,
                    None,
                    None,
                    None,
                )

    @pyqtSlot()
    def start(self):
        if self.running:
            self.LOGGER.warning("Already running")
            return
        self._is_cleaned = False
        self.running = True
        self.LOGGER.info("Starting main process")
        try:
            if self.cam_type == "dxcam":
                import gc
                if self._on_dxcam_reinit and hasattr(self, "cam"):

                    self.LOGGER.warning(f"Rebuild DXC")
                    self.cam.stop()
                    self.cam.release()
                    self.cam.__del__()
                    del self.cam
                    gc.collect()
                    # self.cam = None
                    self._rework_dxc()
                    self._on_dxcam_reinit = False
                elif not hasattr(self, "cam"):
                    gc.collect()
                    self.cam = None
                    self._rework_dxc()

                self.cam.start(region=self.box, target_fps=240)
                time.sleep(0.3)  # warmup
                if not self.cam.is_capturing:
                    raise RuntimeError("Camera failed to start capturing.")
            else:
                from mss import mss

                self.cam = mss()

            if self.m is None:
                self.LOGGER.info("reconnect USB.")
                self.m = USBMouse(self.args.get("mouse", None).get("serial_port", None))
            try:
                self.m.send_mouse_move(0, 0)
            except PortNotOpenError as pnoe:
                self.LOGGER.warning(
                    f"{pnoe}, USB serial Port {self.args['mouse']['serial_port']} is close."
                )
                self.m.open()
            except Exception as e:
                raise e

            # if self.engine is None:
            #     self.init_engine()

            if not self.listener.is_alive() and not self.kb_Listener.is_alive():
                self.kb_Listener = self.listener = None
                self.init_listeners()
            self.kb_Listener.start()
            self.listener.start()

            while self.running:
                self.forward()

        except TypeError as te:
            sys.__excepthook__(type(te), te, None)
            if str(te) == "'NoneType' object is not subscriptable":
                self.LOGGER.error(f"TypeError: {te}")
            self.LOGGER.warning(f"Sys Auto Stop.")
            self._on_dxcam_reinit = True
        except Exception as e:
            sys.__excepthook__(type(e), e, None)
            self.LOGGER.error(f"Error occurred: {e}")
            if not self.no_gui:
                self.on_exception.emit(type(e), e)
        except KeyboardInterrupt:
            self.LOGGER.info("KeyboardInterrupt received. Stopping...")
        finally:
            self.running = False

            if not self._is_cleaned:
                self.cleanup(True)

            if not self.no_gui:
                time.sleep(0.3)  # wait ui
                self.LOGGER.debug("Emitting finished signal")
                self.finished.emit()

    def cleanup(self, pause: bool = False):
        if hasattr(self, "cam"):
            if self.cam:
                self.LOGGER.debug(f"Dxcame closed status: {self.cam.is_capturing}")

                if self.cam_type == "dxcam" and self.cam.is_capturing:
                    self.cam.stop()
                    del self.cam
                    self.LOGGER.debug("obj del self.cam")

        if self.kb_Listener and self.kb_Listener.running:
            self.kb_Listener.stop()

        if self.listener and self.listener.running:
            self.listener.stop()

        self.LOGGER.debug("All listener closed")

        if not pause:
            if self.m:
                self.m.close()
                self.m = None
                del self.m

            if self.engine:
                self.engine.close()

        self._is_cleaned = True
        self.LOGGER.info("Cleaned up resources.")

    @pyqtSlot()
    def stop(self):
        if not self.running:
            self.LOGGER.warning("Not running")
            self.finished.emit()
            return
        self.running = False
        self.LOGGER.info("Stopping main process")
        t = threading.Thread(target=self._interruption_when_time_out)
        t.start()
        # t.join()

    def timer(self, time_out: int):
        start_time = time.time()
        while time.time() - start_time <= time_out:
            if self._is_cleaned:
                break
            time.sleep(0.001)

    def _interruption_when_time_out(self):
        time_out = 10 #s
        self.timer(time_out)

        if not self._is_cleaned: # 當機了 沒有成功清除
            self.LOGGER.warning(f"thread request Interruption")
            self.cleanup(True)
            if not self.no_gui:
                # time.sleep(0.3)  # wait ui
                self.LOGGER.debug("Emitting finished signal")
                self.finished.emit()

