from __future__ import annotations
import logging
from logging import Handler
from logging.handlers import RotatingFileHandler
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime
import sys
from typing import Dict, Optional

# ANSI palette
C: Dict[str, str] = {
    "red": "\033[91m", "green": "\033[92m", "blue": "\033[94m",
    "yellow": "\033[93m", "cyan": "\033[96m", "magenta": "\033[95m",
    "black": "\033[30m", "white": "\033[97m", "gray": "\033[37m",
    "bg_red": "\033[41m", "bg_green": "\033[42m", "bg_blue": "\033[44m",
    "bg_yellow": "\033[43m", "bg_cyan": "\033[46m", "bg_magenta": "\033[45m",
    "bg_black": "\033[40m", "bg_white": "\033[47m",
    "r": "\033[0m",
}

@dataclass
class LoggerConfig:
    name: str = "main"
    level: int | str = logging.DEBUG
    to_file: bool = False
    file_dir: Path = Path("./logs")
    file_name: str = "app"
    static_file_name: bool = False          
    rotate: bool = True             
    max_bytes: int = 2 * 1024 * 1024
    backup_count: int = 3
    use_color: Optional[bool] = None  # None=自動偵測 TTY
    datefmt: str = "%Y-%m-%d %H:%M:%S"

    level_formats: Dict[int, str] = field(default_factory=lambda: {
        logging.DEBUG:    f"%(asctime)s [%(name)s] {C['cyan']}[DEBUG]{C['r']}    | %(message)s",
        logging.INFO:     f"%(asctime)s [%(name)s] {C['green']}[INFO]{C['r']}     | %(message)s",
        logging.WARNING:  f"%(asctime)s [%(name)s] {C['yellow']}[WARNING]{C['r']}  | %(message)s",
        logging.ERROR:    f"%(asctime)s [%(name)s] {C['red']}[ERROR]{C['r']}    | %(message)s",
        logging.CRITICAL: f"%(asctime)s [%(name)s] {C['bg_red']}{C['white']}[CRITICAL]{C['r']} | %(message)s",
    })

    # 檔案寫入不含 ANSI
    file_format: str = "%(asctime)s [%(name)s] [%(levelname)s] | %(message)s"

def _normalize_level(level: int | str) -> int:
    if isinstance(level, int):
        return level
    if isinstance(level, str):
        lvl = logging.getLevelName(level.upper())
        # getLevelName 回傳 str 時代表不合法
        if isinstance(lvl, int):
            return lvl
    return logging.INFO

# -------- formatters --------
class LevelFormatter(logging.Formatter):
    """依 level 套用不同格式。"""
    def __init__(self, fmt_map: Dict[int, str], datefmt: Optional[str] = None):
        super().__init__(datefmt=datefmt)
        self.fmt_map = fmt_map
        self.default = "%(levelname)s: %(message)s"
        self.datefmt = datefmt

    def format(self, record: logging.LogRecord) -> str:
        fmt = self.fmt_map.get(record.levelno, self.default)
        return logging.Formatter(fmt=fmt, datefmt=self.datefmt).format(record)

# -------- factory --------
def get_logger(cfg: LoggerConfig) -> logging.Logger:
    lvl = _normalize_level(cfg.level)
    logger = logging.getLogger(cfg.name)
    logger.setLevel(lvl)
    logger.propagate = False  # 避免傳到 root 重複輸出

    if getattr(logger, "_configured", False):
        return logger

    handlers: list[Handler] = []

    use_color = cfg.use_color if cfg.use_color is not None else sys.stdout.isatty()
    if use_color:
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(lvl)
        ch.setFormatter(LevelFormatter(cfg.level_formats, datefmt=cfg.datefmt))
        handlers.append(ch)
    else:
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(lvl)
        ch.setFormatter(logging.Formatter("%(asctime)s [%(name)s] [%(levelname)s] | %(message)s",
                                          datefmt=cfg.datefmt))
        handlers.append(ch)

    if cfg.to_file:
        cfg.file_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%y-%m-%d-%H%M%S")
        
        if cfg.static_file_name:
            file_path = cfg.file_dir / f"{cfg.file_name}.log"
                
        else:
            file_path = cfg.file_dir / f"{ts}_{cfg.file_name}.log"

        if cfg.rotate:
            fh: Handler = RotatingFileHandler(
                file_path, mode='w',maxBytes=cfg.max_bytes, backupCount=cfg.backup_count, encoding="utf-8"
            )
        else:
            fh = logging.FileHandler(file_path, mode='w',encoding="utf-8")
        fh.setLevel(lvl)
        fh.setFormatter(logging.Formatter(cfg.file_format, datefmt=cfg.datefmt))
        handlers.append(fh)

    for h in handlers:
        logger.addHandler(h)

    logger._configured = True  # 標記避免重複加 handler
    return logger

if __name__ == "__main__":
    cfg = LoggerConfig(
        name="demo",
        level="DEBUG",
        to_file=True,
        file_dir=Path("./logs"),
        file_name="demo",
        rotate=True,
    )
    log = get_logger(cfg)
    log.debug("debug")
    log.info("info ✅")
    log.warning("warning")
    log.error("error")
    log.critical("critical")