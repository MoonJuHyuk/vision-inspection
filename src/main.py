"""
=================================================
 Vision Inspection - Phase 1
 Dual-boundary thread sag detection
=================================================
"""
import cv2
import numpy as np
import os, sys, time, traceback, threading
from datetime import datetime

# ── 한글 텍스트 렌더링 (PIL) ──────────────────
try:
    from PIL import ImageFont, ImageDraw, Image as _PILImage
    _kr_font_cache = {}
    def _kfont(sz):
        if sz not in _kr_font_cache:
            _kr_font_cache[sz] = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", sz)
        return _kr_font_cache[sz]
    _PIL_OK = True
except Exception:
    _PIL_OK = False

_tq = []  # queued text: (text, x, pil_y, size, bgr)

def tq(text, x, y_cv2, size, color_bgr):
    """한글 텍스트 대기열에 추가. y_cv2 = OpenCV baseline y."""
    _tq.append((text, x, max(0, y_cv2 - size), size, color_bgr))

def flush_tq(img):
    """대기열의 텍스트를 PIL로 img에 한 번에 렌더링."""
    global _tq
    if not _tq or not _PIL_OK:
        _tq = []; return
    pil = _PILImage.fromarray(img[:, :, ::-1].copy())
    draw = ImageDraw.Draw(pil)
    for text, x, y, sz, bgr in _tq:
        draw.text((x, y), text, font=_kfont(sz), fill=(bgr[2], bgr[1], bgr[0]))
    img[:] = np.array(pil)[:, :, ::-1]
    _tq = []

# .exe(PyInstaller frozen)와 개발 환경 양쪽에서 경로가 올바르게 잡히도록
if getattr(sys, 'frozen', False):
    _BASE_DIR = os.path.dirname(sys.executable)   # .exe 위치
else:
    _BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BASE_DIR)
from config.settings import *

# 저장 경로를 실행파일 기준 절대경로로 고정
SAVE_DIR = os.path.join(_BASE_DIR, SAVE_DIR)

if ARDUINO_ENABLED or USB_RELAY_ENABLED:
    import serial

if ARDUINO_ENABLED:
    try:
        arduino = serial.Serial(ARDUINO_PORT, ARDUINO_BAUDRATE, timeout=1)
        time.sleep(2)
        print(f"[OK] Arduino: {ARDUINO_PORT}")
    except Exception as e:
        arduino = None
        print(f"[WARN] Arduino 연결 실패: {e}")
else:
    arduino = None
    print("[INFO] Arduino disabled")

# ── USB 릴레이 모듈 (Arduino 없이 경보등 직접 제어) ──
# CH340/CH341 기반 1채널 릴레이 모듈. 장치관리자에서 COM 포트 확인.
_relay = None
if USB_RELAY_ENABLED:
    try:
        _relay = serial.Serial(USB_RELAY_PORT, 9600, timeout=1)
        time.sleep(0.5)
        print(f"[OK] USB 릴레이: {USB_RELAY_PORT}")
    except Exception as e:
        _relay = None
        print(f"[WARN] USB 릴레이 연결 실패 ({USB_RELAY_PORT}): {e}")

def _relay_on():
    """경보등 켜기 (릴레이 ON)."""
    if _relay and _relay.is_open:
        try:
            _relay.write(bytes([0xA0, 0x01, 0x01, 0xA2]))
        except Exception as e:
            print(f"[WARN] 릴레이 ON 실패: {e}")

def _relay_off():
    """경보등 끄기 (릴레이 OFF)."""
    if _relay and _relay.is_open:
        try:
            _relay.write(bytes([0xA0, 0x01, 0x00, 0xA1]))
        except Exception as e:
            print(f"[WARN] 릴레이 OFF 실패: {e}")

os.makedirs(SAVE_DIR, exist_ok=True)

# ── 고정 해상도 (카메라 실제 해상도와 무관하게 이 크기로 작동) ──
FW = FRAME_WIDTH
FH = FRAME_HEIGHT

# ── UI ────────────────────────────────────────
PANEL_W  = 300
WIN_NAME = "Vision Inspection"

# 모든 색상값은 BGR 순서 (OpenCV 기본) — 산업용 HMI 팔레트
C_BG     = (18,  20,  26)   # 배경
C_PANEL  = (24,  28,  38)   # 패널
C_HDR    = (14,  16,  24)   # 헤더바
C_BORDER = (55,  65,  80)   # 테두리
C_UPPER  = (200, 200,   0)  # 시안  (위쪽선)
C_LOWER  = (  0, 155, 230)  # 주황  (아래선)
C_OK     = ( 40, 210,  55)  # 초록
C_ALARM  = ( 40,  40, 220)  # 빨강
C_WARN   = ( 20, 160, 220)  # 앰버
C_ACCENT = (170, 135,  30)  # 금색 강조
C_TEXT   = (220, 228, 240)  # 텍스트
C_DIM    = ( 80,  90, 108)  # 흐린 텍스트
C_ERROR  = ( 30,  30, 220)  # 에러 빨강

_KERNEL = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))

tb = {
    "brightness": THREAD_BRIGHTNESS,
    "min_pixels": ALARM_PIXEL_COUNT,
    "confirm":    ALARM_CONFIRM_FRAMES,
}

CANVAS_W = FW + PANEL_W
CANVAS_H = FH


# ── PC 소리 알람 ──────────────────────────────
import winsound as _ws

_snd_active = False

def _snd_loop():
    """알람 상태인 동안 경보음 반복 재생."""
    while _snd_active:
        _ws.Beep(1400, 180)
        time.sleep(0.05)
        _ws.Beep(900, 180)
        time.sleep(0.35)

def _start_alarm_sound():
    global _snd_active
    if not _snd_active:
        _snd_active = True
        threading.Thread(target=_snd_loop, daemon=True).start()

def _stop_alarm_sound():
    global _snd_active
    _snd_active = False
    # 복귀음 (짧게 한 번)
    threading.Thread(target=lambda: _ws.Beep(600, 120), daemon=True).start()


# ── Arduino 신호 ──────────────────────────────
# 프로토콜: b'R'=빨강(알람)  b'G'=초록(정상)  b'Y'=황색(기준없음/측정중)
def send_signal(status):
    # PC 소리
    if status == "ALARM":
        _start_alarm_sound()
    else:
        _stop_alarm_sound()

    # USB 릴레이 (경보등 직접 제어)
    if status == "ALARM":
        _relay_on()
    else:
        _relay_off()

    # Arduino 신호등
    if arduino:
        try:
            cmd = {
                "ALARM":        b'R',
                "NORMAL":       b'G',
                "NO_REFERENCE": b'Y',
                "MEASURING":    b'Y',
                "CAMERA_ERROR": b'Y',
            }.get(status, b'Y')
            arduino.write(cmd)
        except Exception as e:
            print(f"[WARN] Arduino signal failed: {e}")


def save_frame(frame, label="capture"):
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        path = f"{SAVE_DIR}/{label}_{ts}.jpg"
        cv2.imwrite(path, frame)
        print(f"[SAVE] {path}")
    except Exception as e:
        print(f"[WARN] Save failed: {e}")


def clamp_roi(roi):
    x1, y1, x2, y2 = roi
    x1 = max(0, min(x1, FW - 2))
    y1 = max(0, min(y1, FH - 2))
    x2 = max(x1 + 1, min(x2, FW - 1))
    y2 = max(y1 + 1, min(y2, FH - 1))
    return (x1, y1, x2, y2)


def open_cam(idx):
    for backend in (cv2.CAP_DSHOW, 0):
        c = cv2.VideoCapture(idx, backend) if backend else cv2.VideoCapture(idx)
        if not c.isOpened():
            continue
        c.set(cv2.CAP_PROP_FRAME_WIDTH,  FW)
        c.set(cv2.CAP_PROP_FRAME_HEIGHT, FH)
        c.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        time.sleep(0.5)
        for _ in range(5):
            c.read()
        ret, _ = c.read()
        if ret:
            return c
        c.release()
    return None


def auto_detect_camera():
    """USB 카메라 우선(index 1,2,3), 없으면 내장 카메라(index 0) 사용."""
    for idx in [1, 2, 3]:
        cap = open_cam(idx)
        if cap:
            print(f"[INFO] USB 카메라 감지: index {idx}")
            return cap, idx
    cap = open_cam(0)
    if cap:
        print("[INFO] 내장 카메라 사용: index 0")
        return cap, 0
    return None, -1


def draw_led(canvas, cx, cy, r, color, on=True):
    """산업용 LED 인디케이터."""
    if on:
        cv2.circle(canvas, (cx, cy), r, color, -1)
        hl = tuple(min(255, c + 90) for c in color)
        cv2.circle(canvas, (cx - r//3, cy - r//3), max(1, r//3), hl, -1)
    else:
        dark = tuple(c // 6 for c in color)
        cv2.circle(canvas, (cx, cy), r, dark, -1)
    rim = tuple(min(255, c + 40) for c in color)
    cv2.circle(canvas, (cx, cy), r, rim, 1)


def draw_corner_marks(img, x1, y1, x2, y2, color, sz=18, th=2):
    """ROI 모서리 타깃 마크."""
    for (ax, ay, dx, dy) in [(x1,y1,1,1),(x2,y1,-1,1),(x1,y2,1,-1),(x2,y2,-1,-1)]:
        cv2.line(img, (ax, ay), (ax + dx*sz, ay), color, th)
        cv2.line(img, (ax, ay), (ax, ay + dy*sz), color, th)


def read_frame(cap):
    for _ in range(8):
        ret, frame = cap.read()
        if ret and frame is not None and frame.size > 0:
            if frame.shape[1] != FW or frame.shape[0] != FH:
                frame = cv2.resize(frame, (FW, FH))
            return frame
    return None


# ── Bound measurement ─────────────────────────
def measure_bounds(cap, roi, n=30, on_progress=None):
    rx1, ry1, rx2, ry2 = roi
    print(f"[INFO] Measuring bounds... ({n} frames)")
    accum, count = None, 0
    for i in range(n):
        if on_progress:
            on_progress(i + 1, n)
        frame = read_frame(cap)
        if frame is None:
            continue
        crop = frame[ry1:ry2, rx1:rx2]
        if crop.size == 0:
            continue
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        accum = gray.astype(np.float32) if accum is None else accum + gray
        count += 1
    if count == 0 or accum is None:
        return None, None, None

    avg = (accum / count).astype(np.uint8)
    _, mask = cv2.threshold(avg, tb["brightness"], 255, cv2.THRESH_BINARY_INV)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, _KERNEL)
    ref_mask = mask.copy()

    ys = np.where(mask > 0)[0]
    if len(ys) == 0:
        print("[WARN] Thread not detected - lower Brightness slider")
        return None, None, None

    roi_h = ry2 - ry1
    upper_y = max(0, int(ys.min()) - SAG_MARGIN)
    lower_y = min(roi_h - 1, int(ys.max()) + SAG_MARGIN)
    print(f"[INFO] Upper={upper_y}px  Lower={lower_y}px  (margin {SAG_MARGIN}px)")
    return upper_y, lower_y, ref_mask


# ── Detection ─────────────────────────────────
def detect(roi_gray, upper_y, lower_y, ref_mask=None):
    h = roi_gray.shape[0]
    mask = np.zeros_like(roi_gray)

    if upper_y > 0:
        bs = max(0, upper_y - DETECT_BAND)
        z = roi_gray[bs:upper_y]
        if z.size > 0:
            _, m = cv2.threshold(z, tb["brightness"], 255, cv2.THRESH_BINARY_INV)
            m = cv2.morphologyEx(m, cv2.MORPH_OPEN, _KERNEL)
            if ref_mask is not None and ref_mask[bs:upper_y].shape == m.shape:
                m = cv2.bitwise_and(m, cv2.bitwise_not(ref_mask[bs:upper_y]))
            mask[bs:upper_y] = m

    if lower_y < h - 1:
        be = min(h, lower_y + DETECT_BAND)
        z = roi_gray[lower_y:be]
        if z.size > 0:
            _, m = cv2.threshold(z, tb["brightness"], 255, cv2.THRESH_BINARY_INV)
            m = cv2.morphologyEx(m, cv2.MORPH_OPEN, _KERNEL)
            if ref_mask is not None and ref_mask[lower_y:be].shape == m.shape:
                m = cv2.bitwise_and(m, cv2.bitwise_not(ref_mask[lower_y:be]))
            mask[lower_y:be] = m

    return mask, cv2.countNonZero(mask)


# ── Sliders ───────────────────────────────────
SLIDERS = [
    {"id": "brightness", "label": "밝기 임계값", "min": 1,   "max": 254, "key": "brightness", "step": 5},
    {"id": "min_pixels", "label": "최소 픽셀",   "min": 1,   "max": 500, "key": "min_pixels",  "step": 10},
    {"id": "confirm",    "label": "확인 프레임", "min": 1,   "max": 30,  "key": "confirm",     "step": 1},
]

# ── Layout (CANVAS_H=540) ─────────────────────
#   0   –  46 : 헤더바
#  46   – 116 : 상태 블록 (LED + 상태 + 픽셀)
# 116   – 164 : 라인 정보 (위쪽선, 아래선)
# 164   – 264 : 슬라이더 3개 × 33px
# 264   – 488 : 버튼 5행 × (44+4)px = 240px
# 488   – 540 : 하단 힌트

_SL_START = 180   # slider 0 center-Y  (164 + 16)
_SL_H     = 33
_SL_PAD   = 8
_SL_LW    = 80
_SL_BTN_W = 18   # [-][+] 버튼 너비

_BTN_START = 265
_BTN_H     = 40
_BTN_M     = 4


def _slider_track(px, i):
    tx1 = px + _SL_PAD + _SL_LW
    tx2 = px + PANEL_W - _SL_PAD - (_SL_BTN_W * 2 + 30)  # [-][+] 공간 확보
    cy  = _SL_START + i * _SL_H
    return tx1, tx2, cy

def _slider_btn_rects(px, i):
    """(minus_rect, plus_rect) 각각 (x1,y1,x2,y2)."""
    _, tx2, cy = _slider_track(px, i)
    bh = 14
    mx1 = tx2 + 4
    mx2 = mx1 + _SL_BTN_W
    px1 = mx2 + _SL_BTN_W + 4
    px2 = px1 + _SL_BTN_W
    return (mx1, cy - bh, mx2, cy + bh), (px1, cy - bh, px2, cy + bh)

def hit_slider_btn(px, x, y):
    """클릭한 좌표가 [-]/[+] 버튼이면 (slider_id, delta) 반환, 아니면 None."""
    for i, sl in enumerate(SLIDERS):
        mr, pr = _slider_btn_rects(px, i)
        if mr[0] <= x <= mr[2] and mr[1] <= y <= mr[3]:
            return sl["id"], -sl["step"]
        if pr[0] <= x <= pr[2] and pr[1] <= y <= pr[3]:
            return sl["id"], +sl["step"]
    return None


def draw_sliders(canvas, px, active_id=None):
    for i, sl in enumerate(SLIDERS):
        tx1, tx2, cy = _slider_track(px, i)
        val   = tb[sl["key"]]
        ratio = (val - sl["min"]) / (sl["max"] - sl["min"])
        kx    = int(tx1 + ratio * (tx2 - tx1))

        _tq.append((sl["label"], px + _SL_PAD, cy - 8, 12, C_DIM))

        # 트랙
        cv2.rectangle(canvas, (tx1, cy-2), (tx2, cy+2), (12, 14, 20), -1)
        cv2.rectangle(canvas, (tx1, cy-2), (kx,  cy+2), C_ACCENT, -1)
        cv2.rectangle(canvas, (tx1, cy-2), (tx2, cy+2), C_BORDER, 1)

        # 노브
        active = (active_id == sl["id"])
        knob_col = (220, 200, 80) if active else (160, 135, 40)
        cv2.circle(canvas, (kx, cy), 7, knob_col, -1)
        cv2.circle(canvas, (kx, cy), 7, (255, 240, 120) if active else C_ACCENT, 1)

        # [-] [+] 버튼
        mr, pr = _slider_btn_rects(px, i)
        for rect, lbl in ((mr, "-"), (pr, "+")):
            bx1, by1, bx2, by2 = rect
            cv2.rectangle(canvas, (bx1, by1), (bx2, by2), (40, 50, 65), -1)
            cv2.rectangle(canvas, (bx1, by1), (bx2, by2), C_BORDER, 1)
            # 심볼 중앙 정렬
            mx = (bx1 + bx2) // 2 - 4
            my = (by1 + by2) // 2 + 5
            cv2.putText(canvas, lbl, (mx, my),
                        cv2.FONT_HERSHEY_PLAIN, 1.1, C_TEXT, 1)

        # 값 (버튼 사이 중앙)
        vx = (mr[2] + pr[0]) // 2 - 10
        cv2.putText(canvas, str(val), (vx, cy + 5),
                    cv2.FONT_HERSHEY_PLAIN, 1.0, C_TEXT, 1)


def hit_slider(px, x, y):
    for i, sl in enumerate(SLIDERS):
        tx1, tx2, cy = _slider_track(px, i)
        if tx1-10 <= x <= tx2+10 and abs(y - cy) <= 16:
            return sl["id"]
    return None


def update_slider(px, sl_id, x):
    for i, sl in enumerate(SLIDERS):
        if sl["id"] == sl_id:
            tx1, tx2, _ = _slider_track(px, i)
            ratio = max(0.0, min(1.0, (x - tx1) / max(1, tx2 - tx1)))
            tb[sl["key"]] = max(sl["min"], min(sl["max"],
                                int(sl["min"] + ratio * (sl["max"] - sl["min"]))))
            break


# ── Buttons ───────────────────────────────────
def make_buttons(px):
    bm = _BTN_M
    bh = _BTN_H
    fw = PANEL_W - bm * 2
    hw = (fw - bm) // 2
    btns = []
    y = _BTN_START

    def full(bid, label, color):
        nonlocal y
        btns.append({"id": bid, "label": label, "color": color,
                     "rect": (px+bm, y, px+bm+fw, y+bh)})
        y += bh + bm

    def half(bid1, l1, c1, bid2, l2, c2):
        nonlocal y
        btns.append({"id": bid1, "label": l1, "color": c1,
                     "rect": (px+bm, y, px+bm+hw, y+bh)})
        btns.append({"id": bid2, "label": l2, "color": c2,
                     "rect": (px+bm*2+hw, y, px+bm*2+hw+hw, y+bh)})
        y += bh + bm

    full("set_ref",    "기준선 측정",  (30, 160, 30))
    half("upper_up",   "위쪽선 ▲", (120, 120, 0),
         "upper_down", "위쪽선 ▼", (120, 120, 0))
    half("lower_up",   "아래선 ▲", (0, 110, 180),
         "lower_down", "아래선 ▼", (0, 110, 180))
    full("cam_switch", "카메라 전환", (70, 80, 100))
    half("save",       "사진 저장",  (90, 65, 15),
         "quit",       "종  료",    (90, 20, 20))
    return btns


def hit_button(btns, x, y):
    for b in btns:
        x1, y1, x2, y2 = b["rect"]
        if x1 <= x <= x2 and y1 <= y <= y2:
            return b["id"]
    return None


def draw_button(canvas, b, is_pressed):
    x1, y1, x2, y2 = b["rect"]
    col = b["color"]

    if is_pressed:
        fill   = tuple(min(255, c + 50) for c in col)
        border = tuple(min(255, c + 100) for c in col)
        text_c = (15, 18, 24)
        ofs    = 1
    else:
        fill   = tuple(max(0, c // 5) for c in col)
        border = col
        text_c = C_TEXT
        ofs    = 0

    cv2.rectangle(canvas, (x1, y1), (x2, y2), fill, -1)
    cv2.rectangle(canvas, (x1, y1), (x2, y2), border, 2)
    if not is_pressed:
        hl = tuple(min(255, c + 35) for c in col)
        cv2.line(canvas, (x1+2, y1+1), (x2-2, y1+1), hl, 1)

    sz = 13
    if _PIL_OK:
        try:
            tw = int(_kfont(sz).getlength(b["label"]))
        except AttributeError:
            tw = _kfont(sz).getsize(b["label"])[0]
    else:
        tw = len(b["label"]) * 8
    tx     = x1 + ofs + max(4, (x2 - x1 - tw) // 2)
    ty_pil = y1 + ofs + (_BTN_H - sz) // 2
    _tq.append((b["label"], tx, ty_pil, sz, text_c))


# ── Panel draw ────────────────────────────────
def draw_panel(canvas, px, state, btns):
    h = canvas.shape[0]
    canvas[0:h, px:px+PANEL_W] = C_PANEL
    cv2.line(canvas, (px, 0), (px, h), C_BORDER, 1)

    # ── 헤더바 (0–46) ──
    cv2.rectangle(canvas, (px, 0), (px+PANEL_W, 46), C_HDR, -1)
    cv2.line(canvas, (px, 46), (px+PANEL_W, 46), C_BORDER, 1)
    _tq.append(("비전 검사 시스템", px+12, 5, 17, C_ACCENT))
    cam_lbl = f"CAM {state['cam']}  |  {'내장 카메라' if state['cam']==0 else 'USB 카메라'}"
    _tq.append((cam_lbl, px+12, 26, 11, C_DIM))
    cv2.putText(canvas, datetime.now().strftime("%H:%M"),
                (px+PANEL_W-52, 20), cv2.FONT_HERSHEY_PLAIN, 1.1, C_DIM, 1)

    # ── 상태 블록 (46–116) ──
    blink_on = int(time.time() * 2) % 2 == 0
    has_ref  = state["upper_y"] is not None
    if state["status"] == "CAMERA_ERROR":
        st_txt, st_col = "카메라 오류", C_ERROR
        led_on = True
    elif state.get("measuring"):
        cur, tot = state.get("meas_prog", (0, 30))
        st_txt, st_col = f"측정 중...  {cur} / {tot}", C_WARN
        led_on = blink_on
    elif not has_ref:
        st_txt, st_col = "기준 없음", C_WARN
        led_on = blink_on
    elif state["status"] == "ALARM":
        st_txt, st_col = "처짐 감지!", C_ALARM
        led_on = blink_on
    else:
        st_txt, st_col = "정  상", C_OK
        led_on = True

    bg_col = tuple(c // 7 for c in st_col)
    cv2.rectangle(canvas, (px+6, 50), (px+PANEL_W-6, 114), bg_col, -1)
    cv2.rectangle(canvas, (px+6, 50), (px+PANEL_W-6, 114), st_col, 2)
    draw_led(canvas, px+22, 74, 10, st_col, led_on)
    _tq.append((st_txt, px+38, 57, 22, st_col))
    _tq.append((f"감지픽셀: {state['pixels']}    기준: {tb['min_pixels']}",
                px+38, 90, 11, C_DIM))

    # ── 라인 정보 (116–164) ──
    cv2.line(canvas, (px+6, 116), (px+PANEL_W-6, 116), C_BORDER, 1)
    uy, lv = state["upper_y"], state["lower_y"]
    _tq.append(("위쪽선", px+12, 120, 12, C_DIM))
    _tq.append((f"{uy} px" if uy is not None else "-- px", px+72, 120, 12, C_UPPER))
    _tq.append(("아래선", px+12, 138, 12, C_DIM))
    _tq.append((f"{lv} px" if lv is not None else "-- px", px+72, 138, 12, C_LOWER))

    # ── 슬라이더 섹션 (164–264) ──
    cv2.line(canvas, (px+6, 164), (px+PANEL_W-6, 164), C_BORDER, 1)
    _tq.append(("감지 설정", px+12, 167, 11, C_DIM))
    draw_sliders(canvas, px, state.get("drag_slider"))

    # ── 버튼 섹션 (265–488) ──
    cv2.line(canvas, (px+6, _BTN_START-5), (px+PANEL_W-6, _BTN_START-5), C_BORDER, 1)
    press_id, press_t = state.get("btn_press", (None, 0))
    for b in btns:
        is_pressed = (b["id"] == press_id) and (time.time() - press_t < 0.25)
        draw_button(canvas, b, is_pressed)

    # ── 하단 힌트 (488–540) ──
    cv2.line(canvas, (px+6, h-54), (px+PANEL_W-6, h-54), C_BORDER, 1)
    _tq.append(("우클릭 드래그: 검사영역 설정", px+8, h-50, 11, C_DIM))
    _tq.append(("좌클릭 드래그: 기준선 이동",   px+8, h-34, 11, C_DIM))


# ── Video overlay ─────────────────────────────
def draw_video(frame, state, det_mask, preview_mask):
    rx1, ry1, rx2, ry2 = state["roi"]
    st  = state["status"]
    blink_on = int(time.time() * 2) % 2 == 0

    # ── 마스크 오버레이 ──
    try:
        if preview_mask is not None and state["upper_y"] is None:
            mh, mw = preview_mask.shape[:2]
            area = frame[ry1:ry1+mh, rx1:rx1+mw]
            if area.shape[:2] == (mh, mw):
                ov = np.zeros_like(area)
                ov[preview_mask > 0] = (180, 90, 0)
                frame[ry1:ry1+mh, rx1:rx1+mw] = cv2.addWeighted(area, 0.65, ov, 0.35, 0)

        if det_mask is not None and cv2.countNonZero(det_mask) > 0:
            mh, mw = det_mask.shape[:2]
            area = frame[ry1:ry1+mh, rx1:rx1+mw]
            if area.shape[:2] == (mh, mw):
                ov = np.zeros_like(area)
                ov[det_mask > 0] = (0, 0, 210)
                frame[ry1:ry1+mh, rx1:rx1+mw] = cv2.addWeighted(area, 0.6, ov, 0.4, 0)
    except Exception:
        pass

    # ── ROI 박스 + 코너 마크 ──
    if st == "ALARM" and blink_on:
        roi_col = C_ALARM
    elif state["upper_y"] is None:
        roi_col = C_WARN
    else:
        roi_col = C_OK
    draw_corner_marks(frame, rx1, ry1, rx2, ry2, roi_col, sz=20, th=2)
    cv2.putText(frame, "INSPECT ZONE", (rx1+4, max(14, ry1-5)),
                cv2.FONT_HERSHEY_PLAIN, 0.9, roi_col, 1)

    # ── 기준선 ──
    if state["upper_y"] is not None:
        ua = ry1 + state["upper_y"]
        cv2.line(frame, (rx1, ua), (rx2, ua), C_UPPER, 1)
        cv2.putText(frame, "UPPER", (rx2-50, max(12, ua-3)),
                    cv2.FONT_HERSHEY_PLAIN, 0.9, C_UPPER, 1)
    if state["lower_y"] is not None:
        la = ry1 + state["lower_y"]
        cv2.line(frame, (rx1, la), (rx2, la), C_LOWER, 1)
        cv2.putText(frame, "LOWER", (rx2-50, min(FH-4, la+12)),
                    cv2.FONT_HERSHEY_PLAIN, 0.9, C_LOWER, 1)

    if state.get("roi_preview"):
        p = state["roi_preview"]
        cv2.rectangle(frame, (min(p[0],p[2]), min(p[1],p[3])),
                              (max(p[0],p[2]), max(p[1],p[3])), C_WARN, 1)

    # ── 상태 배지 (좌상단) ──
    if st == "CAMERA_ERROR":
        st_txt, st_col = "카메라 오류", C_ERROR
    elif state.get("measuring"):
        cur, tot = state.get("meas_prog", (0, 30))
        st_txt, st_col = f"측정 중... {cur}/{tot}", C_WARN
    elif state["upper_y"] is None:
        st_txt, st_col = "기준 없음", C_WARN
    elif st == "ALARM":
        st_txt, st_col = "처짐 감지!", C_ALARM
    else:
        st_txt, st_col = "정  상", C_OK

    badge_show = not (st == "ALARM" and not blink_on)
    if badge_show:
        bg = tuple(c // 5 for c in st_col)
        cv2.rectangle(frame, (4, 4), (230, 46), bg, -1)
        cv2.rectangle(frame, (4, 4), (230, 46), st_col, 2)
        draw_led(frame, 20, 25, 8, st_col, True)
        _tq.append((st_txt, 34, 12, 20, st_col))

    cv2.putText(frame, datetime.now().strftime("%H:%M:%S"),
                (FW-95, 22), cv2.FONT_HERSHEY_PLAIN, 1.2, C_DIM, 1)

    # ── 기준 없음: 사용 안내 오버레이 ──
    if state["upper_y"] is None and st != "CAMERA_ERROR" and not state.get("measuring"):
        guide_lines = [
            "[ 시작 방법 ]",
            "1. 실을 정위치에 올려주세요",
            "2. 오른쪽 패널 [기준선 측정] 클릭",
            "3. 측정 완료 후 자동 감시 시작",
        ]
        bx1, by1 = FW//2 - 210, FH//2 - 60
        bx2, by2 = FW//2 + 210, FH//2 + 62
        ov = frame.copy()
        cv2.rectangle(ov, (bx1, by1), (bx2, by2), (10, 12, 18), -1)
        cv2.addWeighted(ov, 0.6, frame, 0.4, 0, frame)
        cv2.rectangle(frame, (bx1, by1), (bx2, by2), C_WARN, 2)
        for gi, line in enumerate(guide_lines):
            col = C_WARN if gi == 0 else C_TEXT
            sz  = 15 if gi == 0 else 13
            _tq.append((line, bx1+12, by1 + 8 + gi*28, sz, col))


# ── Mouse callback ────────────────────────────
def make_mouse_cb(state, btns_ref, panel_x):
    def cb(event, x, y, flags, param):
        try:
            btns = btns_ref[0]
            rx1, ry1, rx2, ry2 = state["roi"]

            if event == cv2.EVENT_LBUTTONDOWN:
                if x >= panel_x:
                    # [-][+] 버튼 먼저 체크
                    sbtn = hit_slider_btn(panel_x, x, y)
                    if sbtn:
                        sid, delta = sbtn
                        for sl in SLIDERS:
                            if sl["id"] == sid:
                                tb[sl["key"]] = max(sl["min"], min(sl["max"],
                                                    tb[sl["key"]] + delta))
                                break
                        return
                    sid = hit_slider(panel_x, x, y)
                    if sid:
                        state["drag_slider"] = sid
                        update_slider(panel_x, sid, x)
                        return
                    bid = hit_button(btns, x, y)
                    if bid:
                        state["action"] = bid
                        state["btn_press"] = (bid, time.time())
                        return
                else:
                    if state["upper_y"] is not None:
                        ua = ry1 + state["upper_y"]
                        if rx1 <= x <= rx2 and abs(y - ua) <= 12:
                            state["drag_mode"] = "upper"; return
                    if state["lower_y"] is not None:
                        la = ry1 + state["lower_y"]
                        if rx1 <= x <= rx2 and abs(y - la) <= 12:
                            state["drag_mode"] = "lower"; return

            elif event == cv2.EVENT_MOUSEMOVE:
                if state.get("drag_slider"):
                    update_slider(panel_x, state["drag_slider"], x)
                    return
                roi_h = ry2 - ry1
                if state["drag_mode"] == "upper":
                    ly = state["lower_y"] if state["lower_y"] else roi_h - 1
                    state["upper_y"] = max(0, min(y - ry1, ly - 5))
                elif state["drag_mode"] == "lower":
                    uy = state["upper_y"] if state["upper_y"] is not None else 0
                    state["lower_y"] = max(uy + 5, min(y - ry1, roi_h - 1))
                elif state.get("roi_drag") and x < panel_x:
                    sx, sy = state["roi_start"]
                    state["roi_preview"] = (sx, sy, x, y)

            elif event == cv2.EVENT_LBUTTONUP:
                state["drag_slider"] = None
                state["drag_mode"]   = None

            elif event == cv2.EVENT_RBUTTONDOWN:
                if x < panel_x:
                    state["roi_drag"]    = True
                    state["roi_start"]   = (x, y)
                    state["roi_preview"] = (x, y, x, y)

            elif event == cv2.EVENT_RBUTTONUP:
                if state.get("roi_drag"):
                    state["roi_drag"] = False
                    sx, sy = state["roi_start"]
                    nr = (min(sx,x), min(sy,y), max(sx,x), max(sy,y))
                    if (nr[2]-nr[0]) > 20 and (nr[3]-nr[1]) > 20:
                        state["roi"]         = clamp_roi(nr)
                        state["roi_preview"] = None
                        state["upper_y"]     = None
                        state["lower_y"]     = None
                        state["ref_mask"]    = None
                        state["action"]      = "roi_changed"
        except Exception:
            pass
    return cb


# ── Main ──────────────────────────────────────
def main():
    print("=" * 50)
    print(" Vision Inspection System")
    print("=" * 50)

    cap, cam_index = auto_detect_camera()
    if cap is None:
        print("[ERROR] 사용 가능한 카메라가 없습니다.")
        return

    print(f"[INFO] Camera {cam_index}: {FW}x{FH}")
    print("[INFO] 기준선 측정 버튼을 클릭하세요.\n")

    default_roi = clamp_roi((ROI_X1, ROI_Y1, ROI_X2, ROI_Y2))
    state = {
        "roi":         default_roi,
        "upper_y":     None,
        "lower_y":     None,
        "ref_mask":    None,
        "status":      "NORMAL",
        "pixels":      0,
        "confirm":     0,
        "cam":         cam_index,
        "cam_fail":    0,
        "measuring":   False,
        "meas_prog":   (0, 30),
        "meas_result": None,
        "drag_mode":   None,
        "roi_drag":    False,
        "roi_start":   None,
        "roi_preview": None,
        "action":      None,
        "btn_press":   (None, 0),
        "drag_slider": None,
    }

    btns_ref  = [make_buttons(FW)]
    canvas    = np.zeros((CANVAS_H, CANVAS_W, 3), dtype=np.uint8)

    cv2.namedWindow(WIN_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WIN_NAME, CANVAS_W, CANVAS_H)
    cv2.setMouseCallback(WIN_NAME, make_mouse_cb(state, btns_ref, FW))

    send_signal("NO_REFERENCE")   # 시작 시 황색

    frame_num    = 0
    det_mask     = None
    preview_mask = None
    last_capture = time.time()
    last_frame   = np.zeros((FH, FW, 3), dtype=np.uint8)

    while True:
        # ── Read frame (측정 중에는 마지막 프레임 재사용) ──
        if state.get("measuring"):
            frame = last_frame.copy()
        else:
            frame = read_frame(cap)
            if frame is None:
                time.sleep(0.1)
                frame = read_frame(cap)
            if frame is None:
                state["cam_fail"] += 1
                frame = last_frame.copy()
                if state["cam_fail"] >= 30:
                    state["status"] = "CAMERA_ERROR"
            else:
                if state["cam_fail"] >= 30:
                    print("[INFO] Camera recovered")
                state["cam_fail"] = 0
                last_frame = frame.copy()

        # ── 측정 결과 적용 ──
        if state.get("meas_result") is not None and not state.get("measuring"):
            uy, ly, rm = state.pop("meas_result")
            if uy is not None:
                state.update({"upper_y": uy, "lower_y": ly, "ref_mask": rm,
                              "confirm": 0, "status": "NORMAL"})
                det_mask = None
                send_signal("NORMAL")
                print("[INFO] Reference set.")
            else:
                state["status"] = "NORMAL"
                send_signal("NO_REFERENCE")

        # ── Action ──
        action = state["action"]
        state["action"] = None

        if action == "roi_changed":
            print(f"[INFO] New ROI: {state['roi']}")
            det_mask = None

        # ── Detection ──
        rx1, ry1, rx2, ry2 = state["roi"]
        preview_mask = None
        det_mask     = None

        frame_num += 1
        if frame_num % 2 == 0:
            try:
                crop = frame[ry1:ry2, rx1:rx2]
                if crop.size > 0:
                    roi_gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                    if state["upper_y"] is None:
                        _, preview_mask = cv2.threshold(
                            roi_gray, tb["brightness"], 255, cv2.THRESH_BINARY_INV)
                    else:
                        det_mask, pcount = detect(
                            roi_gray, state["upper_y"], state["lower_y"],
                            state.get("ref_mask"))
                        state["pixels"] = pcount

                        if pcount >= tb["min_pixels"]:
                            state["confirm"] = min(state["confirm"] + 1, tb["confirm"] * 2)
                        else:
                            state["confirm"] = max(0, state["confirm"] - 1)

                        new_st = "ALARM" if state["confirm"] >= tb["confirm"] else "NORMAL"
                        if new_st != state["status"]:
                            state["status"] = new_st
                            send_signal(new_st)
                            if new_st == "ALARM" and CAPTURE_ON_ALARM:
                                save_frame(frame, "alarm")
                            print(f"[STATUS] -> {new_st}  (pixels: {pcount})")
            except Exception as e:
                print(f"[WARN] Detection error: {e}\n{traceback.format_exc()}")

        # ── Periodic save ──
        if CAPTURE_INTERVAL_SEC > 0:
            now = time.time()
            if now - last_capture >= CAPTURE_INTERVAL_SEC:
                save_frame(frame, "alarm" if state["status"] == "ALARM" else "normal")
                last_capture = now

        # ── Draw ──
        try:
            canvas[:] = C_BG
            video = frame.copy()
            draw_video(video, state, det_mask, preview_mask)
            flush_tq(video)                          # 영상 한글 텍스트 렌더링
            canvas[:CANVAS_H, :FW] = video[:CANVAS_H, :FW]
            draw_panel(canvas, FW, state, btns_ref[0])
            flush_tq(canvas)                         # 패널 한글 텍스트 렌더링
            cv2.imshow(WIN_NAME, canvas)
        except Exception as e:
            print(f"[WARN] Draw error: {e}")

        # ── Keys ──
        key = cv2.waitKey(1) & 0xFF

        if action == "quit" or key in (ord('q'), 27):
            break

        elif (action == "set_ref" or key in (ord('b'), ord('B'))) \
                and not state.get("measuring"):
            state["measuring"]   = True
            state["meas_prog"]   = (0, 30)
            state["meas_result"] = None
            def _do_measure(cap_ref, roi_ref):
                def _prog(cur, tot):
                    state["meas_prog"] = (cur, tot)
                result = measure_bounds(cap_ref, roi_ref, on_progress=_prog)
                state["meas_result"] = result
                state["measuring"]   = False
            threading.Thread(
                target=_do_measure, args=(cap, state["roi"]), daemon=True
            ).start()

        elif action == "cam_switch" or key in (ord('c'), ord('C')):
            ni = 1 if cam_index == 0 else 0
            nc = open_cam(ni)
            if nc:
                cap.release()
                cap, cam_index = nc, ni
                state.update({"cam": ni, "upper_y": None, "lower_y": None,
                              "ref_mask": None, "confirm": 0, "status": "NORMAL"})
                btns_ref[0] = make_buttons(FW)
                det_mask = None
                print(f"[INFO] Switched to camera {ni}")
            else:
                print(f"[WARN] Camera {ni} not available")

        elif action == "save" or key in (ord('s'), ord('S')):
            save_frame(frame, "manual")

        elif action == "upper_up" and state["upper_y"] is not None:
            state["upper_y"] = max(0, state["upper_y"] - 3)
        elif action == "upper_down" and state["upper_y"] is not None:
            ly = state["lower_y"] or (ry2 - ry1 - 1)
            state["upper_y"] = min(ly - 5, state["upper_y"] + 3)
        elif action == "lower_up" and state["lower_y"] is not None:
            uy = state["upper_y"] or 0
            state["lower_y"] = max(uy + 5, state["lower_y"] - 3)
        elif action == "lower_down" and state["lower_y"] is not None:
            state["lower_y"] = min((ry2 - ry1) - 1, state["lower_y"] + 3)

    cap.release()
    cv2.destroyAllWindows()
    if arduino:
        arduino.close()
    if _relay and _relay.is_open:
        _relay_off()
        _relay.close()
    print("\n[INFO] Program closed")


if __name__ == "__main__":
    main()
