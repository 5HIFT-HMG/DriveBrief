# RSS 기본 브리핑과 기사별 상세도

## 현재 기본 경로
일반 홈 → 익명 Auth → read_published_briefing → rss-briefing-v1 → 기존 Pleos 출력기 → 로컬/DB 청취 기록 → OnePaper.
로컬 JSON이나 debug 플래그가 필요하지 않다. 기존 비공개 미리보기와 사람 승인 AI 요약은 별도 기능으로 보존한다.

RSS 자동 처리에는 approved=true 또는 사람 검토 명령을 쓰지 않는다.
validation.status=rss_auto_validated, method=metadata_exact_extract_v1, human_reviewed=false이다.
usage_rights_status=source_terms_not_verified는 이용 권한이 확인됐다는 주장이 아니다.
공모전·시연용이라는 목적도 재이용 허락을 의미하지 않는다. 출처별 이용 조건 확인은 별도 관리 사항이다.

## 선정과 상세도
최근 최대 200건을 기존 Supabase news_articles와 memberships에서 읽는다.
유효 URL·출처·분야·발행시각·최근 5일·길이·HTML 잔여 검사를 통과한 자료만 사용한다.
기존 metadata/group_events/rank_groups/balanced_select와 가중치를 변경하지 않고 최대 25건을 한 번 선정한다.
세 옵션의 catalog_id, article_id 목록, 순서는 동일하다.
현재 관심 분야는 앱에서 공통 25건에 필터를 적용한다. 분야별로 다른 기사 수가 나올 수 있지만 같은 분야의 세 옵션은 같은 순서이다.
사용자별 전체 후보 재선정 API는 이 경로에 새로 만들지 않는다.

- 짧게: 제목 1개 발화 구간
- 중간: 제목과 RSS 설명의 연속 원문 구간 최대 3개
- 길게: 같은 방식 최대 5개

제목은 문법적으로 완결된 문장이 아닐 수 있다. 요약문 생성이 아닌 원문 발화 구간 수이다.
설명 정보가 부족하면 1/3/5개를 억지로 채우지 않는다.
긴 구간을 임의로 자르거나, 없는 접속어·설명·맥락을 추가하지 않는다.
one_line은 제목, detail은 RSS 설명이며 기사 전문 또는 Groq 요약이 아니다.
RSS 응답은 시간 목표·예상시간·approved_sentence_count를 포함하지 않는다.
available_sentence_count는 원문에서 제공 가능한 최대 5개 구간의 수이다.
기존 승인/가상 기사 시간 편성 스키마는 과거 기록과 호환된다.

## 갱신과 실패 보존
backend 가상환경에서 아래 명령은 실제 Supabase를 사용한다.

```sh
.venv/bin/python -B -m drivebrief_api.rss_auto --status
.venv/bin/python -B -m drivebrief_api.rss_auto --dry-run
.venv/bin/python -B -m drivebrief_api.rss_auto
```

마지막 명령은 게시 데이터 쓰기이며 일반 앱의 기본 브리핑을 변경한다.
기존 publish_briefings CLI도 기본 real 경로는 이 자동 처리에 위임한다.
이전 사람 검토 RSS 게시를 명시적으로 사용하려면 --reviewed-rss를 지정한다.
새 스키마를 읽으려면 이 PR의 APK로 업데이트해야 한다. 이전 APK는 rss-briefing-v1을 지원하지 않는다.
기존 공유 DB 수집 동기화가 성공하면 실제 news_crawler/news.sqlite3 경로에서만 backend/.venv의 위 모듈을 호출한다.
임시 테스트 DB와 DRIVEBRIEF_RSS_AUTO=0에서는 호출하지 않는다.
새 스케줄러나 정기 작업은 설치하지 않는다. 기존 수집 주기를 재사용한다.
동일 입력·설정 revision이면 그룹화와 게시를 건너뛴다.
변경 시 세 옵션을 단일 PostgREST batch transaction으로 upsert한다. 일부 옵션만 교체하지 않는다.
빈 입력·잘못된 데이터·처리 실패는 기존 게시를 삭제하지 않는다.
generated_at/latest_source_at/published_at으로 생성·원문·게시 시각을 구분한다.
앱은 발행일이 하루 이상 지난 경우 안내한다. 실시간 자동 push 재생은 하지 않고 새 브리핑 시작 때 최신 게시를 읽는다.
Mac이 꺼져도 이미 게시된 브리핑은 Supabase에서 읽는다. 새 뉴스의 수집·게시까지 계속하려면 별도 서버에서 기존 수집기와 이 Python 환경을 운영해야 한다.
서버 프로세스/스케줄·다중 publisher 잠금·관측·배포는 아직 설치하지 않았다.

## 기록과 QR
기사별 완료는 기존 TTS done 콜백 기준이다. 건너뜀·중단과 구분한다.
최대 25건을 파서/재생/기록에서 처리한다. 로컬·클라우드 기록은 최근 20세션 및 약 440KB 예산을 함께 적용해 오래된 세션부터 보관 범위를 줄인다.
일반 QR의 기존 서버 함수는 승인 스키마·최대 10건만 허용했으므로
supabase/migrations/20261114_rss_auto_share.sql을 SQL Editor에서 한 번 적용해야 한다.
이 migration은 공유 함수만 확장하며 테이블을 초기화하거나 RLS를 공개하지 않는다.
이전 migration을 다시 실행하지 않는다.
공유 snapshot의 approved_sentence_count는 기존 폰 페이지용 표시 호환 필드이며 RSS의 승인 상태가 아니다.
새 available_sentence_count와 content_kind를 함께 제공한다.

노출 범위: 익명 Auth 가입이 가능한 사용자는 게시 RPC를 읽을 수 있다.
기존 폰 페이지는 QR 토큰을 가진 사람이 snapshot을 열 수 있다. 링크 재전달도 가능하다.
토큰은 URL fragment에 있고 서버는 해시·만료·소유자 검사를 유지한다.
이용 조건 미확인 RSS를 앱·공유 페이지에 제공한다는 점은 시연 범위와 별도로 검토해야 한다.
비밀키는 서버 news_crawler/.env에서만 읽고 Android에는 공개용 키·사용자 토큰만 쓴다.

## 테스트
오프라인 테스트에서 실제 접속을 반드시 차단한다.
```sh
SUPABASE_URL= SUPABASE_SECRET_KEY= DRIVEBRIEF_RSS_AUTO=0 .venv/bin/python -B -m unittest tests.test_rss_auto tests.test_rss_playback tests.test_planning tests.test_publish_briefings tests.test_review tests.test_api tests.test_shared_backend tests.test_pipeline tests.test_news_api
```
기기 테스트 RssAutoBriefingTest의 liveRss=true만 실제 일반 앱·Supabase를 사용한다.
liveQr=true는 새 SQL 적용 후 실제 공유 링크 생성까지 확인한다.
테스트 성공과 실제 음성 청취 확인은 구분해 보고한다.

## 검증 결과
- PR #28이 병합된 origin/main 75d6b75에서 개발했다. 기존 .env.example 변경과 .env는 보존한다.
- 관련 Python 58개, Android 단위 23개, 기기 56개 통과. 기존 비공개 입력 전용 1개는 입력 미제공으로 skip.
- 일반 MainActivity를 debug 플래그·파일 주입 없이 실행해 실제 Supabase 게시 25건 수신을 확인했다.
- 실제 TTS 시작·완료 콜백, 일시정지·재개·다음 기사·중단, OnePaper 원문 링크, DB 동기화 및 실제 QR 생성을 확인했다.
- 사용자가 새 공유 SQL을 직접 적용한 후 QR 테스트가 통과했다. 폰 브라우저에서의 실제 렌더링은 별도다.
- 게시 재실행은 unchanged로 반환해 중복 쓰기를 하지 않았다.
- 한 차례 기존 등록 RSS 37개를 수집해 29개 성공/8개 실패(매일경제 유효 기사 없음)를 확인했다.
  공유 DB 변경분 1,609건 전송 뒤 RSS 게시가 자동 갱신됐다. 기존 5일 보관 정책으로 만료 자료 9건이 정리됐다.
  이 수집은 본문·LLM 처리나 새 정기 작업 없이 기존 collect 함수를 한 번 실행한 것이다.
- 수집 후 게시 검사에서도 세 옵션 25건의 ID·순서가 같았다. 짧게는 25건 모두 1구간,
  중간은 21건 3구간/4건 2구간, 길게는 21건 5구간/4건 2구간이었다.
  구성 2026-11-14T01:36:29.470000+00:00, 최신 기사 2026-11-14T01:35:00+00:00 기준이며 이후 갱신 시 달라질 수 있다.
- 재설치 후 일반 실행·중간 25건을 직접 재생했고, 사용자가 실제 한국어 뉴스 음성이 들린다고 확인했다.
- 다중 Mac/서버 publisher의 동시 실행 잠금과 서버 배포는 미구현이다. 현재 운영은 한 publisher를 전제로 한다.
