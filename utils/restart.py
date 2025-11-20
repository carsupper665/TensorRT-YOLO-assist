# utils/restart.py
from __future__ import annotations
import sys
from typing import Callable, Optional
from PyQt6.QtCore import QCoreApplication, QProcess


def restart_self(before_quit: Optional[Callable[[], None]] = None) -> None:
    """以目前參數啟動新行程，並結束本程式。
    - 在 CPython 與 PyInstaller 打包環境皆可用。
    - 若提供 before_quit，會先呼叫以做清理。
    """
    try:
        if callable(before_quit):
            before_quit()
    except Exception:
        # 清理失敗不阻擋重啟
        pass

    # 以目前的可執行檔與參數啟動分離行程
    QProcess.startDetached(sys.executable, sys.argv)

    # 結束本行程
    QCoreApplication.quit()
