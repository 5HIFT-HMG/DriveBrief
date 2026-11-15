# DriveBrief AI (차간신문) 개발 인수인계

**기준일:** 2026년 11월 12일  
**진행 상태:** 6단계 구현 및 통합 테스트 완료, 7단계 개발 예정

**GitHub:** https://github.com/songhaaa/DriveBrief

## 1. 프로젝트 개요

DriveBrief AI는 차량 운전자를 위한 개인화 AI 뉴스 브리핑 서비스다.

운전자가 관심 분야(경제, 사회, 정치, IT, 스포츠)와 브리핑 길이(짧게·중간·길게)를 선택하면 관련 뉴스를 선정하고, AI가 요약한 내용을 차량에서 음성으로 전달한다. 운행 종료 후에는 OnePaper에서 뉴스 요약과 청취 기록을 확인하는 것을 목표로 한다.

### 기술 스택

| 영역 | 기술 |
|---|---|
| Android 앱 | Kotlin, Jetpack Compose |
| 차량 음성 | Pleos On-device TTS |
| 백엔드 | Python, FastAPI |
| 뉴스 수집 | RSS, Python |
| 데이터 저장 | SQLite |
| AI 요약 | Groq API, GPT-OSS 20B |
| 요약 검증 | Pydantic, Evidence ID 기반 근거 연결 |
| 형상 관리 | GitHub |

## 2. 단계별 개발 현황

| 단계 | 주요 개발 내용 | 상태 |
|---|---|---|
| 1단계 | Android 앱 UI, 관심 분야 및 브리핑 길이 선택, Mock 뉴스 화면 | 완료 |
| 2단계 | Pleos On-device TTS, 재생·일시정지·건너뛰기 | 완료 |
| 3단계 | RSS 뉴스 수집, SQLite 저장, 중복 제거 및 조회 | 완료 |
| 4단계 | Groq 기반 AI 요약, 근거 ID 검증, SQLite 캐시 | 완료 (가상 기사) |
| 5단계 | FastAPI와 Android 연결, 실제 RSS 목록 조회 및 단일 AI 데모 재생 | 완료 |
| 6단계 | 기사 검토·승인, 승인 API, 여러 뉴스 연속 재생 및 통합 테스트 | 완료 (가상 기사) |
| 7단계 | 뉴스 중요도 선정, 동일 사건 중복 제거 | 예정 |
| 8단계 | 관심 분야 및 짧게·중간·길게 맞춤 브리핑 편성 | 예정 |
| 9단계 | 실제 청취 기록과 OnePaper 연결 | 예정 |
| 10단계 | 내비게이션 ETA 연동, 서버 배포, 실차 테스트 | 예정 |

## 3. 현재 구현된 주요 기능

### 뉴스 수집 및 조회

- RSS를 이용한 뉴스 수집
- SQLite 데이터 저장
- 제목 및 URL 정규화 기반 중복 제거
- 분야별 뉴스 필터링, 최신순 정렬, 페이지 조회
- FastAPI `GET /v1/news`
- Android 실제 뉴스 목록 표시

### AI 요약 파이프라인

- Groq GPT-OSS 20B를 이용한 구조화된 뉴스 요약 모듈
- TTS 문장, 한 줄 요약, 상세 요약 생성
- 기사 원문 분할 및 Evidence ID 생성
- 요약 문장과 원문 근거 연결 검증
- 숫자, 날짜, 인물, 부정 및 확정 표현 일부 검사
- SQLite 요약 캐시
- 검증 결과를 `needs_review`로 저장

현재 실제 Groq 요약 실험은 자체 작성 가상 기사에서 수행했으며, 6단계 통합 테스트에는 Mock 요약을 사용했다.

### 사람의 검토 및 승인

- 기사 원문과 요약 결과 비교
- 승인, 반려, 수정 후 승인 지원
- 승인 이력을 별도 SQLite에 저장
- 원문 또는 요약 변경 시 기존 승인 무효화
- 승인된 기사만 일반 브리핑 API에서 제공
- FastAPI `GET /v1/briefings/current`

### Android 음성 브리핑

- 승인된 기사 목록 조회
- Pleos 한국어 TTS 재생
- 여러 기사 자동 순차 재생
- 일시정지 및 재개
- 다음 문장 및 다음 기사
- 재생 중단
- 전체 브리핑 완료 상태 표시

## 4. 6단계 최종 검증 결과

2026년 11월 12일 기준:

- 가상 기사 3건의 검토 및 승인 완료
- FastAPI에서 승인된 기사 3건 반환 확인
- 총 9개 TTS 문장의 연속 재생 확인
- Pleos 차량용 에뮬레이터에서 음성 재생 확인
- 일시정지, 재개, 다음 문장, 다음 기사, 중단 동작 확인
- 마지막 문장의 TTS 완료 콜백 및 전체 완료 화면 확인
- Android 기기 테스트 30개 통과, 1개 제외
- 제외 항목은 Android 기본 TTS 환경 진단이며 Pleos 전용 TTS는 정상 작동 확인

**주의:** 이 검증은 실제 뉴스가 아닌 자체 작성 가상 기사 및 Mock 요약 기반이다.

## 5. 주요 프로젝트 구조

```text
DriveBrief/
├── app/
│   └── src/main/java/com/example/drivebrief/
│       ├── ui/
│       │   ├── DriveBriefApp.kt
│       │   └── DemoBriefingScreen.kt
│       ├── data/
│       │   └── DemoBriefingClient.kt
│       └── audio/
│           └── PleosSpeechOutput.kt
│
├── backend/
│   ├── drivebrief_api/
│   │   ├── app.py
│   │   ├── news_repository.py
│   │   └── review.py
│   ├── drivebrief_summary/
│   │   ├── service.py
│   │   ├── providers.py
│   │   ├── validation.py
│   │   └── models.py
│   ├── samples/
│   │   └── pipeline_articles.json
│   └── STAGE6.md
│
├── news_crawler/
└── README.md
```

세부 디렉터리 및 실행 명령은 GitHub의 최신 README와 `backend/STAGE6.md`를 참고한다.

## 6. 개발 환경 및 실행

개발 환경은 macOS, Android Studio, Python 가상환경이다.

프로젝트 위치:

`/Users/kimsongha/AndroidStudioProjects/DriveBrief`

백엔드 실행 예시:

```bash
cd /Users/kimsongha/AndroidStudioProjects/DriveBrief/backend

DRIVEBRIEF_DEMO_ENABLED=1 \
.venv/bin/python -B -m drivebrief_api
```

로컬 API:

- `http://127.0.0.1:8000/healthz`
- `http://127.0.0.1:8000/v1/news`
- `http://127.0.0.1:8000/v1/briefings/current`

Android 에뮬레이터에서는 호스트 컴퓨터의 백엔드에 `10.0.2.2:8000`으로 접근한다.

검토 및 승인 절차는 `backend/STAGE6.md` 참고.

로컬 DB, API 키, 가상환경 및 일부 실행 결과 파일은 GitHub에 포함되지 않으므로 새 개발 환경에서는 별도 설정이 필요하다.

## 7. 다음 개발 계획

### 7단계 — 뉴스 선정 및 중복 기사 처리

**목표:** 수집한 뉴스 중 브리핑에 포함할 기사를 자동 선정한다.

주요 작업:

1. 관심 분야별 뉴스 후보 선정
2. 날짜 및 최신성 반영
3. 중요도 점수 산정
4. 같은 사건을 다룬 중복 기사 식별
5. 중복된 사건에서 대표 기사 선정
6. 선정 이유 및 점수 관리
7. FastAPI 연동 및 단위 테스트

기존 RSS 메타데이터를 활용해 우선 구현한다. 실제 기사 전문을 외부 LLM으로 전송하지 않는다.

### 8단계 — 시간 맞춤 브리핑

**목표:** 사용자가 선택한 길이(짧게·중간·길게)에 맞는 음성 브리핑을 제공한다.

주요 작업:

1. 기사별 TTS 예상 재생시간 계산
2. 선택 길이에 따른 뉴스 개수 결정
3. 관심 분야 및 중요도 기반 편성
4. 기사별 요약 길이 조정
5. 실제 재생시간과 예상시간 오차 검증

### 9단계 — OnePaper 연동

**목표:** 브리핑 종료 후 실제 세션 기록을 확인한다.

주요 작업:

1. 브리핑 세션 ID 관리
2. 기사별 재생 완료·중단 상태 저장
3. 북마크 저장
4. 한 줄 및 상세 요약 표시
5. 원문 출처 링크 연결
6. 실제 청취 내역 기반 OnePaper 구성

### 10단계 — 실서비스 통합

**목표:** 실제 차량 환경에서 사용할 수 있는 서비스로 확장한다.

주요 작업:

1. 이용 권한이 확인된 실제 기사 본문 확보
2. 실제 뉴스 → Groq 요약 → 검토 → 음성 재생 연결
3. 백엔드 서버 배포 및 인증·보안 강화
4. 내비게이션 ETA 연동
5. 오디오 포커스 및 차량 UI 안정성 검증
6. 실제 차량에서 사용성 및 재생 테스트

## 8. 다음 개발자가 반드시 알아야 할 사항

**첫째, 실제 RSS 뉴스와 AI 브리핑은 아직 완전히 연결되지 않았다.**

RSS 목록을 조회하는 기능과 승인된 가상 기사를 음성으로 재생하는 기능은 존재하지만, 실제 뉴스를 자동으로 요약하고 재생하는 서비스는 미완성이다.

**둘째, AI 요약 자동 검증은 완전한 사실 검증이 아니다.**

Evidence ID, 숫자, 날짜 등을 확인하더라도 요약의 의미적 정확성이 보장되지는 않는다. 따라서 승인 절차를 유지해야 한다.

**셋째, 기존 모듈을 최대한 재사용해야 한다.**

뉴스 수집기, AI 요약 모듈, FastAPI, Pleos TTS는 이미 구현되어 있다. 새 모듈을 중복 개발하기보다 기존 구조를 확장한다.

**넷째, 실제 기사 이용 권한을 확인해야 한다.**

RSS에 기사가 노출된다는 사실만으로 전문 수집, 외부 AI 전송, 요약 재배포까지 허용되는 것은 아니다.

**다섯째, 미완성 기능을 완료된 기능으로 기록하면 안 된다.**

Mock 요약, 실제 Groq 요약, 승인된 가상 데이터, 실제 뉴스를 명확히 구분한다.

---

## 9. 현재 인수인계 기준

**현재:** 6단계 완료  
**다음 작업:** 7단계 뉴스 선정 및 중복 기사 처리  
**우선 확인할 문서:** `README.md`, `backend/STAGE6.md`  
**소스코드:** https://github.com/songhaaa/DriveBrief

다음 개발자는 기존 GitHub 저장소를 확인한 후 7단계부터 개발하면 된다.
