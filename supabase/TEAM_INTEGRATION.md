# 다른 기능과 연결할 때의 뉴스 DB 계약

수집/공유 DB 연동만 담당하며 다른 구현자의 요약·재생 로직은 변경하지 않는다.

- 프로젝트: `https://tbffvwmvamwysgvnsfns.supabase.co`
- 기사 원본 키: `news_articles.url` (canonical URL)
- 앱 기사 ID: `rss_` + URL UTF-8 SHA-256 앞 24자리
- 기사 필드: `title`, `description`, `published_at`, `first_seen`, `last_seen`
- 분야·출처 관계: `news_memberships(url, category, source)`
- 앱 조회: `POST /rest/v1/rpc/read_news`, `p_categories`, `p_offset`, `p_limit`
- 인증: publishable API key + 로그인한 사용자 Bearer token, `news_demo_members` 허용 목록 필요
- 앱에 서버 secret key를 넣지 않는다.

공유 뉴스는 **발행 후 5일/최대 1만 건**이다. 해당 범위 밖의 뉴스는 삭제될 수 있다.
청취 기록·북마크·OnePaper가 원문 기사의 영구 존재에 의존하면 안 된다.
이력에는 최소 제목·URL·발행일·당시 확정된 요약을 스냅샷으로 남기거나, 별도 아카이브 정책을 합의한다.
사용자 이력에 기사 삭제 CASCADE를 연결하지 않는다.
요약 결과 테이블을 붙일 때에는 다른 구현자의 실제 출력 스키마와 승인 상태를 확인한 뒤 어댑터를 작성한다.
현재 RSS 설명은 전문이나 승인된 요약이 아니다. AI 처리 가능/승인 여부를 임의로 true로 바꾸지 않는다.

PostgREST 테이블 GET은 서버 측 기본 행 제한이 있으므로 전체 자료가 필요하면 페이지를 나눠 조회한다.
앱 후보 조회는 분야별 100건/페이지 20건을 적용하므로 전체 저장 건수와 표시 가능한 후보 수가 다를 수 있다.
