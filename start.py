import argparse
from main_ui import MainUI
import os, sys, pathlib

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-gui", action="store_true", help="Run without GUI")
    parser.add_argument("--trt_path", type=str, default="", help=r"Path to TensorRT (usally call C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA\\vX.X\\lib\\x64)")
    args = parser.parse_args()

    if args.trt_path:
        cuda_lib = args.trt_path
    else:
        cuda_lib = r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6\lib\x64"

    if not pathlib.Path(cuda_lib).exists():
        raise FileNotFoundError(cuda_lib)

    # 2) 讓當前行程可找到 DLL（Py3.8+ 推薦）
    if sys.platform.startswith("win"):
        os.add_dll_directory(cuda_lib)  # 不污染系統 PATH

    # 3) 需要時再動態擴充本行程 PATH（前置以較高優先）
    os.environ["PATH"] = cuda_lib + os.pathsep + os.environ.get("PATH", "")
    

    if args.no_gui:
        from main import Main

        main = Main(no_gui=True)
        main.start()
    else:
        from PyQt6.QtWidgets import QApplication
        import sys

        app = QApplication(sys.argv)
        window = MainUI()
        window.show()
        # window._clear_all()
        sys.exit(app.exec())