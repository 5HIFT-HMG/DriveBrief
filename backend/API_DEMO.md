# 로컬 FastAPI ↔ Pleos 개발 데모

이 API는 기존 results/groq-source-ids-v3-once.json을 읽는 개발용 어댑터입니다.
Groq 재호출·새 크롤링·캐시 쓰기·DB 스키마 변경은 하지 않습니다.
원본 가상 기사의 article_id로 제목/출처를 가져오며 없는 메타데이터(분야 등)는 만들지 않습니다.

## 실행

DriveBrief/backend에서 실행합니다. Python 3.9 환경에서 검증합니다.

```sh
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install -e '.[test]'
DRIVEBRIEF_DEMO_ENABLED=1 .venv/bin/python -B -m drivebrief_api
```

127.0.0.1:8000에만 바인딩합니다. host 변경 옵션이 없습니다.
API 키 환경변수는 필요하지 않습니다. 기본적으로 DRIVEBRIEF_DEMO_ENABLED가 없으면 데모는 비활성화됩니다.
접근 로그는 꺼져 있고 CORS 전체 허용이나 외부 배포 설정은 없습니다.

```sh
curl --fail http://127.0.0.1:8000/healthz
.venv/bin/python -B -m unittest discover -s tests -v
```

## 엔드포인트와 정책

- GET /healthz: status=ok 및 demo_enabled. 데이터 파일이 없는 경우에도 프로세스 상태만 확인합니다.
- GET /v1/demo/briefing?allow_unreviewed_fictional=true:
  서버의 데모 활성화 및 요청의 명시적 동의가 모두 있어야 합니다. 누락 시 403.
- POST /v1/briefings 등 실제 서비스 엔드포인트는 구현하지 않았습니다(404).

저장된 Groq 결과와 원본 가상 기사만 읽습니다. 가상 권한/ID/요약 스키마와 기존 근거 연결을
다시 검사하며 저장된 quote가 원문에서 재구성한 결과와 다른 경우도 거절합니다.
needs_review/approved=false/review_required=true 자료만 명시적 데모 응답으로 반환합니다.
존재하지 않는 파일은 503/demo_data_missing, JSON·권한·ID·저장 결과 오류는 500/demo_data_invalid입니다.
오류 응답은 파일 경로·원문·모델 오류·키를 노출하지 않습니다.

## 저장 결과와 HTTP 스키마 구분

저장 결과는 기존 2-source-ids-review 문서입니다. API 응답은 별도의 demo-briefing-v1 DTO입니다.

응답 필드:
- schema_version=demo-briefing-v1
- demo_only=true, fictional_only=true, playback_requires_user_action=true
- articles: article_id, title, source, tts_sentences, one_line, detail,
  validation(status=needs_review, approved=false, review_required=true)

provenance, API 공급자 설정, API 키, 원문 body, 근거 인용문은 HTTP 응답에 포함하지 않습니다.
비어 있는 articles는 정상적인 빈 목록으로 전달합니다.
이 응답은 승인된 실서비스 브리핑이 아니며, 개발 데모 외 자동 재생/배포에 사용하면 안 됩니다.

## Android에서 확인

debug APK를 Pleos 에뮬레이터에 설치해 실행한 뒤:
1. 홈의 ‘개발용 AI 브리핑 불러오기’를 누릅니다.
2. 제목/출처/TTS 문장과 ‘미승인 가상 테스트 자료 · needs_review’ 표시를 확인합니다.
3. ‘데모 재생’을 눌렀을 때만 PleosSpeechOutput으로 받은 tts_sentences를 그대로 읽습니다.
4. 일시정지/재개: 완료된 문장 다음부터, 중단한 문장은 처음부터 다시 읽습니다.
5. ‘다음 문장’은 완료 콜백을 위조하지 않습니다. 건너뛴 문장이 있으면 완료로 표시하지 않습니다.
6. 홈으로 나가기·백그라운드 전환 시 정지합니다.
7. 서버를 Ctrl+C로 종료한 뒤 ‘다시 불러오기’를 누르면 오류/재시도가 표시되어야 합니다.

클라이언트 주소는 http://10.0.2.2:8000입니다. Mac localhost 서버에 대한 Android Emulator 호스트 주소입니다.
debug 빌드만 10.0.2.2/127.0.0.1/localhost HTTP를 허용합니다.
release에는 데모 진입 버튼이 없고 debug 네트워크 보안 설정도 병합되지 않습니다.
INTERNET 권한은 main에 추가되어 있습니다.
네트워크 작업은 Dispatchers.IO, 연결 5초/읽기 8초 제한, 응답 256 KB 제한 및 리다이렉트 금지입니다.
실패는 안전한 오류 문자열로 표시하며 응답/원문/키를 로그에 쓰지 않습니다.

10.0.2.2가 동작하지 않는 다른 환경의 대안:
```sh
adb -s emulator-5554 reverse tcp:8000 tcp:8000
```
이때 debug 클라이언트의 baseUrl을 http://127.0.0.1:8000으로 지정해 재검증할 수 있습니다.
기본 실행 경로는 10.0.2.2이며 자동으로 다른 네트워크 주소에 fallback하지 않습니다.
이번 환경에서의 실제 연결 검증 결과는 작업 완료 보고를 참고하세요.

## 유지한 기능 및 범위

기존 Mock 홈·분야 선택·10/20/30분 선택·브리핑·OnePaper는 그대로 유지합니다.
10/20/30분은 UI 선택이며 실제 시간 편성을 하지 않습니다.
서버 데모 재생은 별도 화면이며 기존 OnePaper에 청취 이력을 쓰거나 서버에 이벤트를 보내지 않습니다.
기존 Pleos TTS/Audio Focus/Vehicle SDK는 교체하지 않습니다.

테스트는 API 정상/오류/게이트/비노출/무외부호출, Android 파싱·로컬 HTTP 성공·연결 실패,
빈 목록·재시도·명시적 재생·정확한 TTS 문장 전달·일시정지/재개·건너뛰기를 포함합니다.
실제 전화/내비게이션 오디오 충돌, 실차 청취 및 시간 측정은 별도 확인이 필요합니다.
승인 워크플로, 운영용 API, ETA/시간 편성, 청취 저장, OnePaper 서버 연동, 배포는 미구현입니다.

## 2026-11-11 실제 검증 기록

- Python 3.9.6에서 백엔드 전체 42개 테스트 통과(API 6개 포함). API 테스트는 합성 저장 결과를 사용해
  실제 Groq 결과 파일이 없는 체크아웃에서도 외부 호출 없이 실행됩니다.
- Gradle Sync, assembleDebug, testDebugUnitTest(2개), processReleaseMainManifest 성공.
- Pleos emulator-5554 기기 테스트 19개 통과, 기본 Android TTS 미지원 진단 1개 제외.
- 최종 APK 재설치 및 MainActivity 실행 성공.
- 실제 서버가 127.0.0.1:8000에만 LISTEN하는 것을 확인.
- Android에서 10.0.2.2로 제목/TTS/needs_review 수신 성공. ADB reverse는 사용하지 않음.
- 명시적 재생 후 실제 문장 1/3 -> 일시정지 -> 재개 -> 문장 3개 onDone 확인.
- 사용자가 서버에서 불러온 한국어 요약 음성이 실제로 들린다고 확인.
- 서버 종료 후 최종 APK에서 연결 오류·재시도 표시, 크래시 없음.
- 서버 재시작 후 같은 재시도 버튼으로 데이터 복구 확인. 자동 재생 없음.
- 기존 Vehicle 도어 조회 door pos = 0 유지.
- 확인한 최종 Logcat에 앱 치명적 예외 없음. 에뮬레이터 OpenGLRenderer swap 관련 오류는 남아 있음.
- Groq 호출·새 크롤링·DB 스키마 변경·기존 SQLite 캐시 변경 없음.

