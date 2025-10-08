import serial
from serial.tools import list_ports
class USBMouse:
    def __init__(self, device: str = "COM10"):
        self.serialcomm = serial.Serial(device, 115200, timeout=0.1)

    def send_mouse_move(self, dx, dy, silent=False):
        """
        給定滑鼠 X、Y 的位移量，透過 Serial 傳給 Arduino 控制滑鼠移動。
        如果 silent=True，會在命令前加上 'silent' 前綴，用於隱形瞄準模式。
        """
        # 強制轉成整數
        ix = int(dx)
        iy = int(dy)
        # 構造指令字串
        prefix = 'silent' if silent else ''
        cmd = f"{prefix}{ix}:{iy}"
        # 傳出
        self.serialcomm.write(cmd.encode())

    def close(self):
        self.serialcomm.close()

    def open(self):
        self.serialcomm.open()

def usb_com_ports():
    out = []
    text = ""
    for p in list_ports.comports():
        if (p.vid is not None) or ("USB" in (p.description or "")) or ("USB" in (p.hwid or "")):
            out.append({
                "device": p.device,          # e.g. COM3
                "desc": p.description,       # e.g. USB-SERIAL CH340
                "vid": hex(p.vid) if p.vid is not None else None,
                "pid": hex(p.pid) if p.pid is not None else None,
                "manufacturer": p.manufacturer,
                "serial_number": p.serial_number,
            })
            text += f"{p.device}: {p.description}\n"
            text += f"    VID:PID={hex(p.vid) if p.vid is not None else 'N/A'}:{hex(p.pid) if p.pid is not None else 'N/A'}\n"
            text += f"    Manufacturer: {p.manufacturer}\n"
            text += f"    Serial Number: {p.serial_number}\n"
    return out, text