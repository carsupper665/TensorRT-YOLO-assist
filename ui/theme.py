# ui/theme.py
# 共用色票 / 字型，新頁面統一從這裡取色，避免各檔案各自寫死 hex

BG = "#212121"
CARD_BG = "#1A1A1A"
CARD_BORDER = "#3A3A3A"
SURFACE = "#2A2A2A"  # 卡片內的次要底色 (輸入框、未選中方塊)
SURFACE_HOVER = "#333333"
BORDER_LIGHT = "#CFCFCF"

ACCENT = "#0078D4"  # 同 Windows 顯示設定的選取藍
ACCENT_HOVER = "#1A88E0"

GREEN = "#2E7D32"
GREEN_HOVER = "#388E3C"
RED = "#C62828"
RED_HOVER = "#D32F2F"
BLUE = "#1976D2"
BLUE_HOVER = "#1E88E5"
DISABLED = "#555555"

TEXT = "#E8EBF2"
TEXT_DIM = "#9E9E9E"
TEXT_WHITE = "#FFFFFF"

OK = "#4CAF50"
WARN = "#FFBD4A"

FONT = '"Source Han Sans TC", "Segoe UI", sans-serif'

# 各滑鼠模式在 OSD / 主頁上的顏色 (index = MouseMode)
MODE_COLORS = ["#FF5C5C", "#4CAF50", "#FFD54F", "#4DD0E1"]
MODE_LABELS = ["關閉", "自瞄", "抖動", "混合"]

SPINBOX_STYLE = f"""
QSpinBox {{
    background:{SURFACE}; color:{TEXT}; border:1px solid {CARD_BORDER};
    border-radius:6px; padding:3px 6px; font-family:{FONT}; font-size:13px;
}}
QSpinBox:focus {{ border:1px solid {ACCENT}; }}
"""


def button_style(base: str, hover: str, radius: int = 8, pad: str = "6px 14px", size: int = 13) -> str:
    return f"""
    QPushButton {{ background:{base}; color:white; border:none; border-radius:{radius}px;
                   padding:{pad}; font-family:{FONT}; font-size:{size}px; font-weight:600; }}
    QPushButton:hover {{ background:{hover}; }}
    QPushButton:disabled {{ background:{DISABLED}; color:#AAAAAA; }}
    """


def ghost_button_style(size: int = 12) -> str:
    return f"""
    QPushButton {{ background:{SURFACE}; color:{TEXT}; border:1px solid {CARD_BORDER};
                   border-radius:6px; padding:4px 12px; font-family:{FONT}; font-size:{size}px; }}
    QPushButton:hover {{ background:{SURFACE_HOVER}; }}
    QPushButton:disabled {{ color:{DISABLED}; }}
    """
