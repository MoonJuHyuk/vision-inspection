# =============================================
# 비전 검사 시스템 설정 파일
# =============================================

# --- 카메라 설정 ---
CAMERA_INDEX = 0          # USB 카메라 인덱스 (보통 0, 안되면 1로 변경)
FRAME_WIDTH = 960
FRAME_HEIGHT = 540

# --- ROI 설정 (실이 처지면 들어오는 영역) ---
# 화면을 보면서 직접 좌표 조정할 것
# (x시작, y시작, x끝, y끝) 픽셀 단위
ROI_X1 = 100
ROI_Y1 = 200
ROI_X2 = 1180
ROI_Y2 = 450   # 실이 지나가는 높이보다 약간 아래까지만

# --- 감지 설정 ---
# 실(어두운 객체)로 판단할 밝기 임계값 (0~255, 낮을수록 더 어두운 것만 감지)
THREAD_BRIGHTNESS = 100
# 처짐 판정 기준선 아래에서 실 픽셀이 몇 개 이상이면 알람
ALARM_PIXEL_COUNT = 50
# 감지 민감도 안정화를 위한 연속 프레임 수 (높일수록 오탐 줄어듦)
ALARM_CONFIRM_FRAMES = 8
# 정상 위치 하단에서 처짐 기준선까지의 여유 픽셀 (크면 더 많이 처져야 알람)
SAG_MARGIN = 30
# 기준선 바깥 몇 픽셀 범위만 알람 검사 (너무 멀리 있는 배경 무시)
DETECT_BAND = 80

# --- 사진 저장 설정 ---
CAPTURE_INTERVAL_SEC = 0    # 0 = 주기 저장 비활성화, 5 = 5초마다 저장 (데이터 수집용)
CAPTURE_ON_ALARM = False    # 알람 발생 시 즉시 사진 저장 여부
SAVE_DIR = "data/captures"  # 저장 폴더

# --- 굵기 프리셋 (조명 밝기, 추후 Arduino 연동 시 사용) ---
# 0 ~ 255 (Arduino PWM 값)
THICKNESS_PRESETS = {
    "0.2mm": 220,
    "0.5mm": 180,
    "1.0mm": 140,
    "1.5mm": 100,
    "2.0mm":  70,
}

# --- Arduino 시리얼 설정 ---
ARDUINO_ENABLED = False
ARDUINO_PORT = "COM3"
ARDUINO_BAUDRATE = 9600

# --- USB 릴레이 설정 (Arduino 없이 경보등 직접 제어) ---
# USB 릴레이 모듈을 PC에 꽂으면 COM 포트로 잡힘 (장치관리자에서 확인)
USB_RELAY_ENABLED = True
USB_RELAY_PORT    = "COM4"   # 장치관리자 > 포트(COM & LPT) 에서 확인 (COM3, COM5 등으로 다를 수 있음)
