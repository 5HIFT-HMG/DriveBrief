# 실제 기사 파이프라인과 세션 API

기존 RSS 목록·가상 기사 데모·가상 기사 승인 API는 유지합니다. 실제 기사 경로는 별도 real-review.sqlite3를 사용합니다. 실제 요약도 기존 근거 ID 검증·캐시·검토 절차를 재사용합니다.

## 실행 준비

저장소 루트에서 backend로 이동하고 Python 3.9 이상 가상환경에 requirements.lock을 설치합니다. `.env.example`은 자동 로딩되지 않습니다. GROQ_API_KEY는 서버 환경변수에만 설정합니다. 앱에 키를 넣지 않습니다.

news_crawler/config.json의 body_sources에 사용할 도메인의 본문 수집 설정을 등록합니다. 아래는 형식 설명용이며 실제 언론사의 허가를 주장하지 않습니다.

```json
{
  "body_sources": {
    "news.example.org": {
      "collection_allowed": true,
      "element_id": "article-body",
      "rights": {
        "kind": "licensed",
        "external_llm_allowed": true,
        "summary_reuse_allowed": true,
        "basis": "확인한 이용 근거"
      }
    }
  },
  "max_article_age_days": 7
}
```

본문 selector가 없으면 NewsArticle JSON-LD articleBody를 사용합니다. 출처 설정이 없으면 본문을 요청하지 않고, 권한 근거가 없으면 외부 LLM에 전달하지 않습니다. 본문은 기존 articles와 별도 article_bodies에 저장합니다. HTML 구조 변경·수정 기사 본문 갱신은 추가 검증이 필요합니다.

## 수집부터 요약까지

backend에서 실행합니다.

```sh
.venv/bin/python -B -m drivebrief_api.pipeline --provider mock --length all
DRIVEBRIEF_ALLOW_GROQ=1 .venv/bin/python -B -m drivebrief_api.pipeline --provider groq --allow-external --length all
DRIVEBRIEF_ALLOW_GROQ=1 .venv/bin/python -B -m drivebrief_api.pipeline --provider groq --allow-external --length all --watch --interval 900
```

Groq 명령은 GROQ_API_KEY가 먼저 설정돼 있어야 합니다. 자동 재시도·자동 승인은 하지 않습니다. watch는 다음 수집 주기를 반복하며 동일 요약은 캐시를 재사용합니다. RSS 수집은 기존 collect 함수, 본문 수집은 full_text 모듈을 사용합니다. 사이클별 최신 본문 최대 20건, 길이별 요약 최대 10건을 처리합니다. 중단은 Ctrl+C입니다. 외부 모델 비용·기사 이용 근거가 준비된 환경에서만 Groq 명령을 실행하세요.

본문이 이미 저장돼 있으면 요약만 실행할 수 있습니다.

```sh
.venv/bin/python -B -m drivebrief_api.real_news generate --provider mock --length medium
DRIVEBRIEF_ALLOW_GROQ=1 .venv/bin/python -B -m drivebrief_api.real_news generate --provider groq --allow-external --length medium
```

short/medium/long은 별도 LLM 요청·캐시·검토 항목입니다. 각각 음성 문장 최대 1/2/3개이며 one_line/detail은 전체 기사를 대상으로 합니다. ID는 rss_URLHASH_short 등으로 구분합니다. Mock는 테스트용 대체 구현이며 AI 요약이 아닙니다.

## 검토

```sh
.venv/bin/python -B -m drivebrief_api.real_news inspect --id ARTICLE_ID --output results/real-review.json
.venv/bin/python -B -m drivebrief_api.real_news decide --id ARTICLE_ID --reviewer REVIEWER --revision REVISION --decision approved --confirm-human-review
```

ARTICLE_ID/REVISION은 실제 검토 문서 값으로 교체합니다. 원문·요약·근거·경고 확인 후 실행합니다. 테스트 밖의 승인은 이 작업에서 실행하지 않았습니다. 원문·권한 설정이 현재 DB와 달라진 항목은 새 브리핑에서 제외됩니다.

## API와 앱

```sh
.venv/bin/python -B -m drivebrief_api
```

서버는 기존대로 127.0.0.1:8000에서만 실행합니다. 에뮬레이터는 10.0.2.2:8000을 사용합니다.

서버 시작 시 RSS를 즉시 수집하고 300초마다 같은 news_crawler/news.sqlite3를 갱신합니다. RSS 갱신에는 Groq 키가 필요 없습니다. 수집 실패 시 기존 기사를 유지하고 다음 주기에 다시 시도합니다. 서버 종료 시 수집도 멈추며, 컴퓨터 절전 중에는 지연됩니다. 서버는 한 프로세스로 실행하세요. 별도 news.py --watch와 중복 실행할 필요가 없습니다. 본문 수집·LLM 요약은 위 파이프라인 명령을 별도로 사용합니다.

macOS에서는 저장소 루트의 run-local.command를 실행하면 가상환경과 필수 서버 패키지를 확인하고 서버를 시작합니다. 수집을 끄려면 `python -m drivebrief_api --no-news-collection`, 간격 변경은 `--news-interval 900`을 사용합니다(최소 300초).

`GET /v1/news/status`는 수집 실행 여부, 갱신 간격, 마지막 시도·성공 시각, 최신 기사 시각, 기사 수, 실패 피드 수와 stale 상태를 반환합니다. stale은 설정한 피드 중 하나라도 마지막 성공이 두 주기 이상 지났거나 성공 기록이 없으면 true입니다. API healthz 성공만으로 수집 성공을 판단하면 안 됩니다.

| 메서드 | 경로 | 동작 |
|---|---|---|
| GET | /v1/news/status | RSS 수집 실행 상태·마지막 갱신·오류 및 데이터 노후 여부 |
| POST | /v1/briefings | 관심 분야·요약 길이로 승인된 실제 기사 세션 생성 |
| POST | /v1/sessions/{id}/events | 재생 상태·완료 문장 수·북마크 기록 |
| GET | /v1/sessions/{id}/onepaper | 세션 생성 시점 요약·출처와 최신 재생 상태 반환 |

브리핑 요청은 `{"categories":["IT"],"length":"medium"}`입니다. length는 short/medium/long, optional budget_seconds는 30~7200입니다. 시간은 문자 수 기반 추정치이며 실제 TTS 측정값이나 내비 ETA 연동값이 아닙니다. 같은 정규화 제목을 제거하고 분야 내 최신순으로 최대 10건을 고릅니다. 의미 기반 동일 사건 통합·중요도 모델은 미구현입니다.

이벤트는 `{"event_id":"UUID","article_id":"ID","sequence":0,"state":"interrupted","completed_sentences":1,"bookmarked":true}` 형식입니다. state는 unplayed/playing/interrupted/completed이며 completed는 선택된 모든 문장이 완료돼야 합니다. 동일 event_id 재전송은 같은 내용일 때만 멱등 처리합니다. 과거 sequence·진행 역행은 409입니다.

앱 debug 홈의 ‘실제 뉴스 브리핑’에서 사용합니다. 홈에서 선택한 10·20·30분을 budget_seconds로 전달하고 서버가 반환한 예상 재생 시간을 표시합니다. 후보 수가 적으면 선택 시간보다 짧게 편성됩니다. 선택한 길이의 승인 요약이 없으면 빈 상태를 보여주며 다른 길이로 대체하지 않습니다. 직접 재생을 누른 뒤 TTS 완료 콜백으로 진행합니다. 중단 문장은 처음부터 재개합니다. 기록 동기화 실패는 재시도 버튼으로 복구하며 대기 기록이 있으면 OnePaper 조회·화면 종료를 보류합니다. Activity 재생성은 사용자 재개가 필요합니다. 세션 응답·문장 위치·북마크·미전송 이벤트를 앱 전용 파일에 원자적으로 저장합니다. 앱 강제 종료 후 실제 뉴스 화면을 다시 열면 복원하고 같은 event_id로 전송을 재시도합니다. 복원 후 재생은 사용자가 눌러야 합니다. 앱이 닫힌 동안의 백그라운드 전송은 하지 않습니다. 저장 실패 시 경고를 표시합니다.

OnePaper는 재생 완료·중단·미재생을 구분하고 모든 항목에 ‘기사 전체 내용 요약’임을 표시합니다. TTS 완료 콜백은 사용자의 실제 청취를 증명하지 않습니다. 운영용 인증·계정 간 세션 격리는 미구현이며 현재 로컬 개발용입니다.

## 검증 범위

- RSS/본문/길이별 Mock 요약/검토/세션/이벤트/OnePaper는 합성 자료로 오프라인 통합 테스트합니다.
- 2026-11-13: 백엔드 78개 테스트가 통과했습니다(RSS 서버 시작·종료, 실패 후 재시도, DB/API 일치 및 stale 판정 포함). FastAPI TestClient로 세션 생성·이벤트·OnePaper API도 검증했습니다.
- Android Studio에서 debug APK 빌드가 성공했고, Pleos Connect 2.1 API 34 에뮬레이터에 설치·실행하여 홈의 실제 뉴스 브리핑 진입 버튼을 확인했습니다.
- 실제 언론사 수집, Groq 호출, 실행 중인 HTTP 서버와 앱의 통신, 실제 뉴스 TTS 재생은 아직 검증하지 못했습니다. GROQ_API_KEY와 body_sources 설정이 필요합니다. 현재 실행 환경은 서버 소켓 열기도 제한합니다.
- 재생 상태 영구 저장과 다음 기사 자동 재생 상태 기록 수정 후 APK 재빌드가 성공했습니다. Pleos API 34에서 저장소 재생성 후 위치·대기 이벤트 복원 및 손상 파일 거부 기기 테스트 2개가 통과했습니다. 추가로 에뮬레이터 내부 HTTP fixture를 이용해 시간 예산 전송 → 이벤트 보고 → OnePaper 조회 테스트도 통과했습니다(총 3개). 이 HTTP fixture 검증은 Mac의 FastAPI 서버와의 실제 통신 검증과 다릅니다. 실제 프로세스 강제 종료 후 화면 복원 전체는 별도 검증이 필요합니다.
- 기존 기기 전체 테스트 실행은 도중 중단됐으며 당시 11개 통과·3개 실패가 기록됐습니다. 기존 Compose 화면 테스트에서 Activity 상태/Compose 계층 관련 오류가 발생했고 실제 TTS 테스트도 실패했습니다. 원인은 확정하지 않았으며 전체 회귀 테스트 통과를 주장하지 않습니다. Android 단위 테스트는 이번 환경에서 아직 실행하지 않았습니다.
- 전체 Python 테스트: backend에서 `.venv/bin/python -B -m unittest discover -s tests -v`.
- Android: 저장소 루트에서 `./gradlew :app:assembleDebug :app:testDebugUnitTest :app:connectedDebugAndroidTest`.

### RSS 운영 연결 검증 기록

2026-11-13: 기존 216개 기사를 API 기본 경로 news_crawler/news.sqlite3에 SQLite backup으로 복사했고 원래 날짜를 보존했습니다. 상태 API와 기사 API는 TestClient에서 200으로 응답했습니다. 실제 RSS 요청은 실행 환경의 DNS 제한으로 6개 모두 실패했습니다. 최신 기사 시각은 여전히 11월 7일이며, 최신 뉴스 갱신 성공으로 간주하지 않습니다. 로컬 Mac에서 run-local.command를 실행한 뒤 /v1/news/status의 collector_running, last_success_at, failed_feed_count, latest_article_at을 확인해야 합니다.
