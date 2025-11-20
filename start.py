import argparse
import os, sys, pathlib

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    # e.x python.exe start.py --trt_ver 'v12.6' --log 'info'
    parser.add_argument("--no-gui", action="store_true", help="Run without GUI")
    parser.add_argument(
        "--trt_path",
        type=str,
        default=None,
        help=r"Path to TensorRT (usally call C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA\\vX.X\\lib\\x64)",
    )
    parser.add_argument("--trt_ver", type=str, default=None, help=r"TensorRT Ver")
    parser.add_argument("--log", type=str, default=None, help="log level")
    parser.add_argument(
        "--cfg", type=str, default="./config/config.yaml", help="config path"
    )
    args = parser.parse_args()

    if args.trt_ver or args.trt_path:
        cuda_lib = (
            f"C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA\\{args.trt_ver}\\lib\\x64"
            if args.trt_ver
            else args.trt_path
        )
    else:
        cuda_lib = r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6\lib\x64"

    if not pathlib.Path(cuda_lib).exists():
        raise FileNotFoundError(cuda_lib)

    # # 2) 讓當前行程可找到 DLL（Py3.8+ 推薦）
    # if sys.platform.startswith("win"):
    #     print(cuda_lib)
    #     os.add_dll_directory(cuda_lib)  # 不污染系統 PATH

    # 3) 需要時再動態擴充本行程 PATH（前置以較高優先）
    print("Cuda Path: ", cuda_lib)
    os.environ["PATH"] = cuda_lib + os.pathsep + os.environ.get("PATH", "")

    if args.no_gui:
        from main import Main

        main = Main(no_gui=True)
        main.start()
    else:
        from main_ui import MainUI
        from PyQt6.QtWidgets import QApplication
        import sys

        app = QApplication(sys.argv)
        window = MainUI(level=args.log, cfg_path=args.cfg)
        window.show()
        # window._clear_all()
        sys.exit(app.exec())
