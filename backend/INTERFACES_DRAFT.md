# 실제 뉴스 연동 협의용 인터페이스 목록 (초안, 2026-11-13)

현재 코드의 계약을 정리한 문서다. 새 운영 API나 확정 규격을 만드는 문서가 아니다.
기존 API는 호환성을 유지하며 협의 후 필드 추가 또는 새 버전 adapter로 바꾼다.

| 경계 | 현재 필드/형식 | 책임·제한 |
|---|---|---|
| 수집기 → 메타데이터 | url, title, description, published_at(timezone), category/source 또는 categories/sources | RSS description은 전문이 아님. 수집 담당이 안정 ID·수정/삭제·오류 상태 규격 협의 |
| 원문 catalog → 요약 | InputArticle: article(id/title/body/source/rights), published_at, authored_at?, source_url?, origin | 본문·출처·외부 AI 처리 및 재사용 허가를 별도로 확보. 현재 통합은 fictional만 허용 |
| 이용 권한 | rights.kind, external_llm_allowed, summary_reuse_allowed, basis | bool은 담당자의 확인 기록이며 법적 권한을 자동 증명하지 않음. 증빙 보관·확인 책임자 협의 |
| 선정 결과 | ranked-news-v1: article_id, group_id, related_article_ids, rank, score_components, reasons | GET /v1/news/candidates. metadata_only/ai_eligible=false. 사건 ID는 구성원 해시로 영구 사건 레지스트리가 아님 |
| 선정 → 원문 | selected ID JSON + 별도 원문 catalog, selected_inputs adapter | ID만으로 RSS 설명을 본문으로 변환하지 않음. 미확인 원문·권한은 차단 |
| 요약 | result.tts_sentences,one_line,detail, evidence_links/sources, validation,provenance | 기존 drivebrief_summary. 검증 통과도 needs_review이며 의미적 정확성 승인 아님 |
| 검토/승인 | record+draft revision, reviewer/time, decision, validator version | CLI inspect/decide. 자동 승인 없음. quality_diagnostics는 추가 검토 정보이며 승인·기존 validation을 대체하지 않음 |
| 편성 → Android | approved-briefing-v1 + briefing_id,length_option,target/estimated/delta, articles/order/sentence_indices/partial_tts | GET /v1/briefings/plan. 기존 current/demo 유지. 길이 식별값은 짧게/중간/길게 |
| 청취 → OnePaper | 앱 sessionId(UUID), briefingId, 기사 ID, 시작/완료/건너뜀 인덱스, cursor, interruptedAt/reason, ended/fullyCompleted | 현재 앱 전용 로컬 저장. 서버 전송 API 미구현. 완료는 제공 문장 콜백 기준 |
| 실측 → 품질 분석 | speech-timing-v1: attempt/session/article IDs, 문장 인덱스/해시, 수치 특성, engine/locale/sdk, outcome, startup/speech/request 시간 | 앱 로컬 파일. 원문·음성·키 기록 없음. 실제 Pleos와 mock-test를 구분. 운영 수집·업로드 기능 아님 |

## 동의가 필요한 항목
1. article_id를 수집 단계부터 유지할지, canonical URL 해시를 adapter에서 계속 사용할지.
2. 본문 수정/권한 철회/기사 삭제가 들어올 때 캐시·승인·기존 편성 snapshot 무효화 방식.
3. 한국 날짜·UTC/KST 기준과 발행일 누락/미래 시각/수집 지연 허용 범위.
4. 분류 taxonomy 및 source alias, 사건 정답 라벨 정의(동일 주제와 동일 사건 구분), 판정자 간 불일치 처리.
5. 중요도 정답/선호 비교 방식, 최신 기사 부족 시 경고·제외 정책, 특정 출처 과집중 허용 범위.
6. 30/60/120초는 개발용 임시 설정이다. 최종 목표 시간과 추정 오차 허용치, 최소 문장 수 협의.
7. 부분 TTS 완료와 기사 전체 청취 완료의 표시 명칭. one_line/detail은 전체 승인 요약임을 유지.
8. OnePaper 서버 계약: idempotent event_id, session_id, briefing_id, article_id, 원문 문장 인덱스,
   상태/발생 시각, 서버 확인 순서, 중복/오프라인 재전송 정책.
9. 로컬 최근20세션 보존·사용자 격리·삭제·동기화 및 timing 데이터의 민감도/보존 기간.
10. 일반 승인 API와 미승인 가상 데모의 분리 유지. 원문·근거·검토자·키는 Android 응답에서 제외.

## 호환성 원칙
- 기존 /v1/news, /v1/briefings/current, /v1/demo/briefing을 임의 변경하지 않는다.
- 계산 모듈(selection/planning), wire DTO(pipeline_models), 검토 저장소(review),
  앱 상태 reducer/저장/표시를 분리한다.
- 승인 문장·전체 요약을 수정하거나 재생시간을 채우기 위해 반복하지 않는다.
- 외부 Groq 호출은 기존 명시적 opt-in만 가능. 이 작업에서는 실제 호출하지 않는다.
- 실제 기사 전문 수집·실시간/정기 수집은 이번 변경에 포함하지 않는다.
