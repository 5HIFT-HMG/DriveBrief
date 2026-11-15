# DriveBrief 뉴스 요약: ID 기반 근거와 검토 상태

Python 3.9 이상 / Pydantic 2.11.10에서 검증한 독립 CLI입니다.
Android·news_crawler·FastAPI와 독립적이며 기존 뉴스 DB나 RSS를 자동으로 읽지 않습니다.
samples/articles.json은 자체 작성 가상 기사 10개입니다. 실제 기사 전문을 수집하지 않습니다.

## 책임 분리

1. 권한: Article.rights의 확인된 외부 LLM 처리·요약 재사용 허가와 basis를 검사합니다.
2. 원문 구간: segments.py가 제목/본문을 대략적인 문장·줄 단위로 나눕니다.
   긴 문장은 900자 이하 구간으로 나눕니다. 원문은 변형하지 않습니다.
3. ID: 원문 버전, 분할기 버전, 필드, Unicode 코드포인트 start/end, 구간 텍스트로 ID를 만듭니다.
   동일 원문/알고리즘은 동일 ID, 원문 변경은 새 ID입니다. 반복된 문장도 위치로 구분합니다.
   start는 포함, end는 제외이며 source[field][start:end]가 구간 text입니다.
   이 분할은 의미적으로 독립된 사실 단위라는 보장이 아닙니다.
4. LLM: source_spans와 제목을 받아 자연스러운 한국어 tts_sentences, one_line, detail을 작성하고
   각 출력에 evidence_links(target, index, evidence_ids)를 선택합니다. 인용문은 생성하지 않습니다.
5. Python: ID를 현재 기사에서 해석하여 실제 원문 quote와 출력 claim을 조립합니다.
   LLM이 quote, evidence_snippets, approved를 추가하면 strict Pydantic 검사에서 거절합니다.
6. 검증: 구조/ID/출력별 커버리지와 제한적인 사실 패턴을 검사합니다.
7. 의미 검토: 모든 정상 생성 결과는 validation.status=needs_review이며 approved=false입니다.
   자동 승인·재생·배포 경로는 없습니다. 사람이 원문 전체와 대조해야 합니다.

## LLM 입력/출력 계약

입력에는 article_title과 source_spans의 id, field, start, end, text가 들어갑니다.
권한 메타데이터와 API 키는 입력 메시지에 넣지 않습니다.

LLM의 evidence_links 예:
```json
{
  "target": "tts_sentences",
  "index": 0,
  "evidence_ids": ["실제 입력에 제공된 ID"]
}
```
tts_sentences의 index는 0부터 시작합니다. one_line/detail은 index=0입니다.
출력마다 정확히 하나의 link를 선택하며 그 출력 전체를 지지하는 ID 1~8개를 연결합니다.
detail이 여러 주장을 포함하면 관련 ID들을 함께 선택해야 합니다.
모델은 status=ok/insufficient, reason, tts_sentences, one_line, detail, evidence_links만 반환합니다.

## 공개 결과 호환성 (schema_version=2-source-ids-review)

유지한 result 필드:
status, reason, tts_sentences, one_line, detail, evidence_snippets.
evidence_snippets의 각 항목은 기존과 같은 claim/quote 두 문자열입니다.
claim은 해당 출력에서 Python이 가져오며 quote는 원문에서 Python이 복원합니다.
같은 quote가 여러 출력에 연결되면 중복 항목이 있을 수 있습니다.

추가한 envelope 필드:
- schema_version
- evidence_links: 출력 위치 -> ID 연결
- evidence_sources: 사용된 ID와 원문 필드/범위/text
- validation: status, approved, review_required, checks, review_flags
- provenance: 기존 정보에 approved=false, 분할/입출력 버전 및 공개 스키마 해시 추가

중요: result.status=ok는 구조 처리 성공일 뿐 사실 승인 표시가 아닙니다.
기존 provenance.review_required=true를 유지하며 validation.status=needs_review를 추가했습니다.
소비자는 approved=false인 결과를 자동으로 승인/재생/배포하지 않아야 합니다.
엄격한 envelope 파서나 예전 캐시/LLM 출력 파서는 새 버전에 맞게 업데이트해야 합니다.
원래 result의 claim/quote 필드를 읽는 파서는 그대로 사용할 수 있습니다.
근거가 많을 수 있어 공개 evidence_snippets 최대 개수는 20에서 80으로 늘었습니다.
이전 발췌형 LLM 입력 형식은 새 Draft 형식으로 교체했으며 직접 quote를 반환하는 응답은 거절합니다.

insufficient는 빈 텍스트/배열과 사유를 유지하며 validation도 insufficient, approved=false입니다.
로컬의 본문 100자/완결 문장 2개 미만 검사도 유지합니다.

## 검증 범위

즉시 거절:
- 없는 ID, 다른 기사/버전 ID, 중복 ID/target, 잘못된 target/index, 누락된 출력 근거
- 추가 quote/approved 등 스키마 외 필드, 잘못된 JSON/타입/길이
- 연결된 근거 구간에 없는 숫자 (기사 다른 부분에 존재해도 불충분)
- 인식 가능한 날짜의 연/월/일 불일치 (같은 숫자들의 순서 변경 포함)
- 제한된 직함+한국어 이름 패턴에서 발견한 근거에 없는 인물
- 원문에 그대로 있는 문장을 다른 원문 구간에 연결한 명확한 불일치

검토 보류:
- 모든 자연스러운 재서술, 문맥·사실 누락·근거 관련성·의미적 함의
- 탐지 가능한 부정 표현 차이: polarity_unverified
- 계획/예정 -> 확정 표현 의심: certainty_change_suspected
- 새 사건이나 규칙이 인식하지 못한 인물/날짜, 단위·숫자의 관계

숫자 존재는 관계/단위/통계 해석의 정확성을 증명하지 않습니다.
정규식 이름/부정 탐지는 한국어 NER나 의미 검증기가 아니며 오탐·미탐이 가능합니다.
근거 ID의 존재, 원문과 같은 문장, Mock 결과도 자동 승인하지 않습니다.
거절된 결과는 캐시하지 않으며, needs_review 초안은 승인되지 않은 상태로 캐시합니다.
실제 의미 검증기나 사람의 승인 저장 기능은 아직 구현하지 않았습니다.

## 설치 및 오프라인 실행

backend에서:
```sh
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install -e .
.venv/bin/python -B -m unittest discover -s tests -v
.venv/bin/python -B -m drivebrief_summary.cli --provider mock --input samples/articles.json --cache .cache/mock-ids.sqlite3 --output results/mock-ids-first.json
.venv/bin/python -B -m drivebrief_summary.cli --provider mock --input samples/articles.json --cache .cache/mock-ids.sqlite3 --output results/mock-ids-cached.json
```

첫 실행은 10개 중 9개 needs_review, 1개 insufficient입니다. 자동 승인 0개입니다.
두 번째 실행은 10개 모두 캐시 hit이며 검증/검토 상태가 유지됩니다.
Mock는 결정적인 문자열 재서술과 ID 선택을 하는 테스트 대역으로 AI 품질 검증이 아닙니다.
출력은 기존 파일을 덮어쓰지 않습니다. 재실행에는 새로운 파일/캐시 이름을 지정하세요.
결과 파일의 원문 근거는 결과 데이터이며 공개 로그로 전송하지 마세요.
진단 및 진행 메시지는 원문·모델 응답·키를 출력하지 않습니다.
CLI의 --output을 생략하면 기존처럼 결과 JSON을 stdout에 쓰므로 로그 수집 터미널에서는
항상 --output을 지정하세요.

## 캐시

SQLite 구조와 원자적인 BEGIN IMMEDIATE 중복 호출 방지를 유지합니다.
캐시 키는 기사/권한/모델/공급자/설정/프롬프트/LLM 스키마/공개 스키마/분할기/검증 버전을 포함합니다.
기존 캐시를 삭제하지 않고 새 정책과 분리합니다. 새 캐시에는 ID 기반 초안을 저장합니다.
매 hit마다 현재 원문으로 ID와 근거를 재해석하며 검토 상태를 서버에서 다시 계산합니다.
모델이나 캐시가 승인 여부를 공급할 수 없습니다. 권한 취소는 캐시 읽기 전 차단합니다.
전체 쓰기 잠금 방식은 단일 CLI용이며 서버 확장 시 키별 잠금이 필요합니다.
캐시·결과·.env·.venv는 .gitignore에서 제외합니다. 보관/삭제 정책은 별도 운영 과제입니다.

## 외부 호출 설정 (이번 작업에서는 실행하지 않음)

실제 호출은 사용자가 별도로 수행합니다. 자동 재시도나 모드 fallback은 없습니다.
GROQ_API_KEY는 환경변수로만 읽습니다. .env.example은 문서이며 .env를 자동 로딩하지 않습니다.
기본 모델은 openai/gpt-oss-20b, endpoint는 https://api.groq.com/openai/v1입니다.
LLM_MODEL/LLM_BASE_URL로 교체 가능하며 HTTPS·리다이렉트 차단 정책을 유지합니다.
LLM_JSON_MODE=schema(기본 strict) 또는 object, LLM_MAX_TOKENS=8192(추론+출력 합계),
LLM_REASONING_EFFORT=low(GPT-OSS만 전송; medium/high/omit 가능), LLM_TIMEOUT_SECONDS=30입니다.
API 키가 없으면 HTTP 요청 전 실패합니다. HTTP 403과 length 종료는 구분하며,
오류 원문/헤더 값은 노출하지 않고 허용 목록 오류 코드·형식·존재 여부만 진단합니다.
공급자 지원 문서: https://console.groq.com/docs/structured-outputs

권한 메타데이터는 담당자의 확인 기록이며 법적 사용 허가를 자동으로 판정하지 않습니다.
SBS·전자신문 등 이용 허가 미확인 자료는 입력하지 마세요.
