# 9단계: 현재 승인 브리핑 세션과 OnePaper 최소 연동

## 구현과 협업 경계
기존 DemoBriefingScreen, PleosSpeechOutput, OnePaper Column/Surface 레이아웃을 재사용한다.
SessionPaper 영역만 기존 OnePaper 상단에 추가했고 Mock/북마크 데모 영역은 유지한다.
수집·정기 작업·OnePaper 서버·클라우드 이벤트 API·팀원 브랜치는 구현/수정하지 않았다.

## 데이터 계약 (초안)
- 서버 briefing_id: 편성 내용/설정 식별자. 동일 편성은 같은 값일 수 있다.
- 앱 sessionId: 사용자 재생 세션 UUID. 재생 다시 시작·새로 불러오기는 별도 세션.
- DemoBriefing snapshot: 제공 기사 순서, 제목, 출처, one_line/detail, sourceUrl, 계획 문장,
  승인 원래 문장 수, 옵션/목표/예상 시간을 저장한다.
- ArticleListening: status, completed/skipped/started 인덱스 집합, cursor, interruptedAt,
  interruptionReason. 같은 문장 완료 콜백은 집합으로 중복 제거한다.
- session.ended와 fullyCompleted를 분리한다. 전체 완료는 모든 제공 기사 상태가 COMPLETED이고 종료된 경우다.

상태는 UNHEARD(미청취), PLAYING, COMPLETED, SKIPPED, INTERRUPTED.
시작 콜백만으로 완료되지 않는다. 시작한 문장의 완료 콜백만 한 번 집계한다.
다음 문장은 해당 문장을 건너뛴 것으로, 다음 기사는 나머지 문장을 건너뛴 것으로 기록한다.
재생 중단은 현재 문장 커서/시각을 남긴다. 아직 시작하지 않은 기사는 미청취로 유지한다.
건너뛴 문장이 있는 기사는 이후 일부 재생해도 완료로 바꾸지 않는다.
건너뜀과 중단이 함께 있으면 상태는 SKIPPED를 우선 표시하고 중단 시점/이유는 별도로 보존한다.

완료의 범위는 편성된 TTS 문장이다. 길이 편성에서 승인된 문장 일부만 제공됐다면,
완료 상태여도 OnePaper에 ‘전체 요약에는 미청취 내용이 포함됩니다.’를 표시한다.
실제 사람이 들었다는 증명이 아니라 TTS 콜백 기준이라는 안내도 유지한다.

## 저장 및 복원 범위
SessionHistory는 app-private SharedPreferences에 schema=1 JSON 스냅샷을 저장한다.
디스크 읽기·인코딩·commit은 IO dispatcher의 단일 큐에서 실행한다. UI는 StateFlow의 메모리 상태를 읽는다.
최근 20개 세션만 보존하는 개발용 로컬 정책이다. 팀 협의 후 보존 개수/삭제/보안 정책을 변경해야 한다.
서비스 DB나 기존 RSS/요약 캐시에는 쓰지 않는다.

- 화면 이동 후 기록 유지.
- Activity 재생성은 Bundle에 저장된 커서와 세션을 사용하되 일시정지 상태로 돌아온다.
- 프로세스 재시작 후 디스크 저장에 성공한 세션은 OnePaper에서 복원한다.
  PLAYING 상태로 저장됐다면 INTERRUPTED로 변환하고 자동 재생하지 않는다.
- 앱을 새로 실행해 재생 화면에 진입하면 서버에서 새 세션을 만든다.
  과거 세션을 서버와 동기화하거나 과거 커서에서 자동 이어듣기는 구현하지 않는다.
- 저장은 비동기이므로 저장 완료 이전의 즉시 프로세스 종료에서는 가장 최근 이벤트가 유실될 수 있다.
  테스트 flush는 큐 완료를 기다리며, 앱 강제 종료 검증은 UI 반영 뒤 저장 시간을 둔 상태에서 수행했다.
- 손상된 JSON은 덮어쓰지 않고 오류 표시·새 세션 시작 차단으로 원본을 보존한다.
- 저장 실패는 UI에 표시한다. 개발용 로컬 데이터이며 운영용 암호화/내보내기/사용자별 격리는 별도 과제다.

## OnePaper 표시
제공된 모든 기사(미청취 포함), 제목/출처/한 줄/전체 상세/원문 링크, 상태,
완료·건너뛴 문장 수, 중단 커서/시각, 브리핑 전체 완료 여부를 표시한다.
가상 자료에 원문 URL이 없으면 링크를 만들지 않는다.
보관된 승인 요약을 표시하며 새로운 요약 생성·API 키·원문 본문 저장은 하지 않는다.

## 검증
- 순수 reducer 단위 테스트 5개: 중복 완료/시작만 완료 불가, 일시정지·재개,
  건너뜀/미청취 구분, 전체 완료, 중단·재시작 상태.
- 신규 기기 테스트 5개: 디스크 roundtrip·복원, 손상 파일 보존,
  편성 파싱/문장 인덱스, 재생 완료와 OnePaper 일치, 중단/건너뜀 집계.
- 기존 테스트 포함 앱 단위 7개 통과, Pleos 기기 35개 통과·1개 제외.
  실제 저장 이력이 생긴 후 Mock 전용 UI 테스트 5개가 스크롤 위치로 실패한 것을 발견했다.
  enableDemo=false인 기존 Mock 모드에는 개발용 기록 영역을 표시하지 않도록 분리해
  사용자 기록 삭제나 기존 테스트 변경 없이 전체 회귀를 다시 통과했다.
  제외는 Android 기본 TTS init=-1 환경 진단이며 Pleos 전용 TTS와 구분한다.
- 실제 중간 편성 API: 3개 가상 기사, 각2문장(총6), 목표60초/예상55초.
  짧게는 3문장/28.6초, 길게는9문장/84.6초. 수치는 개발용 설정·동일 승인 자료에 대한 결과다.
- 실제 Pleos에서 일시정지·재개·다음 기사·중단 후 OnePaper에
  완료2/2, 건너뜀1/2, 중단0/2가 별개 상태로 표시되는 것을 확인했다.
- 앱 force-stop 후 재실행해 동일 세션·수치 복원과 자동 재생 없음을 확인했다.
- 첫 완주 확인 세션에는 건너뜀 기록이 있어 성공으로 집계하지 않았다.
  입력을 추가하지 않는 별도 재검증에서 시작6회·완료6회와 ‘브리핑 전체 재생 완료’를 확인했다.
- 이어 OnePaper의 세 기사 모두 완료2/2·전체 완료 표시와 첫 기사의
  제목/한 줄/전체 상세가 API와 일치함을 확인했다. 사용자는 한국어 연속 음성이 ‘잘들림’이라고 확인했다.
- 재검증 시작~최종 완료 콜백의 기기 초 단위 시각 차이는 약36초였다.
  예상55초와 차이가 있으므로 속도 추정은 보정이 필요하며 정확한 시간 편성이라고 주장하지 않는다.
- 실제 전화/내비게이션 오디오 충돌, 실차, 장시간/즉시 강제종료의 마지막 쓰기 보장은 검증하지 않았다.

## 실행
1. backend의 가상 기사 생성/사람 승인 절차는 STAGE6/STAGE8 참조. 실제 RSS를 입력하지 않는다.
2. backend에서 DRIVEBRIEF_DEMO_ENABLED=1 .venv/bin/python -B -m drivebrief_api.
3. debug 앱 홈에서 짧게/중간/길게와 관심 분야 선택 → 검토 승인 브리핑 불러오기.
4. 사용자 재생 버튼 → 제어 또는 전체 완료 → 홈 → OnePaper 보기.
5. 앱 종료·재시작 후 OnePaper로 저장 기록 확인.
6. 테스트: ./gradlew :app:testDebugUnitTest :app:connectedDebugAndroidTest.

## 팀과 합의할 인터페이스
- 수집/요약: selected ID와 별도 원문 catalog를 연결하는 명시적 매핑, 권한 증빙 책임자.
- Android: 옵션 문자열 유지 여부, 편성 응답 버전, 부분 문장 청취의 완료 명칭, 실제속도 보정.
- OnePaper: sessionId/briefingId/articleId, source sentence index, event type/time/id,
  전체 승인 요약과 실제 재생 부분 구분, 저장 보존·사용자 격리·서버 동기화.
내부 reducer/저장과 외부 서버 DTO를 분리했으므로 협의 후 adapter에서 변환할 수 있다.

## 팀 협의용 이벤트 DTO 예시 (서버 엔드포인트 미구현)
```json
{"session_id":"app-session-uuid","briefing_id":"brief_example","article_id":"fiction-01","status":"INTERRUPTED","completed_sentence_indices":[0],"skipped_sentence_indices":[],"cursor":1,"interrupted_at_ms":1794550000000,"session_ended":true,"session_completed":false}
```
현재 저장 파일은 SessionHistory의 schema=1 스냅샷이며 위 DTO를 서버로 전송하지 않는다.
