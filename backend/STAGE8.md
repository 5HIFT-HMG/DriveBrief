# 8단계: 승인 문장 기반 길이 편성 (기존 경로)

현재 일반 앱 기본 RSS 경로는 [RSS_AUTO.md](RSS_AUTO.md)의 기사별 1/최대3/최대5 구간 방식이다.
아래 시간 예산과 사람 승인 정책은 기존 AI 요약·가상 기사 경로에만 적용한다.

## 안전 경계
기존 Summarizer/캐시/근거 검증/검토 CLI를 유지한다.
review generate --selected-ids는 선정 ID 배열을 별도 검증된 원문 catalog와 대조한다.
메타데이터만 있거나 권한 미확인/실제 기사인 경우 요약 입력을 만들지 않는다.
LLM 요약 경로는 기존 권한·근거 검증을 유지한다. RSS 제목·설명의 별도 경로는 LLM에 보내지 않는다.
일반 게시에는 출처별 명시적 TTS·재사용 허용 근거와 사람 승인을 모두 요구한다.
허용 근거가 없는 실제 RSS는 debug 전용 private-rss-preview-v1에서만 비공개 테스트한다.
이 미리보기는 needs_review/approved=false이며 일반 게시 함수와 일반 앱 파서가 거부한다.
이 경계는 수집기·선정기와 요약기의 명시적 인터페이스이며 자동 RSS 전문 전송 경로가 아니다.
API 요청은 LLM을 호출하지 않는다. generate 기본은 Mock이며 Groq는 기존 이중 opt-in 유지.

backend에서 별도 테스트 DB를 지정한 생성 예:
```sh
.venv/bin/python -B -m drivebrief_api.review --db .cache/pipeline-test.sqlite3 generate --input samples/pipeline_articles.json --selected-ids samples/pipeline_selected_ids.json --cache .cache/pipeline-test-summaries.sqlite3
```
승인은 STAGE6.md의 사람이 inspect/decide하는 절차를 따른다.
테스트 코드의 임시 승인 fixture를 실제 승인이라고 주장하지 않는다.
기존 사용자가 승인한 3건을 재생성하거나 자동 재승인하지 않는다.

## 내부 편성 및 설정
- 옵션 ID는 팀 PR #2의 문자열 짧게/중간/길게 그대로 사용한다.
- pipeline_config.json의 목표 30/60/120초는 개발 테스트용 placeholder이며 팀 정책이 아니다.
- characters_per_second=5, 문장 간 pause=0.4초로 문자 수 기반 예상값을 계산한다.
  실제 Pleos 속도 측정치가 아니며 과대/과소 추정될 수 있다.
- 승인된 기사만 기존 검토 저장소에서 읽고 매 요청 재검증한다. 편성은 승인 풀 전체를 평가하며,
  기존 current의 첫10건 상한을 미리 적용하지 않는다. 최종 편성은 설정 max_articles(기본10)로 제한한다.
- 7단계 그룹화/중요도/균형 선택을 재사용한다. 가상 기사 분류는 samples/pipeline_categories.json의
  명시적 테스트 분류이며 승인 요약문이나 원문 권한을 수정하지 않는다.
- 중요도·관심·분야 균형으로 대표 기사를 정렬한 뒤 각 기사 첫 문장을 예산 내 배정한다.
  이후 같은 순서로 한 문장씩 라운드로빈 추가한다. 기사별 원래 문장 순서의 prefix만 허용한다.
- 같은 문장을 반복하지 않으며 첫 문장도 못 넣는 기사는 제외한다.
- 전체 예상시간은 목표를 초과하지 않는다. 부족하면 shortage=true, delta_seconds<0으로 반환한다.
- one_line/detail은 승인 전체 요약 그대로다. TTS가 prefix로 줄면 partial_tts=true,
  approved_sentence_count와 sentence_indices를 제공한다. 전체 기사 청취 완료와 혼동하지 않는다.
- 후보 부족 시 새 내용을 생성하거나 문장을 늘리지 않는다.

## API
GET /v1/briefings/plan?length=중간&categories=경제&categories=사회
선택적으로 timezone 포함 as_of를 지정해 재현한다.
응답은 기존 approved-briefing-v1 envelope + briefing_id,length_option,policy_status,target_seconds,
estimated_seconds,delta_seconds,shortage,timing_estimate_only,as_of,status,articles다.
기사 필드는 기존 응답 + order,categories,group_id,importance_score,sentence_indices,
approved_sentence_count,partial_tts,estimated_seconds다.
briefing_id는 편성 내용·설정의 해시이며 청취 세션 ID와 다르다.
승인 자료가 없거나 예산이 너무 작으면 200과 빈 articles/status=no_fitting_approved_articles.
잘못된 옵션·분야/시각422, 자료·설정 오류503. 내부 검토 정보·키·원문은 반환하지 않는다.
기존 /v1/briefings/current 및 /v1/demo/briefing 계약은 유지한다.

Android는 기존 DemoBriefingClient의 명시적 길이 옵션에서만 plan을 호출한다.
기존 current 클라이언트와 테스트용 loader 주입은 유지한다.
홈의 검토 승인 브리핑 버튼이 현재 관심 분야와 길이를 전달한다.
목표/예상 초와 개발용 정책 표시를 보여주며 기존 Pleos 출력기를 재사용한다.

## 테스트 / 협의
```sh
.venv/bin/python -B -m unittest tests.test_planning tests.test_selection -v
```
옵션·시간·prefix 원문 보존·중복/부족·미승인 차단·권한·current 호환성·설정 오류를 검증한다.
최적 가중치/한국어 의미 정확도/실제 시간 근접도를 측정한 성과로 주장하지 않는다.
팀 합의 항목: 목표 초·말하기 속도 추정·최소 기사 문장 수·중요도/관심 fallback,
편성 응답 버전·세션 ID 규격·권한 확인 자료 입력 경계.

## 응답 일부 필드 예시 (합성)
```json
{"schema_version":"approved-briefing-v1","fictional_only":true,"playback_requires_user_action":true,"briefing_id":"brief_example","length_option":"중간","policy_status":"development_placeholder_not_team_policy","target_seconds":60,"estimated_seconds":3.8,"delta_seconds":-56.2,"shortage":true,"articles":[{"article_id":"fiction-01","title":"가상 기사","tts_sentences":["사람이 검토한 가상 문장입니다."],"one_line":"가상 한 줄","detail":"가상 전체 요약","source":"자체 작성","mock":true,"sentence_indices":[0],"approved_sentence_count":3,"partial_tts":true,"validation":{"status":"approved","approved":true,"review_required":false}}]}
```
예시는 실제 승인 파일을 대체하지 않으며 저장/재생 테스트 fixture로 위장하지 않는다.
