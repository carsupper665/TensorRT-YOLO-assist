from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, 
    QStackedWidget
)
from PyQt6.QtCore import Qt, QObject, pyqtSignal, pyqtSlot, QThread, QTimer
import sys
import os
import time
from ui import *
from logging import Logger
from pathlib import Path
import sys
from packaging.tags import sys_tags
from packaging.utils import parse_wheel_filename
from src.logger import loggerFactory, C
import json
from pprint import pformat
# from cuda import cudart
# import importlib, pkgutil, cuda

class MainUI(QMainWindow):
    startRequested = pyqtSignal()
    stopRequested = pyqtSignal()
    def __init__(self, cfg_path: str, level: str = None):
        super().__init__()
        self.args = self._load_yaml(cfg_path)
        self.cfg_path = cfg_path
        if level:
            self.args['log_level'] = level
        self.LOGGER = loggerFactory(log_level=self.args['log_level'], logger_name="MainUI").getLogger()
        self.LOGGER.info("⏳Starting up...")
        self.setObjectName(self.__class__.__name__)
        self.setWindowTitle("手殘黨")
        self.resize(16*60, 9*60)
        self.setStyleSheet("background-color: #212121;")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self.aim_sys = None  # Main instance

        self.central_widget = QWidget()

        self.main_layout = QHBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        self.toast = Toast(self)
        self.toast.fatalTriggered.connect(self._clear_all)

        try:
            self.nav_bar = NavBar(self)
            self.main_layout.addWidget(self.nav_bar)
            
            self.content_widget = QStackedWidget()
            
            self._add_pages(cfg_path)

            self.main_layout.addWidget(self.content_widget)

            self.nav_bar.tabChanged.connect(self.content_widget.setCurrentIndex)

            self.setCentralWidget(self.central_widget)

            self.nav_bar.set_disabled()

            self.LOGGER.debug("Starting up...()")
            self._run_start_up()
        except Exception as e:
            pass
            # self._on_exception(type(e), e)

    def _add_pages(self, cfg_path):
        self.loading_page = LoadingPage()
        self.home_page = HomePage(self)
        self.visualize_page = VisualizePage(self)
        self.setting_page = SettingPage(self)
        self.osd = OSD(self)
        self.osd.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        pages = [self.home_page, self.setting_page, self.visualize_page, self.loading_page]
        for page in pages:
            self.content_widget.addWidget(page)
            if page.objectName() != "LoadingPage":
                page.on_exception.connect(self._on_exception)
        self.content_widget.setCurrentIndex(len(pages)-1)
        self.visualize_page.osd_fps.connect(self.osd._on_fps)
        self.setting_page.build(self.args, cfg_path)
        
        # self.content_widget.setCurrentIndex(0)

        self.home_page.startRequested.connect(self._start_aim_sys)
        self.home_page.stopRequested.connect(self._stop_aim_sys)
        self.home_page.restartRequested.connect(self._restart_aim_sys)

        self.osd.stop_aim_sys.connect(self._stop_aim_sys)

    def _run_start_up(self):
        self.loading_thread = QThread()
        self.loading_worker = StartUp(self.LOGGER, self.args)
        self.loading_worker.moveToThread(self.loading_thread)

        self.loading_thread.started.connect(self.loading_worker.run_startup)
        self.loading_worker.progress.connect(self.loading_page.update_progress)
        self.loading_worker.res.connect(self._set_aim_sys)
        self.loading_worker._exception.connect(self._on_exception)
        self.loading_worker.finished.connect(self._start_up_finished)
        self.loading_worker.show_next_page.connect(self.content_widget.setCurrentIndex)

        self.loading_thread.start()

    def _start_up_finished(self,):
        # self.nav_bar.set_enabled()
        self.loading_thread.quit()
        self.loading_thread.wait()
        self.loading_thread = None
        self.loading_worker = None

    def _set_aim_sys(self, aim_sys: object | None, status: str = ""):
        if aim_sys is None and status == "install_package_end":
            self.toast.show_notice("info", "Rebooting App", "Packages installed. Restarting...", 5000)
            from utils.restart import restart_self
            QTimer.singleShot(5000, lambda: restart_self(self._clear_all))
            self.hide()
            return
        if status!= "success":
            self.toast.show_notice(FATAL, "Unexpected Error", UnexpectedError(), 30000)
            self.hide()
            return
        from main import Main

        if not isinstance(aim_sys, Main):
            self.toast.show_notice(FATAL, "Unexpected Error", UnexpectedError("AimSys is not initialized"), 30000)
            # self.hide()
            return
        
        self.aim_sys = Main(no_gui=False, args=self.args)
        self._prepare_worker()
        

        # self.startRequested.connect(self.aim_sys.start)
        # self.stopRequested.connect(self.aim_sys.stop)

        self.nav_bar.set_enabled()
        self.toast.show_notice(INFO, "歡迎使用", "歡迎使用手殘黨，這是一個基於TensorRT的AI輔助瞄準工具。", 
                               5000, px=self._get_x(), py=self._get_y())
        # self.home_page.set_aim_sys(aim_sys)

    def _prepare_worker(self):
        
        self.work_thread = QThread(self)
        self.aim_sys.moveToThread(self.work_thread)
        self.work_thread.started.connect(self.aim_sys.start, type=Qt.ConnectionType.QueuedConnection)

        self.aim_sys.on_exception.connect(self._on_exception)
        self.aim_sys.image_queue.connect(self.visualize_page.on_image, type=Qt.ConnectionType.QueuedConnection)
        self.aim_sys.finished.connect(self.work_thread.quit)
        self.aim_sys.finished.connect(lambda: self.home_page.set_running(False))
        self.aim_sys.finished.connect(lambda: self.osd.hide())
        self.aim_sys.on_trigger.connect(self.osd.on_trigger)

        self.aim_sys.init_all()
    
    @pyqtSlot()
    def _start_aim_sys(self):
        if self.work_thread.isRunning():
            self.LOGGER.warning("Already running")
            return
        self.home_page.set_running(True)
        self.work_thread.start()
        self.osd.show_osd()
        self.toast.show_notice(INFO, "系統啟動", "AI輔助瞄準系統已啟動。", 3000, px=self._get_x(), py=self._get_y())

    @pyqtSlot()
    def _stop_aim_sys(self):
        if self.aim_sys:
            self.aim_sys.stop()
        if self.work_thread and self.work_thread.isRunning():
            self.work_thread.quit()
            self.work_thread.wait()
            # self.work_thread.deleteLater()
        self.home_page.set_running(False)
        self.toast.show_notice(INFO, "系統停止", "AI輔助瞄準系統已停止。", 3000, px=self._get_x(), py=self._get_y())

    @pyqtSlot()
    def _restart_aim_sys(self):
        self.LOGGER.info("Restarting aim sys process...")
        try:
            self._stop_aim_sys()
            self.aim_sys.cleanup()
            del(self.aim_sys)
            self.aim_sys = None
            Main = _reload_main_class()
            self.args = self._load_yaml(self.cfg_path)
            self.aim_sys = Main(no_gui=False, args=self.cfg_path)
            self._prepare_worker()
            self.home_page.set_restart_enabled(True)
            self.toast.show_notice(INFO, "Aim Sys Restarted", "Aim Sys restarted successfully.", 3000, px=self._get_x(), py=self._get_y())
        except Exception as e:
            self._on_exception(type(e), e)
            return

    @pyqtSlot()
    def _clear_all(self):
        """Clear all resources and exit the application."""
        self.hide()
        self.LOGGER.info("Clearing all resources and exiting the application.")
        try:
            if self.aim_sys and hasattr(self.aim_sys, "stop"):
                self.aim_sys.stop()
                self.LOGGER.debug("Main process stopped successfully.")
        except Exception as e:
            self.LOGGER.error(f"Error while stopping main process: {e}")
        
        try:
            if self.loading_thread and self.loading_thread.isRunning():
                self.loading_thread.quit()
                self.loading_thread.wait()
                self.LOGGER.debug("Loading thread stopped successfully.")
        except Exception as e:
            self.LOGGER.error(f"Error while stopping loading thread: {e}")

    @pyqtSlot(type, Exception,)
    def _on_exception(self, exctype: type, e: Exception):
        self.hide()
        import traceback
        tb_text = "".join(traceback.TracebackException.from_exception(e).format())
        title ="App Crash Exception"
        print(type(e))
        from serial.serialutil import SerialException
        if isinstance(e, SerialException):
            title = "USB Device Not Found"
            
            from utils.mouse import usb_com_ports
            _, text = usb_com_ports()
            tb_text = f"{e}\n\nAvailable USB COM Ports:\n{text}\n\n{tb_text}"
        self.toast.show_notice(FATAL, title, e, 60000, traceback=tb_text)
        self.hide()
        sys.__excepthook__(exctype, e, traceback)

    def _get_x(self):
        return self.pos().x()
    
    def _get_y(self):
        return self.pos().y()
    
    def _load_yaml(self, path: str) -> dict:
        import yaml
        if not os.path.exists(path):
            #copy default
            import shutil
            shutil.copy("config/default.yaml", path)
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data

class StartUp(QObject):

    progress = pyqtSignal(dict)
    res = pyqtSignal(object, str)
    _exception = pyqtSignal(type, Exception)
    finished = pyqtSignal()
    show_next_page = pyqtSignal(int)

    def __init__(self, Logger: Logger, args: dict):
        super().__init__()
        self.logger = Logger
        self.args = args

    @pyqtSlot()
    def run_startup(self):
        next_page = None
        value = 0

        try:
            self.emit_helper("env_check", value, "Checking system environment...")
            time.sleep(2)
            res = self.env_check(value)

            #raise Here
            if (missing := res.get('missing', None)) is not None: 
                raise ModuleNotFoundError(f"Missing modules: {', '.join(missing)}")
            
            # 格式化 env_check 的回傳結果，優先用 JSON（多行），若含不可序列化物件則退到 pformat
            try:
                formatted_res = json.dumps(res, indent=2, ensure_ascii=False)
            except Exception:
                try:
                    formatted_res = pformat(res, width=120, compact=False)
                except Exception:
                    formatted_res = str(res)
            self.logger.debug("env check result:\n%s", formatted_res)
            value = 41
            self.emit_helper("init_AimSys", value, "Initializing system...")

            from main import Main
            aim_sys = Main(no_gui=False, args=self.args)
            self.res.emit(aim_sys, "success")
            
            next_page = 0
            self.emit_helper("start_up_end", None, "Startup complete.")
        except ModuleNotFoundError as me:
            value = 41
            self.logger.warning(f"ModuleNotFoundError: {me}")
            self.logger.info("Try to install missing modules and restart the application.")
            self.emit_helper("install_package", value, str(me) +"\nInstalling missing packages...")
            try:
                self._fully_install(value, res)
                value = 95
                self.res.emit(None, "install_package_end")
            except Exception as e:
                self._exception.emit(type(e), e)
        except Exception as e:
            self.emit_helper("error", value, str(e))
            self._exception.emit(type(e), e)
        finally:
            for i in range(value + 1 , 101):
                self.emit_helper("start_up_end", i, None)
                time.sleep(0.02)
            if next_page is not None:
                self.show_next_page.emit(next_page)  # 切換到主頁
            self.finished.emit()

    def emit_helper(self, id: str, value: int, status: str):
        self.progress.emit({"signalId": id, "value": value, "status": status})

    def _fully_install(self, progress_value: int, package_data: dict):
        import subprocess
        import sys
        p = progress_value
        self.emit_helper("install_package", None, "Upgrading setuptools, wheel, pip...")
        time.sleep(1)
        subprocess.check_call([sys.executable, "-s", "-m", "pip", "install", "--upgrade", "setuptools", "wheel", "pip"])
        p += 15
        self.emit_helper("install_package", p, "Installing PyTorch, It may take a while\n Depending on your network speed...")
        if package_data['modules']['torch']['err'] != '' or (not package_data['modules']['torch']['ok']):
            subprocess.check_call([sys.executable, "-s", "-m", "pip", "install", "torch", "torchvision", "torchaudio", "--index-url", "https://download.pytorch.org/whl/cu126"])
        p += 20
        self.emit_helper("install_package", p, "Installing Packages from requirements.txt")
        subprocess.check_call([sys.executable, "-s", "-m", "pip", "install", "-r", "./requirements.txt"])
        p += 15
        self.emit_helper("install_package", p, "Searching for tensorrt wheel...")
        if package_data['modules']['tensorrt']['err'] != '' or (not package_data['modules']['tensorrt']['ok']):

            wheel = pick_wheel(r".\packages")
            if not wheel:
                raise TensorRTWheelNotFound()
            self.emit_helper("install_package", p, f"Installing {wheel.name} ...")
            subprocess.check_call([sys.executable, "-s", "-m", "pip", "install", "--upgrade", str(wheel)])
        p += 5

    def _probe(self, mod: str) -> tuple[bool, str | None, object | None]:
        import importlib
        from importlib import metadata
        try:
            m = importlib.import_module(mod)           # 真的 import，避免假陽性
            try:
                ver = metadata.version(mod.split('.')[0])
                self.logger.info(f"{mod} version: {ver}")
            except metadata.PackageNotFoundError:
                ver = getattr(m, "__version__", "?")
                self.logger.warning(f"Cannot find version for {mod}, fallback to {ver}")
            return True, ver, m
        except ModuleNotFoundError as e:
            self.logger.error(f"Module {mod} not found.")
            return False, None, e
        except FileNotFoundError as fne:
            self.logger.critical(f"If nvinfer_10.dll is missing, you can set ver by using --trt_ver (your TensorRT installver) manually.")
            raise fne
        except Exception as e:
            # raise e
            return False, None, e

    def env_check(self, progress_value: int) -> dict:
        """
        回傳結果：
        {'ok': True/False, 'modules': {name: {'ok':bool,'ver':str,'err':str|None}}, 'gpu': {...}}
        並透過 emit_helper 回報進度。
        progress_value 最後為40
        """
        targets = [
            "serial", "yaml", "numpy", "cv2", "argparse", "time",
            "threading", "multiprocessing", "mss", "pynput.mouse", "pynput.keyboard",
            "simple_pid", "cuda.cudart", "tensorrt", "ctypes", "torch",
        ]

        result = {"ok": True, "modules": {}, "gpu": {}}
        step = max(1, int(40 / (len(targets) + 2)))  # +2 給 GPU 檢查
        p = progress_value

        for mod in targets:
            self.emit_helper("env_check", None, f"Checking {mod}...")
            ok, ver, err = self._probe(mod)
            p = min(40, p + step)
            msg = f"{mod} ... {'OK' if ok else 'MISSING'}"
            self.emit_helper("env_check", p, msg)
            result["modules"][mod] = {"ok": ok, "ver": ver or "", "err": "" if ok else str(err)}
            if not ok:
                result["ok"] = False

        # 進一步檢查 GPU 能力（若有安裝）
        try:
            self.logger.info(f"Checking torch cuda...")
            import torch
            result["gpu"]["torch_cuda"] = bool(torch.cuda.is_available())
            result["gpu"]["torch_device_count"] = torch.cuda.device_count() if torch.cuda.is_available() else 0
            if torch.cuda.is_available():
                result["gpu"]["torch_device0"] = torch.cuda.get_device_name(0)
        except Exception as e:
            self.logger.error(f"Error checking torch cuda: {e}")
            # raise e
            result["gpu"]["torch_cuda"] = False
            result["gpu"]["torch_err"] = str(e)

        p = min(40, p + step)
        self.emit_helper("env_check", p, "torch cuda check")

        try:
            self.logger.info(f"Checking tensorrt...")
            import tensorrt as trt
            result["gpu"]["tensorrt_ver"] = getattr(trt, "__version__", "")
            # 可選：建立 Logger 以驗證可載入
            _ = trt.Logger(trt.Logger.WARNING)
            self.logger.info(f"TensorRT version: {result['gpu']['tensorrt_ver']}")
        except Exception as e:
            self.logger.error(f"Error checking tensorrt: {e}")
            # raise e
            result["gpu"]["tensorrt_ver"] = ""
            result["gpu"]["tensorrt_err"] = str(e)
            result["ok"] = False

        p = min(100, p + step)
        self.emit_helper("env_check", p, "tensorrt check")

        # 決策：缺模組時丟一個彙總錯誤，或交給呼叫端處理
        missing = [k for k, v in result["modules"].items() if not v["ok"]]
        if missing:
            self.logger.error(f"Missing modules: {', '.join(missing)}")
            result['missing'] = missing
            return result        
        #檢查models/500e.trt 是否存在
        model_path = Path("models/500e.trt")
        if not model_path.exists():
            self.emit_helper("env_check", None, f"Model file {model_path} not found, building...\nMay take 15 minutes, depending on your system performance.")
            self.logger.warning(f"Model file {model_path} not found.")
            self.logger.info(f"{C['purple']}Building for first use, please wait...")
            self.logger.info(f"{C['purple']}It may take a {C['cyan']}15{C['purple']} minutes, depending on your system performance.{C['r']}")
            from utils.export import onnx_to_trt
            onnx_to_trt(onnx_path="models/500e.onnx", engine_path="models/500e.trt",
                         v10=True, end2end=True)
            self.logger.info(f"Model file {model_path} built successfully.")
            self.emit_helper("env_check", None, f"Model file {model_path} built successfully.\nBuilding secnond model...")
            onnx_to_trt(onnx_path="models/180e.onnx", engine_path="models/180e.trt",v10=True, end2end=True)
            

        return result


def pick_wheel(dirpath: str, name_prefix="tensorrt-10."):
    wheels = [p for p in Path(dirpath).glob("*.whl") if p.name.startswith(name_prefix)]
    if not wheels:
        return None

    # 取得當前環境支援的 tag 集合
    env_tags = {str(t) for t in sys_tags()}

    best = None
    for whl in wheels:
        dist, version, build, wheel_tags = parse_wheel_filename(whl.name)
        # 若需要也可檢查 dist == "tensorrt" and version.startswith("10.")
        # 比對是否有交集
        if env_tags.intersection({str(t) for t in wheel_tags}):
            # 選第一個符合即可；要更嚴謹可打分挑最匹配
            best = whl
            break
    return best

def _reload_main_class(module_name="main", class_name="Main"):
    import importlib
    importlib.invalidate_caches()
    mod = sys.modules.get(module_name)
    if mod is None:
        mod = importlib.import_module(module_name)   # 第一次載入
    else:
        mod = importlib.reload(mod)                  # 之後重載
    return getattr(mod, class_name)

# if __name__ == "__main__":
#     app = QApplication(sys.argv)
#     window = MainUI()
#     window.show()
#     sys.exit(app.exec())

