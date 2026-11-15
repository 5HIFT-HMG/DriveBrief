# 실제 RSS 브리핑: 이전 비공개 검증 기록

현재 일반 앱의 기본 경로는 [RSS_AUTO.md](RSS_AUTO.md)의 RSS 자동 처리이다.
아래는 PR #28 당시의 별도 비공개/사람 검토 경로이며 기본 실행이 아니다.

## 현재 경계

- PR #21/#23을 그대로 유지한다. 일반 홈은 익명 Auth → read_published_briefing → 승인 파서 → 기존 Pleos 출력기를 사용한다.
- RSS 제목·설명은 기사 전문이나 AI 요약이 아니다. 후보 선정은 이용 권한·사람 승인을 부여하지 않는다.
- 실제 출처의 TTS·재사용 허용 근거가 아직 없으므로 공개 게시는 보류한다.
- 사용자 요청에 따른 비공개 debug 테스트만 허용한다. 원문 전문 수집, 외부 LLM, 자동 승인, Supabase 쓰기는 수행하지 않는다.
- migration은 추가하거나 재실행하지 않는다. 가중치·그룹화·수집기도 바꾸지 않는다.

## 비공개 통합 실행

backend에서 기존 가상환경과 news_crawler/.env 설정을 사용한다. 키를 인자로 넘기지 않는다.

```sh
.venv/bin/python -B -m drivebrief_api.publish_briefings \
  --private-rss-preview --dry-run --limit 200 \
  --preview-output results/private-rss-preview.json
```

파일이 이미 있으면 덮어쓰지 않는다. 다른 파일명을 사용한다.
Supabase GET 한 번으로 최근 최대 200건과 분야·출처를 읽는다.
기존 metadata → group_events → rank_groups → balanced_select → 문장 prefix 편성을 재사용한다.
TTS 문장은 제목과 RSS 설명의 정확한 구간만 사용하며 내용을 생성하거나 재작성하지 않는다.
긴 설명 구간은 중간을 자르거나 이후 문장으로 건너뛰지 않는다. 부족한 분량은 그대로 둔다.
길이 30/60/120초 및 문자 기반 시간 추정은 기존 개발 설정이며 확정 정책·실측 시간이 아니다.

로컬 출력은 Git 제외 대상 results/ 안에서만 생성한다. 스키마는 private-rss-preview-v1,
preview_only=true, publication_allowed=false, needs_review/approved=false이다.
승인 저장소를 만들거나 승인 상태로 변환하지 않는다. 일반 publish/앱 파서는 이 응답을 거부한다.

debug APK를 설치한 후 앱 소유 files/private-rss-preview.json에 위 JSON을 전달하고 다음으로 연다.
USER_ID는 adb shell am get-current-user로 확인한다(현재 Pleos는 10).
실행하지 않은 명령은 검증 완료로 보지 않는다.

```sh
adb push backend/results/private-rss-preview.json /data/local/tmp/drivebrief-private-rss.json
adb shell run-as com.example.drivebrief --user USER_ID mkdir -p files
adb shell run-as com.example.drivebrief --user USER_ID cp /data/local/tmp/drivebrief-private-rss.json files/private-rss-preview.json
adb shell am start --user USER_ID -n com.example.drivebrief/.MainActivity --ez private_rss_preview true
```

일반 런처 실행에는 이 플래그가 없다. release는 플래그와 미승인 응답을 모두 거부한다.
홈의 길이·분야 → 브리핑 시작 → 재생 버튼을 누른다. 자동 재생하지 않는다.
기존 일시정지·재개·다음 문장·다음 기사·중단·완료 콜백 처리를 유지한다.
테스트 문구를 표시하고 Groq 요약으로 표기하지 않는다.
OnePaper는 별도 로컬 저장소(private_rss_preview_history_v1)를 사용한다.
일반 청취 기록과 섞지 않고 클라우드 연결·폰으로 이어보기·QR 생성을 차단한다.
앱 재시작 후에도 같은 debug 진입점에서 저장 기록을 읽되 자동 재생하지 않는다.

## 별도 후속 작업: 기사별 요약 상세도

짧게·중간·길게를 시간 예산 대신 기사별 요약 상세도로 바꾸는 작업은 이 PR에 포함하지 않는다.
현재 옵션 ID, length_seconds, 승인 문장 prefix 편성 및 화면 의미를 유지한다.
후속 작업에서 팀의 상세도 정의·기사 수·승인된 길이별 문장·API 호환성을 먼저 정한 뒤 별도 PR로 진행한다.

## 출처 허용 확인 후의 일반 게시 경로

허용 근거를 임의로 작성하지 않는다. samples/rss-tts-policy.example.json은 빈 템플릿이다.
출처별 source, article_host, tts_allowed, reuse_allowed, basis, confirmed_by, confirmed_at을
실제 확인 후 로컬 .cache/rss-tts-policy.json에 작성한다. 허용값과 확인 시각을 검사한다.

```sh
.venv/bin/python -B -m drivebrief_api.rss_review prepare --limit 200
```

prepare는 로컬 기존 reviews/decisions 형식만 사용하며 needs_review로 저장한다.
본문/외부 LLM 권한과 별개인 RSS 이용 허용만 기록하며 external_llm_allowed는 false로 유지한다.
inspect/decide는 기존 Evidence ID 검증과 동일한 revision 및 사람 확인을 요구한다.
수정된 입력은 승인을 취소하며, 허용 근거가 삭제·변경된 결과는 게시를 차단한다.

```sh
.venv/bin/python -B -m drivebrief_api.rss_review inspect --id ARTICLE_ID --output results/rss-review.json
.venv/bin/python -B -m drivebrief_api.rss_review decide --id ARTICLE_ID --reviewer REVIEWER \
  --revision INSPECT_REVISION --decision approved --confirm-human-review
.venv/bin/python -B -m drivebrief_api.publish_briefings --namespace real --reviewed-rss --dry-run
```

실제 source 권한 확인 및 사람 승인 전에는 위 검토·승인 명령을 실행하지 않는다.
이번 작업에서는 실제 RSS의 준비·승인·게시를 실행하지 않았다.
실제 publish는 별도 DB 쓰기 승인 후에만 수행한다. 빈 편성은 기존 게시 행을 삭제하지 않는다.
일반 응답은 approved-briefing-v1을 유지하고 fictional_only=false/content_kind=rss_metadata로 구분한다.
명시적 승인·출처 URL·RSS 표식이 없는 실제 데이터는 앱이 거부한다.
기존 가상 기사 형식은 그대로 지원한다. 실제 기사 전문 AI 요약 권한 검사는 완화하지 않는다.

## 검증 명령

```sh
.venv/bin/python -B -m unittest tests.test_rss_playback tests.test_planning tests.test_publish_briefings tests.test_review -v
```

Android 관련 클래스: HomeBriefingTest, RssBriefingTest, SupabaseNewsTest,
SessionCheckpointTest, ApprovedBriefingTest, DemoBriefingClientTest, DemoBriefingUiTest,
SessionStorageTest, PipelineSessionUiTest.
실제 RSS 음성 테스트는 RssBriefingTest의 privateRssBundle(base64 JSON)을 명시적으로 전달할 때만 실행한다.
실제 청취 확인과 TTS 시작·완료 콜백 확인은 구분한다.
익명 가입·공개 QR는 실제 DB 쓰기를 피하기 위해 fake HTTP 계약 테스트로 확인한다.

## 변경 파일

| 영역 | 파일 및 목적 |
|---|---|
| RSS 검토 | drivebrief_api/rss_review.py(신규), samples/rss-tts-policy.example.json(신규): 명시적 허용 근거·기존 사람 검토 연결 |
| 비공개 편성 | drivebrief_api/private_preview.py(신규), planning.py, pipeline_models.py: 미승인 preview와 승인 결과 분리, 기존 선정 재사용 |
| 게시 | drivebrief_api/publish_briefings.py: private dry-run, 승인 RSS 경로, namespace 검증, 빈 편성 삭제 방지 |
| 앱 수신 | app/src/main/java/com/example/drivebrief/data/DemoBriefingClient.kt, CloudBriefingLoader.kt, PrivateRssPreviewLoader.kt(신규): 출처·승인 검증 및 debug 파일 로더 |
| 앱 진입·출력 | app/build.gradle.kts, MainActivity.kt, audio/PleosSpeechOutput.kt: debug 진입, BuildConfig, 빠른 취소 후 SDK 정리 대기 |
| 기록·표시 | data/SessionHistory.kt, ui/DriveBriefApp.kt, DemoBriefingScreen.kt, SessionPaper.kt: 미승인 표시·독립 로컬 기록·QR 차단 |
| 테스트 | backend/tests/test_rss_playback.py(신규), test_publish_briefings.py, test_pipeline.py; app/src/androidTest/java/com/example/drivebrief/RssBriefingTest.kt(신규) |
| 문서 | README.md, backend/STAGE8.md, supabase/README.md, 본 문서 |

앱 파일의 data/ui/audio 경로는 app/src/main/java/com/example/drivebrief/ 기준이다.
news_crawler/.env.example은 작업 전부터 있던 사용자 변경이며 수정하거나 되돌리지 않았다.
뉴스 수집기·그룹화·가중치·LLM 요약 검증·Supabase SQL은 변경하지 않았다.

## 이번 로컬 검증 결과

- 실제 RSS 200건 GET → 짧게 4건/5문장/27.6초, 중간 8건/9문장/56.0초, 길게 10건/14문장/109.8초.
  초 단위 값은 추정이며 실측 발화시간이 아니다. 실행 시점의 데이터에 따라 달라진다.
- published_briefings는 조회 시 0건이었다. 실제 RSS 승인·게시·migration 실행은 하지 않았다.
- 최초 연동에서 Gradle Sync, assembleDebug, Android 단위 13개, Pleos 기기 관련 테스트 39개 통과.
- 최신 origin/main(3ee5652) 반영 후 assembleDebug, Android 단위 23개, Pleos 기기 관련 테스트 52개 통과.
  PR #25의 기어별 OnePaper 전환·QR 제한과 PR #27의 브리핑 단위 오디오 포커스·안내 후 재개를 보존했다.
  비공개 테스트의 정차 후 표시 대기 정보도 별도 로컬 저장소로 분리한다.
  실제 RSS 테스트는 main의 종료 후 자동 화면 전환에 맞춰 중단·완료 상태와 기록 복원을 확인한다.
- 기기 테스트에는 실제 RSS 4건의 재생 제어·완료 콜백·Activity 재생성·디스크 기록 복원·로컬 OnePaper가 포함된다.
- 실제 음성 청취는 사용자가 현재 확인할 수 없어 미확인이다.
- 빠른 stop→다시 재생에서 SDK의 지연 stop이 새 발화를 중단하는 문제를 재현했다.
  기존 출력기에서 취소 후 300ms 정리 대기와 세대 검사를 적용해 이 기기의 재검증을 통과했다.
  SDK의 공식 정지 완료 보장값을 뜻하지 않으며 다른 장치에서 추가 검증이 필요하다.
- Python 관련 테스트 49개 통과. 테스트 실행은 아래처럼 접속 환경변수를 비워 실행한다.
  기존 test_pipeline이 수집 후 자동 동기화하는 부작용을 발견해 테스트에서 네트워크를 차단했다.
  최초 실행이 전송한 합성 fixture 1건은 사용자 삭제 승인 후 URL·발행시각·내용·출처를 대조해 삭제했다.
  삭제 1건, 해당 URL·시각 잔여 0건을 확인했다. 최초 동기화 로그의 보관 정책 정리 건수는 0건이었다.

```sh
SUPABASE_URL= SUPABASE_SECRET_KEY= .venv/bin/python -B -m unittest tests.test_rss_playback tests.test_planning tests.test_publish_briefings tests.test_review tests.test_api tests.test_shared_backend tests.test_pipeline tests.test_news_api
```
