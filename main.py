# ./main.py
import sys
import os
import gc
import time
import traceback
import threading
import ctypes
from collections import deque

import dxcam
import numpy as np
from simple_pid import PID
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
from pynput.mouse import Button, Listener
from pynput import keyboard as KB

from typing import Optional, Tuple
from serial.serialutil import PortNotOpenError, SerialException
# from dxcam.dxcam import INFINITE, WAIT_FAILED Deprecated
# from dxcam.util.timer import (
#     create_high_resolution_timer,
#     set_periodic_timer,
#     wait_for_timer,
#     cancel_timer,
# )

from utils.common import MouseMode, MODE_TO_STR
from utils.logger import get_logger, C, LoggerConfig
from utils.mouse import USBMouse
from inference import BaseEngine
from utils.obs import OBSCapture

# Deprecated new ver of DxCam, delete the method "_cap" and fix the join-on-current-thread errors.
# ---------------------------------------------------------------------------
# dxcam monkey-patches — applied only when fix_dxcam_* flags are enabled
# ---------------------------------------------------------------------------
def _dxc_safe_stop(self):
    """Replace DXCamera.stop to avoid join-on-current-thread errors."""
    t = getattr(self, "_DXCamera__thread", None)
    if self.is_capturing:
        self._DXCamera__frame_available.set()
        self._DXCamera__stop_capture.set()
        if t is not None and t is not threading.current_thread() and t.is_alive():
            try:
                t.join(timeout=10)
            except RuntimeError as e:
                print(e)
    self._DXCamera__frame_buffer = None
    self._DXCamera__frame_count = 0
    self._DXCamera__frame_available.clear()
    self._DXCamera__stop_capture.clear()
    self._DXCamera__thread = None

# Deprecated new ver of DxCam, delete the method "_cap" and fix the join-on-current-thread errors.
# def _dxc_fixed_cap(
#     self, region: Tuple[int, int, int, int], target_fps: int = 60, video_mode=False
# ):
#     """Replace DXCamera.__capture to handle capture errors gracefully."""
#     if target_fps != 0:
#         period_ms = 1000 // target_fps
#         self._DXCamera__timer_handle = create_high_resolution_timer()
#         set_periodic_timer(self._DXCamera__timer_handle, period_ms)
#
#     self._DXCamera__capture_start_time = time.perf_counter()
#     capture_error = None
#
#     while not self._DXCamera__stop_capture.is_set():
#         if self._DXCamera__timer_handle:
#             res = wait_for_timer(self._DXCamera__timer_handle, INFINITE)
#             if res == WAIT_FAILED:
#                 self._DXCamera__stop_capture.set()
#                 capture_error = ctypes.WinError()
#                 continue
#         try:
#             frame = self._grab(region)
#             if frame is not None:
#                 with self._DXCamera__lock:
#                     self._DXCamera__frame_buffer[self._DXCamera__head] = frame
#                     if self._DXCamera__full:
#                         self._DXCamera__tail = (self._DXCamera__tail + 1) % self.max_buffer_len
#                     self._DXCamera__head = (self._DXCamera__head + 1) % self.max_buffer_len
#                     self._DXCamera__frame_available.set()
#                     self._DXCamera__frame_count += 1
#                     self._DXCamera__full = self._DXCamera__head == self._DXCamera__tail
#             elif video_mode:
#                 with self._DXCamera__lock:
#                     prev = self._DXCamera__frame_buffer[
#                         (self._DXCamera__head - 1) % self.max_buffer_len
#                     ]
#                     self._DXCamera__frame_buffer[self._DXCamera__head] = np.array(prev)
#                     if self._DXCamera__full:
#                         self._DXCamera__tail = (self._DXCamera__tail + 1) % self.max_buffer_len
#                     self._DXCamera__head = (self._DXCamera__head + 1) % self.max_buffer_len
#                     self._DXCamera__frame_available.set()
#                     self._DXCamera__frame_count += 1
#                     self._DXCamera__full = self._DXCamera__head == self._DXCamera__tail
#         except Exception as e:
#             print(traceback.format_exc())
#             self._DXCamera__stop_capture.set()
#             capture_error = e
#
#     if self._DXCamera__timer_handle:
#         cancel_timer(self._DXCamera__timer_handle)
#         self._DXCamera__timer_handle = None
#
#     if capture_error is not None:
#         self.is_capturing = False
#         self._DXCamera__frame_buffer = None
#         self._DXCamera__frame_count = 0
#         self._DXCamera__frame_available.clear()
#         self._DXCamera__stop_capture.clear()
#         raise capture_error
#
#     elapsed = time.perf_counter() - self._DXCamera__capture_start_time
#     print(f"Screen Capture FPS: {int(self._DXCamera__frame_count / elapsed)}")


# ---------------------------------------------------------------------------

class Main(QObject):
    image_queue = pyqtSignal(object, object, object, object)
    on_exception = pyqtSignal(type, Exception)
    finished = pyqtSignal()
    on_trigger = pyqtSignal(bool)

    def __init__(self, args: dict | str, no_gui: bool = True):
        self.running = False
        self._is_cleaned = False
        self.tick = 0
        self._scheduler_stop_event = threading.Event()
        self._cleanup_done_event = threading.Event()

        if not isinstance(args, (dict, str)):
            raise TypeError("Config must be dict or str")
        if isinstance(args, str):
            args = self.load_yaml(path=args)
        self.args = args

        # log_level has a safe default so the LoggerConfig call never hits UnboundLocalError
        log_level = self.args.get("log_level", "ERROR")
        if self.args.get("debug", False):
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

    def load_yaml(self, path: str) -> dict:
        import yaml
        import shutil

        if not os.path.exists(path):
            shutil.copy("config/default.yaml", path)
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

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
            if not self.no_gui:
                self.on_exception.emit(type(SE), SE)
        except Exception as e:
            self.LOGGER.critical(f"Error initializing all components: {e}")
            if not self.no_gui:
                self.on_exception.emit(type(e), e)

    def _rework_dxc(self):
        fix_dxcam: bool = self.args.get("fix_dxcam_error_hook", False)
        fix_dxcam_thread_join = self.args.get("fix_dxcam_thread_join", False)

        if fix_dxcam_thread_join:
            self.LOGGER.warning("This method has been Deprecated")

        if fix_dxcam:
            self.LOGGER.warning("This method has been Deprecated")

        self.cam = dxcam.create(output_idx=0, output_color="BGRA")
        self.grab_screen = self._dx_or_obs_grab_screen

    def create_obs(self):
        self.cam = OBSCapture(w=self.screen_width, h=self.screen_height, id=1)
        self.grab_screen = self._dx_or_obs_grab_screen

    def init_camera(self):
        self.cam_type = self.args.get("camera", "dxcam").lower()
        self.screen_width = self.args.get("resolution_x")
        self.screen_height = self.args.get("resolution_y")
        self.detect_length = 640

        top = self.screen_height // 2 - self.detect_length // 2
        left = self.screen_width // 2 - self.detect_length // 2
        self.box = (left, top, left + self.detect_length, top + self.detect_length)

        if self.cam_type == "dxcam":
            self._rework_dxc()
        elif self.cam_type == "obs":
            self.create_obs()
        else:
            self.grab_screen = self._mss_grab_screen

        self.LOGGER.debug(f"Camera initialized., cam type: {self.cam_type}")

    def init_parms(self):
        self._on_dxcam_reinit = False
        mouse_cfg = self.args["mouse"]
        res_x = self.args["resolution_x"]

        self.smooth = mouse_cfg["smooth"] * 1920 / res_x
        self.scale = res_x / 1920
        if "dis" in self.args:
            self.args["dis"] *= self.scale

        self.mms = 1.0 / mouse_cfg["mag"]
        self.conf = self.args["model"]["conf"]
        self.label = self.args["model"]["label_list"]
        self.enemy_label = self.args["model"]["enemy_list"]
        self.pos_factor = mouse_cfg["pos_factor"]
        self.max_lock_dis = mouse_cfg["max_lock_dis"]
        self.max_step_dis = mouse_cfg["max_step_dis"]
        self.max_pid_dis = mouse_cfg["max_pid_dis"]

        self.detect_center_x = self.detect_length // 2
        self.detect_center_y = self.detect_length // 2

        self.pidx = PID(
            mouse_cfg["pidx_kp"], mouse_cfg["pidx_kd"], mouse_cfg["pidx_ki"],
            setpoint=0, sample_time=0.001,
        )
        self.pidy = PID(
            mouse_cfg["pidy_kp"], mouse_cfg["pidy_kd"], mouse_cfg["pidy_ki"],
            setpoint=0, sample_time=0.001,
        )
        self.pidx(0)
        self.pidy(0)

        self.LOGGER.debug("Parameters initialized.")

    def init_mouse(self):
        serial_port = self.args["mouse"].get("serial_port")
        if serial_port is None:
            raise ValueError("Serial port not specified in configuration.")
        self.m = USBMouse(serial_port)
        self.LOGGER.debug(f"Mouse initialized on port {serial_port}.")
        self.current_mouse_mode = MouseMode.Off

    def init_engine(self):
        path = self.args["model"]["file_path"]
        self.engine = BaseEngine(path)
        self.LOGGER.debug(f"Engine initialized with model at {path}.")

    def init_listeners(self):
        self.down = set()
        self.kb_Listener = KB.Listener(on_press=self.on_press, on_release=self.on_release)
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

    # ------------------------------------------------------------------
    # Input handlers
    # ------------------------------------------------------------------

    def on_release(self, key):
        k = f"{key}"
        if k in self.down:
            self.down.remove(k)

    def on_press(self, key):
        k = f"{key}"
        if k not in self.down:
            self.down.add(k)

    def on_click(self, x, y, button, pressed):
        if button == getattr(Button, self.toggle_aim) and pressed:
            self.aim = not self.aim
            self.current_mouse_mode = (self.current_mouse_mode + 1) % (MouseMode.Mix + 1)
            self.LOGGER.info(
                f"Mode switch to {C['cyan']}{MODE_TO_STR[self.current_mouse_mode]}{C['r']}"
            )
            if not self.no_gui:
                self.on_trigger.emit(self.aim)

        if button == getattr(Button, self.toggle_aiming) and self.current_mouse_mode != MouseMode.Off:
            self.aiming = pressed
            self.LOGGER.info(f"Aimbot aiming {'started' if pressed else 'stopped'}")

    # ------------------------------------------------------------------
    # Screen capture
    # ------------------------------------------------------------------

    def _dx_or_obs_grab_screen(self):
        return self.cam.get_latest_frame()

    def _mss_grab_screen(self):
        return np.asarray(self.cam.grab(self.box))

    # ------------------------------------------------------------------
    # Targeting & movement
    # ------------------------------------------------------------------

    def target_list(self, boxes, confidences, classes) -> Optional[Tuple]:
        if len(boxes) == 0:
            return None

        conf_mask = confidences >= self.conf
        if not np.any(conf_mask):
            return None

        boxes = boxes[conf_mask]
        classes = classes[conf_mask]

        enemy_ids = np.array(
            [self.label.index(lbl) for lbl in self.enemy_label], dtype=classes.dtype
        )
        enemy_mask = np.isin(classes, enemy_ids)
        if not np.any(enemy_mask):
            return None

        boxes = boxes[enemy_mask]
        cx = (boxes[:, 0] + boxes[:, 2]) * 0.5
        cy = (boxes[:, 1] + boxes[:, 3]) * 0.5 - self.pos_factor * (boxes[:, 3] - boxes[:, 1])
        dx = cx - self.detect_center_x
        dy = cy - self.detect_center_y
        dis = np.hypot(dx, dy)

        ok = dis < self.max_lock_dis
        if not np.any(ok):
            return None

        sel = np.flatnonzero(ok)[np.argmin(dis[ok])]
        return cx[sel], cy[sel], dis[sel], boxes[sel]

    def get_move_dis_fast(self, cx, cy, dis) -> Tuple[float, float]:
        rel_x = (cx - self.detect_center_x) * self.smooth
        rel_y = (cy - self.detect_center_y) * self.smooth

        if dis >= self.max_step_dis:
            k = self.max_step_dis / dis
            rel_x *= k
            rel_y *= k
        elif dis <= self.max_pid_dis:
            rel_x = self.pidx(-rel_x)
            rel_y = self.pidy(-rel_y)
        return rel_x, rel_y

    def lock_target(self, T, mouse_mode: int, tick: int, s: float = 0.5):
        if not self.aiming:
            self.pidx(0)
            self.pidy(0)
            return

        jitter = [(4, 4), (-2, -1), (-3, -3)]

        if mouse_mode == MouseMode.AimBot and T is not None:
            moveto_x, moveto_y = self.get_move_dis_fast(T[0], T[1], T[2])
            self.m.send_mouse_move(moveto_x * s, moveto_y * s, False)
        elif mouse_mode == MouseMode.Jitter:
            moveto_x, moveto_y = jitter[tick]
            self.m.send_mouse_move(moveto_x, moveto_y, False)
            self.LOGGER.debug(f"MOVE {int(moveto_x)}, {int(moveto_y)}")
        elif mouse_mode == MouseMode.Mix:
            jit_x, jit_y = jitter[tick]
            moveto_x, moveto_y = (0, 0) if T is None else self.get_move_dis_fast(T[0], T[1], T[2])
            self.m.send_mouse_move(moveto_x * s + jit_x, moveto_y * s + jit_y, False)

        self.pidx(0)
        self.pidy(0)

    def silent(self, T):
        if T is None or not self.silent_aiming:
            return
        rel_x = T[0] - self.detect_center_x
        rel_y = T[1] - self.detect_center_y
        self.m.send_mouse_move(rel_x, rel_y, True)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def forward(self, tick: int = 0):
        cmm = self.current_mouse_mode
        is_silent = self.silent_aim
        img = self.grab_screen()

        if img is None:
            self.LOGGER.warning("No frame captured from camera.")
            return

        if cmm != MouseMode.Off or is_silent:
            boxes, confidences, classes = self.engine.forward(img)
            T = self.target_list(boxes, confidences, classes)
            self.lock_target(T, cmm, tick, self.mms)
            self._emit_ui_preview(img, boxes, confidences, classes)
        else:
            time.sleep(0.001)
            self._emit_ui_preview(img, None, None, None)

    # ------------------------------------------------------------------
    # Lifecycle helpers (called from start)
    # ------------------------------------------------------------------

    def _control_target_fps(self) -> float:
        args = getattr(self, "args", {})
        runtime_cfg = args.get("runtime", {}) if isinstance(args.get("runtime", {}), dict) else {}
        target_fps = args.get("control_fps", runtime_cfg.get("control_fps"))
        if target_fps is None:
            return 0.0
        try:
            target_fps = float(target_fps)
        except (TypeError, ValueError):
            return 0.0
        return max(target_fps, 0.0)

    def _ui_preview_target_fps(self) -> float:
        args = getattr(self, "args", {})
        runtime_cfg = args.get("runtime", {}) if isinstance(args.get("runtime", {}), dict) else {}
        target_fps = args.get("ui_preview_fps", runtime_cfg.get("ui_preview_fps"))
        if target_fps is None:
            return 0.0
        try:
            target_fps = float(target_fps)
        except (TypeError, ValueError):
            return 0.0
        return max(target_fps, 0.0)

    def _capture_target_fps(self) -> float:
        args = getattr(self, "args", {})
        runtime_cfg = args.get("runtime", {}) if isinstance(args.get("runtime", {}), dict) else {}
        target_fps = args.get("capture_fps", runtime_cfg.get("capture_fps", 240))
        try:
            target_fps = float(target_fps)
        except (TypeError, ValueError):
            target_fps = 240.0
        return max(target_fps, 1.0)

    def _init_runtime_scheduler(self, start_time: float | None = None):
        start_time = time.perf_counter() if start_time is None else start_time
        self._control_target_hz = self._control_target_fps()
        self._control_period_s = 1.0 / self._control_target_hz if self._control_target_hz > 0.0 else 0.0
        self._next_control_deadline = start_time + self._control_period_s
        self._scheduler_started_at = start_time
        self._control_tick_count = 0
        self._control_tick_durations = deque(maxlen=240)
        self._queue_depth_max = 0
        self._ui_emit_count = 0
        self._ui_preview_enabled = not getattr(self, "no_gui", True)
        if self._ui_preview_enabled:
            self._ui_preview_target_hz = self._ui_preview_target_fps()
            self._ui_preview_period_s = 1.0 / self._ui_preview_target_hz if self._ui_preview_target_hz > 0.0 else 0.0
            self._next_ui_emit_at = start_time
        else:
            self._ui_preview_target_hz = 0.0
            self._ui_preview_period_s = 0.0
            self._next_ui_emit_at = float("inf")
        self._scheduler_stop_event.clear()

    def _emit_ui_preview(self, img, boxes, confidences, classes, now: float | None = None) -> bool:
        if getattr(self, "no_gui", True):
            return False
        now = time.perf_counter() if now is None else now
        if not hasattr(self, "_next_ui_emit_at"):
            self._ui_preview_enabled = True
            self._ui_preview_target_hz = self._ui_preview_target_fps()
            self._ui_preview_period_s = 1.0 / self._ui_preview_target_hz if self._ui_preview_target_hz > 0.0 else 0.0
            self._next_ui_emit_at = now
            self._ui_emit_count = 0
        if self._ui_preview_period_s > 0.0 and now < self._next_ui_emit_at:
            return False
        self.image_queue.emit(img, boxes, confidences, classes)
        self._ui_emit_count += 1
        if self._ui_preview_period_s > 0.0:
            self._next_ui_emit_at = now + self._ui_preview_period_s
        return True

    def _record_control_tick(self, finished_at: float, duration_s: float):
        self._control_tick_count += 1
        self._control_tick_durations.append(max(duration_s, 0.0))
        self._queue_depth_max = max(self._queue_depth_max, 1)

    def _pace_control_loop(self, now: float | None = None):
        if getattr(self, "_control_period_s", 0.0) <= 0.0:
            return
        now = time.perf_counter() if now is None else now
        wait_s = self._next_control_deadline - now
        if wait_s > 0:
            self._scheduler_stop_event.wait(wait_s)
            self._next_control_deadline += self._control_period_s
        else:
            self._next_control_deadline = now + self._control_period_s

    def get_scheduler_status(self, now: float | None = None) -> dict:
        now = time.perf_counter() if now is None else now
        elapsed = max(now - getattr(self, "_scheduler_started_at", now), 1e-9)
        durations = list(getattr(self, "_control_tick_durations", ()))
        avg_tick_ms = (sum(durations) / len(durations) * 1000.0) if durations else 0.0
        return {
            "control_target_fps": float(getattr(self, "_control_target_hz", self._control_target_fps())),
            "control_cadence_hz": float(getattr(self, "_control_tick_count", 0) / elapsed),
            "control_tick_avg_ms": avg_tick_ms,
            "queue_depth_max": int(getattr(self, "_queue_depth_max", 0)),
            "ui_preview_enabled": bool(getattr(self, "_ui_preview_enabled", not getattr(self, "no_gui", True))),
            "ui_preview_target_fps": float(getattr(self, "_ui_preview_target_hz", 0.0 if getattr(self, "no_gui", True) else self._ui_preview_target_fps())),
            "ui_emit_cadence_hz": float(getattr(self, "_ui_emit_count", 0) / elapsed),
        }

    def _ensure_camera(self):
        """Reinitialize or start the capture device."""
        if self.cam_type == "mss":
            from mss import mss
            self.cam = mss()
            return

        if self._on_dxcam_reinit and hasattr(self, "cam"):
            self.LOGGER.warning("Rebuild DXC")
            self.cam.stop()
            self.cam.release()
            del self.cam
            gc.collect()
            self._rework_dxc()
            self._on_dxcam_reinit = False
        elif not hasattr(self, "cam"):
            gc.collect()
            self.cam = None
            self._rework_dxc()

        self.cam.start(region=self.box, target_fps=int(self._capture_target_fps()))
        time.sleep(0.3)  # warmup
        capture_status = getattr(self.cam, "is_capturing", None)
        if capture_status is not None:
            if callable(capture_status):
                capture_status = capture_status()
            if not capture_status:
                raise RuntimeError("Camera failed to start capturing.")

    def _ensure_mouse(self):
        """Reconnect USB mouse if the port is closed."""
        if self.m is None:
            self.LOGGER.info("Reconnecting USB mouse.")
            self.m = USBMouse(self.args["mouse"]["serial_port"])
        try:
            self.m.send_mouse_move(0, 0)
        except PortNotOpenError as pnoe:
            self.LOGGER.warning(
                f"{pnoe}, USB serial Port {self.args['mouse']['serial_port']} is closed."
            )
            self.m.open()

    def _ensure_listeners(self):
        """Restart input listeners if both have stopped."""
        if not self.kb_Listener.is_alive() and not self.listener.is_alive():
            self.kb_Listener = None
            self.listener = None
            self.init_listeners()
        self.kb_Listener.start()
        self.listener.start()

    @pyqtSlot()
    def start(self):
        if self.running:
            self.LOGGER.warning("Already running")
            return
        self.current_mouse_mode = MouseMode.Off
        self._is_cleaned = False
        self.running = True
        self._scheduler_stop_event.clear()
        self._cleanup_done_event.clear()
        self.LOGGER.info("Starting main process")
        try:
            self._ensure_camera()
            self._ensure_mouse()
            self._ensure_listeners()
            self._init_runtime_scheduler()

            while self.running:
                loop_started_at = time.perf_counter()
                self.tick = (self.tick + 1) % 3
                self.forward(self.tick)
                loop_finished_at = time.perf_counter()
                self._record_control_tick(loop_finished_at, loop_finished_at - loop_started_at)
                self._pace_control_loop(loop_finished_at)

        except TypeError as te:
            sys.__excepthook__(type(te), te, None)
            self.LOGGER.error(f"TypeError: {te}")
            self.LOGGER.warning("Sys Auto Stop.")
            self._on_dxcam_reinit = True
        except Exception as e:
            sys.__excepthook__(type(e), e, None)
            self.LOGGER.error(f"Error occurred: {e}")
            if not self.no_gui:
                self.LOGGER.debug("Exception transport to ui")
                self.on_exception.emit(type(e), e)
        except KeyboardInterrupt:
            self.LOGGER.info("KeyboardInterrupt received. Stopping...")
        finally:
            self.running = False
            if not self._is_cleaned:
                self.cleanup(True)
            if not self.no_gui:
                time.sleep(0.3)
                self.LOGGER.debug("Emitting finished signal")
                self.finished.emit()

    def cleanup(self, pause: bool = False):
        if self.kb_Listener and self.kb_Listener.running:
            self.kb_Listener.stop()

        if self.listener and self.listener.running:
            self.listener.stop()

        data = self.engine.get_infer_status()
        scheduler_status = self.get_scheduler_status()
        self.LOGGER.debug(f"YOLO Infer status:\nAVG ms: {data.get('avg_ms', None)}\ndt ms: {data.get('dt_ms', None)}\n"
                          f"fps: {data.get('fps', None)}\n"
                          f"total frames: {data.get('total_frames', None)}")
        self.LOGGER.debug(
            "Scheduler status:\n"
            f"target fps: {scheduler_status['control_target_fps']}\n"
            f"control cadence hz: {scheduler_status['control_cadence_hz']}\n"
            f"avg tick ms: {scheduler_status['control_tick_avg_ms']}\n"
            f"queue depth max: {scheduler_status['queue_depth_max']}"
        )
        if hasattr(self, "cam") and self.cam_type == "dxcam" and self.cam:
            self.LOGGER.debug(f"Dxcame closed status: {self.cam.is_capturing}")
            if self.cam_type == "dxcam" and self.cam.is_capturing:
                self.cam.stop()
                del self.cam
                self.LOGGER.debug("obj del self.cam")


        self.LOGGER.debug("All listener closed")

        if not pause:
            if self.m:
                self.m.close()
                self.m = None
            if self.engine is not None:
                self.engine.close()

        self._is_cleaned = True
        cleanup_done_event = getattr(self, "_cleanup_done_event", None)
        if cleanup_done_event is not None:
            cleanup_done_event.set()
        self.LOGGER.info("Cleaned up resources.")


    @pyqtSlot()
    def stop(self):
        if not self.running:
            self.LOGGER.warning("Not running")
            self.finished.emit()
            return
        self.running = False
        self._scheduler_stop_event.set()
        self.LOGGER.info("Stopping main process")
        t = threading.Thread(target=self._interruption_when_time_out)
        t.start()

    def _interruption_when_time_out(self):
        time_out = 10
        wait_interval_s = 0.05
        start_time = time.time()
        cleanup_done_event = getattr(self, "_cleanup_done_event", None)
        while time.time() - start_time <= time_out:
            if self._is_cleaned:
                break
            if cleanup_done_event is not None and cleanup_done_event.wait(wait_interval_s):
                break
            if cleanup_done_event is None:
                time.sleep(wait_interval_s)

        if not self._is_cleaned:
            self.LOGGER.warning("Thread request Interruption")
            self.cleanup(True)
            if not self.no_gui:
                self.LOGGER.debug("Emitting finished signal")
                self.finished.emit()
