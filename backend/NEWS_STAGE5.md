# DriveBrief 5단계 개발 기록 — 기존 RSS DB 후보 조회 확장

## 1. 조사 스냅샷 (2026-11-11)

모든 운영 DB 조사는 읽기 전용이며 RSS 재수집/기사 전문 수집을 실행하지 않았다.
- articles: URL PK 기준 214행, 서로 다른 원문 제목 212개, description 공란 0건.
- memberships: IT 100행(고유 URL 98건), 경제/사회/정치/스포츠 각 29행.
- sources: SBS 116 URL, 전자신문 IT 50 URL, 전자신문 SW·AI 50 URL.
  전자신문 두 출처가 공유한 URL이 있어 출처별 합계는 전체 URL 수와 다르다.
- 분류 연결이 없는 article: 0건.
- 최초/최신 발행 시각: 2026-11-04T16:33:30+09:00 / 2026-11-07T12:28:00+09:00.
- 마지막 수집 시각: 2026-11-07T12:39:13.371228+09:00.
- feed_status: 6행, 마지막 상태에서 오류 0·skipped 0.
  이 테이블은 출처별 마지막 상태를 덮어쓰므로 과거 실패가 전혀 없었다는 뜻은 아니다.
- 내_뉴스.json: 2026-11-06 대상, 5개 분야 각 5건 = 25건.
- 같은 날짜의 DB 후보: 경제18/사회8/정치20/IT47/스포츠26 =119건.

articles 필드: url,title,description,published_at,first_seen,last_seen.
memberships: url,category,source. feed_status: feed_url,category,source,last_attempt,
last_success,item_count,skipped,error.
선정 JSON은 여기에 category,source,관심사 score가 붙은 출력 결과다.
본문·이용 허가·AI 요약·청취 상태 필드는 DB에 없다.

## 2. 실제 원인과 기존 구조의 한계

내_뉴스.json은 전체 기사 저장소가 아니라 특정 날짜에 관심사 점수·최신순으로 분야별
최대 5건을 고른 결과다. 이 파일만 앱에 연결하면 DB의 나머지 후보에 접근할 수 없다.
기존 get_articles의 기본 조회도 최근 30일로 제한되므로 오래된 누적 기사를 전체 조회하지 못한다.
RSS는 제공 시점의 항목만 처리하며 이 수집기가 누락된 과거 기사까지 보장하지는 않는다.
날짜/제목/링크가 없거나 잘못된 RSS 항목은 버린다. 현재 RSS 2.0만 지원한다.
description은 RSS 설명이고 기사 전문으로 판정할 수 없다.

기존 URL 정규화 및 URL PK/멤버십 PK는 저장 중복을 막지만, 같은 제목의 다른 URL과
다른 출처 멤버십은 조회 시 중복될 수 있다. 같은 사건의 다른 제목은 의미 기반 중복 제거가 필요하다.
오류 시 기존 데이터를 지우지 않는 fetch/collect 처리와 top-5 알고리즘은 이미 있어 유지했다.
새 RSS 출처 활성화나 수집량 증가를 이번 성과로 주장하지 않는다.

## 3. 재사용 및 구현

news.py에 다음 읽기 기능을 추가했다.
- get_articles의 기존 기본 30일 동작 유지, all_history와 단일/다중 분야 SQL 필터 추가.
- connect_read_only: mode=ro, 파일이 없어도 새 DB를 만들지 않는다.
- get_candidates: 전체 누적 이력, 발행 최신순, 정규화 URL 및 공백/대소문자 정규화 제목 중복 제거.
  숫자·문장부호가 다른 제목을 임의로 같은 사건으로 취급하지 않는다.
- 중복 그룹 연결 시 최신 기사를 대표로 하되 관측된 sources/categories를 유지한다.
- candidate_page: limit/offset, 날짜·분야 필터, 분야별 후보 한도.
- config.json의 limit=5 및 6개 기존 feeds 유지. candidate_limits를 분야별 100으로 별도 추가.

API의 limit은 페이지 크기(기본20, 최대100), candidate_limits는 분야별 후보 풀 상한이다.
per_category_limit=0은 분야별 상한 없이 전체 후보를 페이지로 조회한다.
기존 관심 키워드 선정/내_뉴스.json/HTML 출력은 변경하지 않는다.

새 크롤러를 만들지 않은 이유는 기존 파서·정규화·DB 관계·실패 보존 동작을 재사용해
저장 데이터와 기존 UI 출력 호환성을 유지하기 위해서다.
API 계층이 고정된 news.py 경로를 importlib로 불러온다. monorepo 구조이므로 backend만
단독 배포하면 news_crawler 코드/DB/설정을 함께 제공해야 한다.

## 4. 데이터 흐름 및 API

기존 DB (읽기 전용) -> 기존 news.py 후보 함수 -> NewsRepository -> GET /v1/news
-> Android NewsListClient -> 개발용 실제 뉴스 목록.

예:
- /v1/news?category=IT&limit=20
- /v1/news?date=2026-11-06&category=IT&limit=100
- /v1/news?categories=경제&categories=IT&limit=20&offset=20
- /v1/news?per_category_limit=0&limit=100&offset=100

date는 한국 날짜 YYYY-MM-DD. 단일 category와 다중 categories를 동시에 주면 422.
잘못된 분야/날짜/범위는 422, DB 누락·손상·설정 오류는 원문/경로를 숨긴 503.
정상 빈 DB/범위 밖 페이지는 빈 articles를 반환한다.
DB 스키마·인덱스 변경은 없다. /v1/demo/briefing의 기존 계약도 유지했다.

응답의 article_id는 기존 URL에서 파생한 rss_+SHA256 식별자(새로운 기사 사실이 아님)다.
title,category,source,published_at,description,source_url과 관측된 categories/sources를 전달한다.
content_level=rss_description, summary_status=not_available, ai_eligible=false는 안전 정책 표시다.
본문 부재/외부 AI 처리 권한 미확인/재사용 권한 미확인을 ai_blockers에 명시한다.
가상 TTS 문장이나 임의 AI 요약은 실제 기사에 연결하지 않는다.

## 5. Android

기존 debug 데모 진입 영역에 ‘개발용 실제 뉴스 목록’을 추가했다.
홈 관심 분야를 적용하고 전체/관심 분야/분야별 필터, 제목·출처·KST 발행일, AI 사용 불가 표시,
20건 단위 이전/다음 페이지, 빈 목록, 오류·재시도를 제공한다.
네트워크는 Dispatchers.IO, 연결5초/읽기8초, 응답1MB, 로컬 주소만 사용한다.
실제 뉴스 목록에는 TTS 재생 버튼이나 SpeechOutput 연결이 없다.
기존 가상 AI 브리핑, Mock, TTS, OnePaper와 10/20/30분 UI를 유지한다.
시간 선택은 여전히 실제 편성 기능이 아니다.

## 6. 정량 결과와 DB 보존

- 누적 저장량: 전후 모두 214건(새 수집 없음).
- 신규 전체 후보 조회: URL/제목 중복 제거 후 212건.
- 후보 분야별: 경제29/사회28/정치28/IT98/스포츠29.
- 동일한 2026-11-06 대상 접근 가능 기사: 선정25건 -> 후보119건(4.76배).
  이는 수집량 증가가 아니라 기존 저장 데이터의 접근 범위 확대다.
- IT 목록 API: 반환20건, 전체 IT 후보98건.
- 후보 조회 10회 중앙값: 3.264ms(이번 로컬 DB·warm 조회 측정치). 기존 대비 속도 향상 수치는 아니다.
- 실행 계획은 memberships scan + articles URL 자동 인덱스 + 정렬 임시 B-tree였다.
  현재 규모에서 새 인덱스는 적용하지 않았다. 규모가 커져 병목이 실측되면 별도 승인 후
  category/url 및 발행일 인덱스 마이그레이션을 검토할 수 있다.

운영 DB SHA256:
680633dbe067051f8c7304112a2320a0e53f0c44009309c5891d67d32cd33e06

재현(backend에서):
```sh
.venv/bin/python -B -m drivebrief_api.news_audit
.venv/bin/python -B -m unittest discover -s tests -v
```
원본 크롤러 테스트(프로젝트 루트):
```sh
backend/.venv/bin/python -B -m unittest discover -s news_crawler/tests -v
```

## 7. 추가 RSS 후보 — 승인 전 미적용

기사 본문을 다운로드하지 않고 공식 안내·저작권 정책 및 HTTP HEAD만 확인했다.
HEAD 200은 XML 파싱 성공이나 이용 허가를 의미하지 않는다. RSS 본문을 수집/저장하지 않았다.

1. 행정안전부 보도자료
   - RSS: https://www.mois.go.kr/gpms/view/jsp/rss/rss.jsp?ctxCd=1012
   - 공식 안내: https://mois.go.kr/frt/sub/a08/rss/screen.do
   - 정책: https://mois.go.kr/frt/sub/a08/copyrightPolicy/screen.do
   - HEAD 200, text/xml. 초기 예상 활용은 자료 발견·제목·출처·링크·게시일 확인.
     문서별 공공누리 표시, 제3자 권리, 출처 표시 및 외부 AI 처리 가능 여부를 확인하기 전
     본문 확보/LLM 전송을 허가된 것으로 취급하지 않는다.

2. 경향신문 전체 뉴스
   - RSS: https://www.khan.co.kr/rss/rssdata/total_news.xml
   - 공식 안내·조건: https://www.khan.co.kr/help/help_rss.html
   - HEAD 200, application/xml. 개인 구독 범위의 서비스이며 다수 공유/영리 활용에는 사전 허가가 필요하다고 안내한다.
     개인 로컬 기사 발견용 후보로만 검토하며 앱 서비스 재배포/LLM 입력은 별도 허가 전 미사용.

3. 정책브리핑 RSS는 후보에서 제외
   - 공식 중단 공지: https://www.korea.kr/etc/noticeView.do?newsId=132038885
   - 2026-07-01 저작권 등 권리 보호에 따른 RSS 제공 중단을 확인했다.

어느 출처도 feeds에 추가하거나 정기 수집을 시작하지 않았다.
사용자 승인과 조건 검토를 마친 후에만 새 RSS 대상 추가를 진행한다.
네이버 검색 API는 사용하지 않았으며 그 결과를 AI 입력·저장·가공 경로에 연결하지 않는다.

## 8. 향후 AI 요약 연결

현재 후보 전부는 AI 요약 사용 불가다. RSS 설명을 전문처럼 변환하거나 자동 허가하지 않는다.
본문 확보 -> 외부 AI 처리 허가 -> 요약/재사용 허가 -> 출처/허가 근거 기록 -> 충분성 확인 후
기존 drivebrief_summary의 Article/Rights 입력으로 명시적으로 변환해야 한다.
동일 사건의 의미 기반 중복 제거와 사람의 검토/승인도 별도 과제다.
기존 권한 검사는 완화하지 않았고 Groq/유료 API 호출은 0회다.

## 9. 자소서·면접에 사용할 수 있는 문제 해결 포인트

‘뉴스가 25개밖에 없다’는 현상을 수집 실패로 단정하지 않고 저장 테이블과 선정 산출물을
분리해 조사했다. DB에 214건이 있고 동일 날짜에도 119건이 있다는 것을 확인했다.
원인은 수집기의 부재가 아니라 분야별 5건 출력물을 전체 후보처럼 사용하는 조회 경로였다.
기존 코드를 재사용해 읽기 전용 후보 계층과 페이지 API를 추가하고, 기존 선정 기능을 보존했다.
URL/제목 중복과 의미적 사건 중복을 구분했으며, RSS 공개와 AI 사용 허가도 분리했다.
실제 측정한 접근 가능 기사 수와 DB 해시로 변경 효과·데이터 보존을 입증했다.

주장하면 안 되는 성과: 수집량/요약 정확도/주행 안전성/응답 속도 개선율,
새 출처 운영 성공, 의미 기반 중복 제거 완료, AI 요약 권한 확보.
아직 최신 수집 이후 기사 누락 가능성과 출처별 허가, 대규모 DB 성능, 의미 중복 문제가 남아 있다.

## 10. 최종 검증 결과

- 백엔드 unittest: 52개 통과. 기존 크롤러 unittest: 5개 통과.
- Gradle Sync 성공. :app:assembleDebug 및 :app:testDebugUnitTest 성공(단위 테스트 2개).
- Pleos emulator-5554의 :app:connectedDebugAndroidTest: 25개 통과, 1개 제외.
  제외 항목은 기존 Android 기본 TTS 환경 진단이며 통과로 집계하지 않았다.
- debug APK 설치 후 MainActivity 전면 실행 Status=ok 확인.
- 10.0.2.2를 통해 실제 DB 전체 후보 212건, IT 필터 98건과 기사 카드 표시 확인.
- 로컬 서버 중단 후 ‘뉴스 서버에 연결할 수 없습니다.’ 및 재시도 버튼 표시, 앱 유지 확인.
  서버 재시작 후 재시도로 전체 후보 212건 목록 복구 확인.
- 기존 /healthz 정상, /v1/demo/briefing?allow_unreviewed_fictional=true HTTP 200 확인.
- 최근 앱 Logcat 150개 확인 범위에 FATAL EXCEPTION/AndroidRuntime 오류 없음,
  Vehicle SDK의 door pos = 0 확인. 전체 시간대 오류 부재를 보장하는 검사는 아니다.
- 에뮬레이터 검증 후 운영 DB SHA256도 위 값과 동일. DB/스키마 변경 없음.
- RSS 실제 재수집, 신규 출처 활성화, 실제 기사 AI/TTS 재생은 수행하지 않았다.
- 프로젝트 루트는 Git 저장소가 아니어서 git status 기반 변경 목록 확인은 불가능했다.

서버 실행(backend 디렉터리):
```sh
DRIVEBRIEF_DEMO_ENABLED=1 .venv/bin/python -B -m drivebrief_api
```
127.0.0.1:8000에만 바인딩한다. 에뮬레이터 앱 홈에서 ‘개발용 실제 뉴스 목록’을 선택한다.
전체/관심 분야/IT 필터와 페이지 버튼을 확인하고, 서버 종료 후 재진입하여 오류 화면을 확인한다.
서버를 다시 실행한 뒤 ‘재시도’를 누르면 목록을 복구할 수 있다.
