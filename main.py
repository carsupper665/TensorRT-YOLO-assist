#./main.py
import os
import time
import dxcam
from simple_pid import PID
from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot
from utils.logger import loggerFactory, C
from utils.mouse import USBMouse
from inference import BaseEngine
from ui import SerialPortNotFound
from pynput.mouse import Button, Listener
from pynput import keyboard as KB

class Main(QObject):
    image_queue = pyqtSignal(object, object, object, object)  # img, boxes, scores, cls_inds
    on_exception = pyqtSignal(type, Exception)
    finished = pyqtSignal()
    def __init__(self, no_gui: bool = True, level: str = ""):
        self.LOGGER = loggerFactory(log_level="DEBUG", logger_name="AimSys").getLogger()
        self.running = False
        # self.LOGGER.info(f"TEST =====================")
        self.args = self.load_yaml("config/config.yaml")
        log_level = self.args.get("log_level", "WARNING")
        debug = self.args.get("debug", False)

        if debug:
            log_level = "DEBUG"
        
        if level != "":
            log_level = level

        self.LOGGER.setLevel(log_level)

        self.no_gui = no_gui

        print(f"{C['cyan']}Log level set to: {log_level}{C['r']}\n")

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
            self.LOGGER.info(f"""{C['cyan']}Welcome to use this aimbot! YOLO V8, V9, V10{C['green']}
######## ######## ######## ######## ######## ######## ######## ######## ######## ######## ######## #########
######   #        #        #   #    ######## ######   ##     # #  ###   ######## #        ##     # #       #
#####    #   ##   #   ##   #   #    ######## #####    ###   ## #   #    ######## #   ##   #        #  # #  #
####     #   ##   #   #### ##  #  # ######## ####     ###   ## #        ######## #   #  # #   #    ###   ###
###  #   #        #     ## ###   ## ######## ###  #   ###   ## #  # #   ######## #     ## #   #    ###   ###
##       #   #### #   #### ##  #  # ######## ##       ###   ## #  ###   ######## #   #  # #   #    ###   ###
#   ##   #   #### #   ##   #   #    ######## #   ##   ###   ## #  ###   ######## #   ##   #        ###   ###
   ###   #   #### #        #   #    ########    ###   ##     # #   #    ######## #        ##     # ###   ###
######## ######## ######## ######## ######## ######## ######## ######## ######## ######## ######## #########
                           ---------------------Sucsessful---------------------{C['r']}""")
        except Exception as e:
            self.LOGGER.critical(f"Error initializing all components: {e}")
            if not self.no_gui:
                self.on_exception.emit(type(e), e)

    def load_yaml(self, path: str) -> dict:
        import yaml
        if not os.path.exists(path):
            #copy default
            import shutil
            shutil.copy("config/default.yaml", path)
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data
    
    def init_camera(self):
        self.screen_width, self.screen_height = self.args.get("resolution_x", None), self.args.get("resolution_y", None)
        self.detect_length = 640
        top  = self.screen_height // 2 - self.detect_length // 2
        left = self.screen_width  // 2 - self.detect_length // 2
        self.box = (left, top, left + self.detect_length, top + self.detect_length)
        self.cam = dxcam.create(output_idx=0, output_color="BGRA")
        self.LOGGER.debug(f"Camera initialized.")

    def init_parms(self):
        self.smooth = self.args.get("mouse", None).get("smooth", None) * 1920 / self.args.get("resolution_x", None)
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
        self.pidx = PID(pidx_kp, pidx_kd, pidx_ki, setpoint=0, sample_time=0.001,)
        self.pidy = PID(pidy_kp, pidy_kd, pidy_ki, setpoint=0, sample_time=0.001,)
        self.pidx(0),self.pidy(0)
        self.detect_center_x, self.detect_center_y = self.detect_length//2, self.detect_length//2
        self.LOGGER.debug(f"Parameters initialized.")

    def init_mouse(self):
        serial_port = self.args.get("mouse", None).get("serial_port", None)

        try:
            if serial_port is None:
                raise ValueError("Serial port not specified in configuration.")
            self.m = USBMouse(serial_port)
            self.LOGGER.debug(f"Mouse initialized on port {serial_port}.")
        except Exception as e:
            raise SerialPortNotFound(f"Failed to initialize USBMouse on port {serial_port}: {e}")
        
    def init_engine(self):
        path = self.args.get("model").get("file_path")
        self.engine = BaseEngine(path)
        self.LOGGER.debug(f"Engine initialized with model at {path}.")
    
    def init_listeners(self):
        self.kb_Listener = KB.Listener(on_press=self.on_press)
        self.listener = Listener(on_click=self.on_click)

        self.toggle_aim = self.args['mouse']['switch_button']
        self.toggle_aiming = self.args['mouse']['aimbot_button']
        self.aim = False
        self.aiming = False

        self.LOGGER.debug("Input listeners initialized.")
    
    def on_press(self, key):
        self.LOGGER.debug(f"Key pressed: {key}")

    def on_click(self, x, y, button, pressed):
        self.LOGGER.debug(f"Mouse clicked at ({x}, {y}) with {button}, pressed={pressed}")
        if button == getattr(Button, self.toggle_aim):
            if pressed:
                self.aim = not self.aim
                self.LOGGER.info(f"Aimbot toggled to {'ON' if self.aim else 'OFF'}")

        if button == getattr(Button, self.toggle_aiming) and self.aim:
            self.aiming = pressed
            self.LOGGER.info(f"Aimbot aiming {'started' if pressed else 'stopped'}")

    def grab_screen(self):
        frame = self.cam.get_latest_frame()
        return frame
    
    def forward(self, ):
        is_aim = self.aim
        img = self.grab_screen()
        # if img is None:
        #     self.LOGGER.warning("No frame captured from camera.")
        #     return
        # if is_aim:
        #     boxes, confidences, classes = self.engine.forward(img)
        #     if not self.no_gui:
        #         self.image_queue.emit(img, boxes, confidences, classes)
        # else:
        #     self.image_queue.emit(img, None, None, None)
        # pass

    @pyqtSlot()
    def start(self):
        if self.running:
            self.LOGGER.warning("Already running")
            return
        self.running = True
        self.LOGGER.info("Starting main process")

        try:
            self.cam.start(region=self.box, target_fps=144)
            time.sleep(0.2) # warmup
            if self.m is None:
                self.m = USBMouse(self.args.get("mouse", None).get("serial_port", None))

            if not self.listener.is_alive() and not self.kb_Listener.is_alive():
                self.kb_Listener = self.listener = None
                self.init_listeners()
            self.kb_Listener.start()
            self.listener.start()
            if not self.cam.is_capturing:
                raise RuntimeError("Camera failed to start capturing.")
            
            while self.running:
                self.forward()
                
        except Exception as e:
            self.LOGGER.error(f"Error occurred: {e}")
            if not self.no_gui:
                self.on_exception.emit(type(e), e)
        except KeyboardInterrupt:
            self.LOGGER.info("KeyboardInterrupt received. Stopping...")
        finally:
            self.cam.stop()

            self.kb_Listener.stop()
            self.listener.stop()

            self.m.close()
            self.running = False
            self.LOGGER.info("Main process stopped")
            if not self.no_gui:
                self.LOGGER.debug("Emitting finished signal")
                self.finished.emit()

    def cleanup(self):
        if self.cam and self.cam.is_capturing:
            self.cam.stop()
        if self.kb_Listener and self.kb_Listener.running:
            self.kb_Listener.stop()
        if self.listener and self.listener.running:
            self.listener.stop()
        if self.m:
            self.m.close()
            self.m = None
        self.LOGGER.info("Cleaned up resources.")

    @pyqtSlot()
    def stop(self):
        if not self.running:
            self.LOGGER.warning("Not running")
            return
        self.running = False
        self.LOGGER.info("Stopping main process")

