# 7단계: 메타데이터 사건 후보와 중요도

## 구현
drivebrief_api.selection은 외부 호출 없는 순수 함수다. candidates는 기존 crawler.get_articles의
읽기 전용 전체 메타데이터를 받아 내부 형식으로 변환한다. 기존 /v1/news 계약·수집기는 변경하지 않는다.
현재 작업은 feature/ai-pipeline에서 최신 main(e99471c)을 기반으로 하며 PR #2/#4를 유지한다.

## 알고리즘과 설명 가능성
1. URL tracking 제거·NFKC/공백/대소문자 정규화 제목으로 완전 중복 그룹. 모든 URL ID/분류/출처 유지.
2. 발행 시각 36시간 이내, 제목 숫자 일치, 상충 사건 유형·장소/기업/인물 패턴 제외 조건을 먼저 검사.
3. 제목 문자 bigram Jaccard >=0.55, 제목 공유 토큰 >=3, 설명 토큰 Jaccard >=0.28일 때만 사건 병합.
   명사 추출/한국어 NER 모델이 아닌 보수적 휴리스틱이다. 서술 표현 차이로 누락될 수 있고 오병합도 가능하다.
4. 모든 구성원 쌍이 조건을 만족하는 complete-link 방식으로 연쇄 병합을 제한한다.
5. 대표는 설명/날짜/분류/출처 품질, 최신 시각, ID 순서로 결정한다.
6. 그룹 ID는 구성 기사 ID 정렬의 SHA256. 구성원 변화 시 ID가 바뀌며 영구 사건 식별자는 아니다.

응답에 grouping_reasons(제목/설명 유사도, 공유 토큰, 시간차), related_article_ids를 제공한다.
완전 중복은 시각 제한 없이 제목이 같으면 병합한다. 반복되는 동일 제목의 다른 날짜 사건은 이 정책의 한계다.

## 점수
최종 점수 = 0.35 최신성 + 0.15 보도량 + 0.20 출처 다양성 + 0.20 관심사 + 0.10 품질.
- 최신성: 2^(-기사 경과시간/24h). 누락·잘못된 날짜·미래 날짜는 0.
- 보도량: 언론사별 다른 제목 최대2건 합산 후 전체4건에서 포화.
- 출처 다양성: 언론사3곳에서 포화. 전자신문 IT/SW·AI는 동일 언론사로 정규화.
- 관심사: 선택 분야와 교집합이 있으면1, 아니면0.
- 품질: 제목/설명/과거의 유효 날짜/분류/출처의 유효 비율 평균.
소수 6자리로 각 기여도를 반환한다. 기본값은 검증된 최적 가중치가 아니다.

선정은 관심 일치 그룹을 먼저 처리하고, 같은 분야에 배정한 수 *0.15를 정렬 점수에서 차감한다.
다중 분류는 선택 분야 중 사용량이 적은 분야에 배정한다. 부족하면 다른 분야로 fallback(명시 표시).
관심사가 없으면 전체 분야에서 균형 선정한다. 후보가 부족하면 그대로 적게 반환한다.
동일 입력과 같은 as_of·설정은 순서와 관계없이 같은 결과를 낸다.

## 설정
backend/pipeline_config.json 또는 DRIVEBRIEF_PIPELINE_CONFIG 경로로 교체한다.
임계값/가중치/출처 alias/분야 편중 감점/입력 상한(기본2000)을 조절한다.
상한 초과 시 최신순 제한 및 input_truncated=true를 반환한다. O(n²) 구조라 대규모 최적화는 추후 필요하다.

## API
GET /v1/news/candidates?categories=IT&categories=경제&limit=20&as_of=2026-11-13T12:00:00%2B09:00
- ranked-news-v1: as_of,input_count,processed_count,group_count,articles.
- articles: 대표 article_id,group_id,title,source,categories,published_at,source_url,
  importance_score,score_components,rank,selection_reason,related_article_ids,grouping_reasons.
- metadata_only=true / ai_eligible=false: 후보 선정은 AI 처리/재생 권한을 부여하지 않는다.
- 잘못된 분야/limit/시각은422, DB/설정 오류는 원문을 숨긴503.
- API는 기본 현재 시각을 사용한다. 재현 비교 시 반드시 같은 timezone 포함 as_of를 지정한다.

## 로컬 표본 보고서 (backend에서)
```sh
.venv/bin/python -B -m drivebrief_api.candidates --as-of 2026-11-13T12:00:00+09:00 --output results/stage7-review-final.json
.venv/bin/python -B -m unittest tests.test_selection -v
```
분야별 최대5건씩 25개 URL을 선택하고 부족하면 다른 분야로 보충한다.
보고서는 원래 제목·설명·링크·그룹 이유·순위가 있어 사람 검토에 사용한다. results는 Git 제외.
출력 파일은 덮어쓰지 않는다. 정확도 측정이나 사람 검토를 자동 완료했다고 표시하지 않는다.

## 팀 협의
수집기 입력은 URL/title/description/published_at(timezone)/category/source가 최소 계약이다.
원문이나 권한 정보는 이 계층에서 만들지 않는다. source alias, 사건 정답 표본, 임계값 튜닝,
팀 공통 카테고리와 페이징/대용량 처리 정책을 협의해야 한다.

후속 보수적 제한: 설정의 location_terms에 있는 장소, 회사 접미어(전자/자동차/은행/증권/그룹),
직함 뒤 한글 이름 패턴이 양쪽 제목에서 발견되면서 다르면 병합하지 않는다.
이 역시 완전한 NER가 아니며 미탐/과잉 분리가 가능하다. 상충 장소/회사/인물 회귀 테스트를 추가했다.

## 응답 일부 필드 예시 (합성, 실제 수집 기사 아님)
```json
{"schema_version":"ranked-news-v1","metadata_only":true,"ai_eligible":false,"articles":[{"article_id":"rss_example","group_id":"event_example","title":"[가상] 공원 정비 계획","category":"사회","source":"가상 출처","rank":1,"importance_score":0.704167,"score_components":{"recency":0.3,"coverage":0.0375,"diversity":0.066667,"interest":0.2,"quality":0.1},"related_article_ids":["rss_example"],"source_url":"https://example.test/news"}]}
```
이는 필드 모양의 합성 예시이며 점수 측정 결과가 아니다. 실제 품질 기여도의 최대값은 설정 가중치다.
