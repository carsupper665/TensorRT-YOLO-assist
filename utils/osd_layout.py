# utils/osd_layout.py
# OSD 位置 / 顯示器選擇的純邏輯 (不依賴 Qt，方便單元測試)
import re

CORNERS = ("top_left", "top_right", "bottom_left", "bottom_right")

DEFAULT_OSD_CFG = {
    "enabled": True,
    "monitor": "",
    "corner": "top_left",
    "offset_x": 16,
    "offset_y": 16,
}

OFFSET_MAX = 2000

# rect / size 都用 tuple: rect=(x, y, w, h), size=(w, h)


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def normalize_osd_cfg(cfg) -> dict:
    """補上預設值並修正非法值，回傳新的 dict。"""
    out = dict(DEFAULT_OSD_CFG)
    if isinstance(cfg, dict):
        out.update({k: v for k, v in cfg.items() if k in DEFAULT_OSD_CFG})

    out["enabled"] = bool(out["enabled"])
    out["monitor"] = "" if out["monitor"] is None else str(out["monitor"])
    if out["corner"] not in CORNERS:
        out["corner"] = DEFAULT_OSD_CFG["corner"]
    for k in ("offset_x", "offset_y"):
        try:
            out[k] = _clamp(int(out[k]), 0, OFFSET_MAX)
        except (TypeError, ValueError):
            out[k] = DEFAULT_OSD_CFG[k]
    return out


def compute_osd_pos(screen_rect, osd_size, corner, ox, oy) -> tuple[int, int]:
    """依角落 + 偏移算出 OSD 左上角座標，並保證整塊 OSD 留在螢幕內。"""
    sx, sy, sw, sh = screen_rect
    w, h = osd_size

    if corner in ("top_right", "bottom_right"):
        x = sx + sw - w - ox
    else:
        x = sx + ox
    if corner in ("bottom_left", "bottom_right"):
        y = sy + sh - h - oy
    else:
        y = sy + oy

    # OSD 比螢幕大時以左上角對齊
    x = _clamp(x, sx, max(sx, sx + sw - w))
    y = _clamp(y, sy, max(sy, sy + sh - h))
    return int(x), int(y)


def resolve_monitor(saved: str, available: list, current: str | None):
    """
    回傳 (要使用的顯示器名稱, 是否與設定不同需要存檔)。
    saved 不存在 -> fallback 到 current，current 也不存在 -> 第一個可用顯示器。
    """
    if not available:
        return saved, False
    if saved in available:
        return saved, False
    if current in available:
        return current, True
    return available[0], True


def monitor_number(name: str, idx: int) -> int:
    """從 '\\\\.\\DISPLAY2' 取出 2；取不到就用 idx+1。"""
    m = re.search(r"(\d+)\s*$", name or "")
    if m:
        return int(m.group(1))
    return idx + 1


def display_numbers(ids: list, primary: str | None) -> dict:
    """
    排列圖上的編號：主顯示器為 1，其餘依裝置編號 (DISPLAYn 的 n) 排序接著編。
    (Windows 設定裡的編號無法直接取得，這樣與常見情況一致。)
    """
    rest = sorted(
        (i for i in ids if i != primary),
        key=lambda name: monitor_number(name, ids.index(name)),
    )
    order = ([primary] if primary in ids else []) + rest
    return {name: n + 1 for n, name in enumerate(order)}


def layout_tiles(rects, w, h, margin=12, gap=4) -> list[tuple[float, float, float, float]]:
    """
    把虛擬桌面上的螢幕矩形等比縮放、置中到 (w, h) 的區域。
    gap 為相鄰螢幕之間保留的間距 (每個方塊各內縮 gap/2)。
    """
    if not rects:
        return []
    min_x = min(r[0] for r in rects)
    min_y = min(r[1] for r in rects)
    max_x = max(r[0] + r[2] for r in rects)
    max_y = max(r[1] + r[3] for r in rects)
    vw, vh = max_x - min_x, max_y - min_y
    aw, ah = max(1, w - 2 * margin), max(1, h - 2 * margin)
    scale = min(aw / vw, ah / vh)
    off_x = margin + (aw - vw * scale) / 2
    off_y = margin + (ah - vh * scale) / 2

    half = gap / 2
    out = []
    for x, y, rw, rh in rects:
        tx = off_x + (x - min_x) * scale + half
        ty = off_y + (y - min_y) * scale + half
        out.append((tx, ty, max(1.0, rw * scale - gap), max(1.0, rh * scale - gap)))
    return out
