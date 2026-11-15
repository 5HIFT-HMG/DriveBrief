# GitHub 공개 준비 기록 (2026-11-12)

## 확인한 범위
- GitHub 인증 재확인 성공. 원격은 songhaaa/DriveBrief, 기본 브랜치 main.
- 기존 원격은 초기 커밋 44f645f와 제목만 있는 README.md로 구성.
- 기존 커밋을 fetch해 로컬 main의 부모 이력으로 유지. force push/이력 재작성 없음.
- 로컬 README.md와 .gitignore를 유지하고 프로젝트 소스·테스트·문서를 추가.
- 실제 수집 DB/JSON/HTML, AI 결과, 환경변수, 가상환경, IDE 설정, 빌드/캐시는 공개 제외.
- 실제 데이터 파일 삭제 없음. 코드 라이선스를 임의로 부여하지 않음.
- 알려진 키 패턴 검사에서 발견 없음. 패턴 검사는 모든 비밀정보 부재를 보장하지 않음.
- 초기 원격 이력에는 제목 한 줄 README만 있으며 비밀정보 없음.

## 테스트
- Python 백엔드 52개 통과, 크롤러 5개 통과 (이번 공개 준비 중 재실행).
- Android assembleDebug / testDebugUnitTest 성공.
- connectedDebugAndroidTest는 연결 기기 없음으로 실행 실패. 통과로 집계하지 않음.
- 이전 Pleos 기기 검증 결과는 README 및 backend 개발 기록과 구분.

## 새 체크아웃 주의
- 실제 뉴스 DB 및 Groq 결과가 없으므로 해당 API는 503을 반환할 수 있음.
- API의 합성 fixture 테스트, Mock 요약 CLI, Android Mock UI는 별도 경로로 제공.
- Mock CLI 결과를 Groq 결과로 위장해 데모 API에 연결하지 않음.
- 뉴스 수집·실제 LLM 호출·정기 작업·배포를 자동 실행하지 않음.

커밋 및 push의 실제 완료 여부·최종 SHA는 작업 완료 보고와 GitHub 커밋 이력에서 확인한다.
