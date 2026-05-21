# 비전 검사 시스템 — 실 처짐 감지

USB 카메라를 이용한 압출 실 처짐 감지 시스템

---

## 폴더 구조

```
vision_inspection/
├── src/
│   └── main.py              ← 메인 실행 파일
├── config/
│   └── settings.py          ← 설정값 모음 (ROI, 임계값 등)
├── data/
│   ├── captures/            ← 주기적 사진 자동 저장
│   └── logs/                ← 로그 (추후 사용)
├── arduino/
│   └── signal_control.ino   ← Arduino 스케치 (하드웨어 준비 후 사용)
├── requirements.txt
└── README.md
```

---

## 빠른 시작

### 1. 가상환경 만들고 패키지 설치

```bash
cd vision_inspection
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 2. 실행

```bash
python src/main.py
```

---

## 화면 조작

| 키 | 동작 |
|---|---|
| `Q` / `ESC` | 프로그램 종료 |
| `S` | 현재 화면 수동 저장 |
| `1` ~ `5` | 굵기 프리셋 선택 (0.2mm ~ 2.0mm) |
| `R` | 배경 모델 초기화 |

---

## 처음 실행 시 조정할 것

### 1. 카메라 인덱스
`config/settings.py` 에서 `CAMERA_INDEX` 값을 조정
- 보통 `0`, 안 되면 `1`, `2` 시도

### 2. ROI 좌표
화면을 보면서 실이 처지면 들어오는 영역에 맞게 조정
```python
ROI_X1 = 100   # 좌측
ROI_Y1 = 200   # 상단
ROI_X2 = 1180  # 우측
ROI_Y2 = 600   # 하단
```

### 3. 감지 민감도
처짐을 못 잡거나 오탐이 있을 때 조정
```python
THRESHOLD_VALUE = 40       # 낮을수록 민감
ALARM_PIXEL_COUNT = 500    # 낮출수록 민감
ALARM_CONFIRM_FRAMES = 5   # 높일수록 오탐 감소
```

---

## 개발 로드맵

- [x] Phase 1: OpenCV 배경차분 감지 + 모니터링 화면
- [ ] Phase 2: Arduino 연동 (신호등 + 조명 제어)
- [ ] Phase 3: YOLOv8 학습 데이터 수집 (Phase 1이 자동으로 저장)
- [ ] Phase 4: YOLOv8 모델 학습 + 교체
- [ ] Phase 5: Raspberry Pi 이식
