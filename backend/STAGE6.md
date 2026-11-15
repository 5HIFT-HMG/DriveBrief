# 6단계: 가상 기사 입력·검토 승인·음성 브리핑

## 구현과 경계
- 새 InputArticle은 기존 Article을 감싸 발행일, 선택적 작성일/원문 URL, 자료 출처를 관리한다.
- 이번에는 fictional 자료만 처리한다. licensed 또는 unverified RSS 입력도 거부한다.
- samples/pipeline_articles.json의 가상 기사 3개는 기존 자체 작성 샘플의 일부다. 날짜 메타데이터도 합성이다.
- 기존 Summarizer/MockProvider/GroqProvider/권한 검사/근거 ID·숫자·날짜·인물 검증/캐시를 재사용한다.
- 검토 전용 .cache/review.sqlite3에 reviews 및 decisions 테이블을 새로 만든다.
  기존 news.sqlite3와 summaries 캐시 스키마는 변경하지 않는다.
- 승인·반려·수정 승인은 CLI 명령으로만 수행한다. 서버는 승인 API나 자동 승인 기능이 없다.
- 수정안은 Draft 전체와 evidence_links를 함께 제출하고 기존 검증을 다시 통과해야 한다.
- 원문/초안 해시, 검증 버전, 검토자·시각을 기록한다. 오래된 revision의 승인은 거부한다.
  원문·초안·모델 캐시 키 변경 시 재검토하며, 입력 권한 검증 실패 시 이전 승인도 회수한다.
- 읽기 API에서도 권한·근거·승인 해시를 재검사한다. 변조된 승인 자료는 503으로 차단한다.
- 의미적 정확성은 여전히 사람이 판단한다. 부정/확정 여부 경고를 검토해야 한다.
- 로컬 파일 신뢰 모델이다. 검토자 인증, 전자서명, 운영용 접근 통제, 전체 과거 초안 보관은 미구현이다.
  decisions는 결정 시각·검토자·해시만 기록하므로 과거 전문을 재구성하는 감사 저장소가 아니다.

## 데이터 흐름
입력 JSON → 기존 Summarizer/SQLite 캐시 → 기존 자동 검증 → review DB(needs_review)
→ 검토 문서 내보내기 → 사람이 승인/반려/수정 승인 → GET /v1/briefings/current
→ 기존 DemoBriefingClient/Screen의 승인 모드 → 기존 PleosSpeechOutput.

기존 /v1/news와 /v1/demo/briefing, Mock 홈·OnePaper는 유지한다.
승인 브리핑도 가상 자료이며 실제 뉴스 서비스로 승격하지 않는다.
API는 mock 여부를 전달하고 UI도 Mock를 AI 생성 결과와 구분한다.

## 오프라인 생성
backend에서:
```sh
.venv/bin/python -B -m drivebrief_api.review generate --input samples/pipeline_articles.json
```
기본 mock, 자동 외부 호출·재시도 없음. 같은 입력은 기존 캐시를 재사용한다.
배치별 성공/실패 배열의 순서는 입력 순서와 같다. 실패 기사 이후도 계속 처리한다.
실제 Groq는 사용자가 별도로 명시한 경우에만 --provider groq --allow-external 및
DRIVEBRIEF_ALLOW_GROQ=1, GROQ_API_KEY 환경변수가 모두 필요하다. 이번 작업에서 실행하지 않았다.

## 사람 검토 절차
```sh
.venv/bin/python -B -m drivebrief_api.review inspect --id fiction-01 --output results/review-fiction-01.json
```
fiction-02, fiction-03도 같은 방식으로 각각 내보낸다.
문서에는 원문(record), TTS/one_line/detail(result), 자동 검증/경고(validation),
근거 ID와 실제 문장(source_spans/evidence_links/evidence_snippets), revision이 들어 있다.
기존 출력 파일은 덮어쓰지 않는다. 다른 파일명을 사용한다.
원문이 포함된 검토 JSON은 로컬 전용이며 results/는 Git에서 제외한다.

원문과 모든 출력을 직접 비교한 다음 문서의 revision 값을 복사한다.
아래 REVISION은 실제 검토 문서의 값으로 교체해야 하며 복사 실행용 값이 아니다.
```sh
.venv/bin/python -B -m drivebrief_api.review decide --id fiction-01 --reviewer songhaaa --revision REVISION --decision approved --confirm-human-review
```
반려는 --decision rejected. 수정 승인은 검토 문서의 draft 객체만 별도 JSON으로 저장한 뒤
--edited-draft results/edited-fiction-01.json을 추가한다. 원문의 숫자/근거 ID를 임의로 바꾸면 거부한다.
수정 후 generate를 다시 실행하면 새 초안으로 바뀌어 승인이 해제될 수 있다.
승인 후 다시 inspect하면 결정 상태를 확인할 수 있다.

실제 로컬 자료는 자동 승인하지 않았다. 테스트에서만 test-reviewer의 임시 승인 fixture를 사용한다.

## 서버 및 앱
```sh
DRIVEBRIEF_DEMO_ENABLED=1 .venv/bin/python -B -m drivebrief_api
curl --fail http://127.0.0.1:8000/v1/briefings/current
```
승인 자료가 없으면 200과 articles=[]를 반환하며 DB를 새로 생성하지 않는다.
여러 승인은 article_id 순으로 최대 10건을 반환한다.
스키마는 approved-briefing-v1, fictional_only=true, playback_requires_user_action=true.
기사별 title/source/발행일/원문 URL/요약/mock/validation만 포함하며 원문·근거·검토자·키는 노출하지 않는다.
approval은 사람 결정 상태이며 자동 검증 결과가 의미 검증을 완료했다는 뜻이 아니다.

debug 앱 홈의 ‘검토 승인 브리핑 불러오기’에서 불러오고 ‘데모 재생’을 직접 누른다.
기존 TTS 화면과 SpeechOutput을 확장하며 별도 TTS 엔진은 만들지 않았다.
문장 완료 콜백에서 다음 문장, 기사 끝에서 다음 기사로 이동한다.
일시정지/재개·다음 문장/기사·중단·기사 번호·최종 완료를 제공한다.
건너뛴 내용이 있으면 전체 완료로 표시하지 않는다.
Activity 재생성/백그라운드/포커스 상실 뒤에는 사용자 재개가 필요하다.
서버 실패는 오류·재시도, 빈 목록은 빈 상태로 표시한다.
승인과 TTS 완료는 실제 청취 사실을 증명하지 않는다. OnePaper 서버 연결은 하지 않았다.

## 최초 구현 시 검증 기록
- Python 전체 62개 테스트(기존 52 + 검토 통합 10): 결과는 최종 실행 기록 참고.
- Android 앱·테스트 APK 빌드 및 단위 테스트 2개 검증.
- 새 기기 테스트 5개: 승인 파서, 3기사 순차 완료, 일시정지/재개/건너뛰기/중단,
  포커스 실패, 연결 실패·재시도·빈 목록. 기존 테스트와 함께 실행하도록 구성.
- 연결 기기가 없어 connectedDebugAndroidTest는 No connected devices로 실패했다.
  새 기기 테스트는 컴파일만 확인했으며 실행 통과로 집계하지 않는다.
- 이번에는 Pleos 실제 3기사 음성, Activity 재생성 실기 검증, 실제 사람의 승인 이후 연속 통합 실행을 확인하지 못했다.
- 실제 Groq 호출 0회. 로컬 Mock 3건 생성 및 두 번째 실행 캐시 hit 3건 확인.
- 실제 RSS DB SHA256은 기존 값과 동일. 무단 크롤링·배포·ETA·시간 편성 없음.

아래 후속 검증에서 사람 승인 및 기기 재생을 추가 확인했다.

## 후속 통합 검증 (2026-11-12)

- 사용자가 원문·요약·근거를 검토하고 fiction-01/02/03 승인 명령을 직접 실행했다고 확인했다.
- SQLite 읽기 전용 조회에서 3개 모두 approved 확인. 자동 승인 명령은 실행하지 않았다.
- 실제 /v1/briefings/current 응답: fiction-01 → fiction-02 → fiction-03, 기사별 3문장, 총 9문장.
  모두 approved=true, review_required=false, mock=true. 원문이나 검토자 정보는 응답하지 않는다.
- Pleos emulator-5554 연결, APK 재설치 및 MainActivity 실행 성공.
- connectedDebugAndroidTest: 30개 통과·1개 제외. 새 ApprovedBriefingTest 5개도 실제 실행 통과.
  제외 항목은 Android 기본 TTS init=-1 환경 진단이며 Pleos TTS와 구분한다.
- 실제 서버 데이터가 앱에 기사 1/3 및 Mock 표시로 나타남을 확인.
- Pleos 재생 중 일시정지 → 재개, 다음 문장, 기사 2/3 → 다음 기사 → 3/3 이동 확인.
- 재생 중단 후 ‘브리핑 중단 · 완료되지 않았습니다.’ 표시 확인.
- 다시 재생으로 기사 1/3부터 조작 없이 전체 재생. 마지막 기사 3/3에서
  ‘브리핑 전체 재생 완료’ 표시 및 재시작 이후 onDone 9회 확인.
- 사용자가 한국어 연속 음성이 ‘잘 들림’이라고 확인. 직접 청취한 주체는 사용자이며
  도구 검증은 화면 상태·콜백이다. 해당 로그 구간에서 앱 치명 오류나 TTS 오류는 발견되지 않음.
- 기능 수정 없이 통과했으며 이번 변경은 검증 문서 갱신뿐이다.

남은 검증: 실차, 실제 전화/내비게이션 오디오 포커스 상호작용, 장시간 재생·복원,
운영용 검토자 인증/승인 무결성 보강. 이번 연속 재생은 Mock 요약의 가상 자료이며
실제 뉴스 권한 확보·AI 품질·실제 RSS 요약·시간 편성·ETA·OnePaper 서버 완료를 의미하지 않는다.
