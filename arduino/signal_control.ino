/*
  =============================================
  비전 검사 시스템 - 산업용 경보등 릴레이 제어
  =============================================

  [ 배선 ]
  Arduino Pin 8  → 릴레이 모듈 IN
  Arduino 5V     → 릴레이 모듈 VCC
  Arduino GND    → 릴레이 모듈 GND

  릴레이 COM → 12V 어댑터 (+)
  릴레이 NO  → 경보등 전원 (+)
  경보등 (-) → 12V 어댑터 (-)  [공통 GND]

  [ PC → Arduino 시리얼 명령 ]
  'R' → 알람  : 릴레이 ON  → 경보등 켜짐 (자체 깜빡임+사이렌)
  'G' → 정상  : 릴레이 OFF → 경보등 꺼짐
  'Y' → 대기  : 릴레이 OFF → 경보등 꺼짐

  Baudrate: 9600 (settings.py ARDUINO_BAUDRATE 와 일치)
*/

#define PIN_RELAY 8

void setup() {
  Serial.begin(9600);
  pinMode(PIN_RELAY, OUTPUT);
  digitalWrite(PIN_RELAY, LOW);  // 시작: 경보등 OFF
  Serial.println("Arduino Ready");
}

void loop() {
  if (Serial.available() > 0) {
    char cmd = Serial.read();

    if (cmd == 'R') {
      // 알람: 경보등 ON (내장 깜빡임+사이렌 자동 작동)
      digitalWrite(PIN_RELAY, HIGH);
      Serial.println("ALARM ON");
    }
    else if (cmd == 'G' || cmd == 'Y') {
      // 정상 또는 대기: 경보등 OFF
      digitalWrite(PIN_RELAY, LOW);
      Serial.println("ALARM OFF");
    }
  }
}
