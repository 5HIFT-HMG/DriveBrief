# AI 파이프라인 품질 점검 (2026-11-13)

PR #5의 main 병합 커밋 `3df0b86`에서 `feature/ai-quality`를 만들었다.
이번 작업은 외부 LLM 호출·뉴스 수집 없이 기존 RSS 메타데이터와 사람이 승인한 가상 기사만 사용했다.
크롤러·원본 DB·승인 절차·기본 가중치·그룹 임계값·시간 설정은 변경하지 않았다.

## 1. 사건 그룹화: 정답 수집 단계

기존 SQLite 214개 항목, 211개 그룹, 가능한 기사 쌍 22,791개 중 60쌍을 추출했다.

| 표본 | 쌍 수 |
|---|---:|
| 기존 알고리즘이 같은 그룹으로 묶은 쌍 | 3 |
| 병합하지 않은 제목 유사도 상위 쌍 | 39 |
| 결정적 해시 순서로 추출한 나머지 대조 쌍 | 18 |

JSON bundle에는 입력 snapshot·설정·SHA256·예측을 보관한다. CSV에는 기사 제목·설명·출처·발행일·URL과 빈 정답 칸만 제공한다. CSV는 예측·추출 계층을 숨기고 해시 순으로 섞어 판정자의 선입견을 줄인다. 스프레드시트 수식 시작 문자는 escape한다.

**현재 사람이 표시한 정답은 0개다. Precision/Recall/F1은 null이며 정확도가 개선됐다고 주장하지 않는다.** 오병합·누락 확정 사례도 없으므로 임계값을 조정하지 않았다. 이 표본은 유사 기사 중심의 편향 표본이며 이후 계산해도 전체 모집단 Recall이 아니다.

backend에서:
```sh
.venv/bin/python -B -m drivebrief_api.quality pairs --count 60 --output results/my-quality-pairs.json
```

생성된 CSV의 `human_label`에 `same_event` / `different_event` / `uncertain`을 입력한다. 동일 주제만으로 동일 사건이라 판단하지 말고 사건·주체·시점·장소를 확인한다. 설명만으로 판단 불가능하면 uncertain으로 남긴다. 확정 라벨에는 reviewer를 기입하고 필요하면 notes에 판단 근거를 적는다. ID와 source_hash는 수정하지 않는다.

```sh
.venv/bin/python -B -m drivebrief_api.quality evaluate --bundle results/my-quality-pairs.json --labels results/my-quality-pairs.csv --output results/my-quality-metrics.json
```

빈 칸·uncertain은 음성 정답으로 취급하지 않는다. 수정된 설정 파일을 `--candidate-config`로 전달하면 같은 snapshot·정답으로 전후 confusion matrix, P/R/F1, false_merge/missed_duplicate ID를 비교한다. 정답 수집 후 개발/검증 표본을 분리해 임계값을 검토해야 한다.

실제 생성한 로컬 파일은 `results/quality-pairs-final.json/.csv`, `quality-pairs-final-unlabeled.json`이다. 실제 RSS 내용이 포함되어 Git에서 제외한다.

## 2. 중요도·편중 진단

기존 점수는 최신성 .35 + 보도량 .15 + 출처 다양성 .20 + 관심 .20 + 품질 .10이다.
실험 설정 `samples/ranking_recency_candidate.json`은 각각 .50/.10/.15/.15/.10이며 **운영 기본값이 아니다**.

고정 기준시각 2026-11-13 12:00 KST, 전체 분야, 상위 20건을 비교했다.

| 측정 | 결과 |
|---|---|
| 기본값 대비 실험 설정의 상위 20건 순위 | 변경 없음 |
| 대표 출처 | SBS 16, 전자신문 4 (SBS 80%) |
| 전체 211그룹 대표 출처 | SBS 113, 전자신문 98 |
| 선정 분야 | 경제·사회·정치·IT·스포츠 각 4 |
| 상위 20건 중 48시간 초과 | 20 |
| 전체 후보 중 48시간 이내 | 0 |
| 상위 20건의 최대 기사 나이 | 약 157.43시간 |
| 개수 부족 | 없음 (211그룹) |

최신 기사 자체가 없으므로 최신성 가중치만 올려도 신선한 기사를 만들 수 없다. 분야 균형과 출처 구성의 상호작용도 있으므로 SBS 비중만으로 오선정이라 단정하지 않는다. 오래된 뉴스 제외/경고 정책과 사용자 선호 정답은 팀 협의가 필요하다.

```sh
.venv/bin/python -B -m drivebrief_api.quality ranking --as-of 2026-11-13T12:00:00+09:00 --candidate-config samples/ranking_recency_candidate.json --output results/my-ranking.json
```

JSON은 pool/선정 출처·분야·날짜·부족 상태, Markdown은 기사별 순위와 다섯 점수 기여도 전→후를 보여준다. 현재 로컬 결과는 `quality-ranking-final.json/.md`이다. 사람의 선호 평가나 최적 가중치 검증은 아니다.

## 3. Pleos 재생시간 실측

기존 PleosSpeechOutput을 decorator로 관찰하며 재생 큐·음성·승인 문장은 바꾸지 않았다.
각 speak 시도 UUID, 세션/기사/문장 인덱스, 문자 특성, 문장 SHA256, 요청/시작/완료 시간을 앱 전용 JSONL에 기록한다. 문장 원문·음성·API 키는 저장하지 않는다.

- 요청→시작 = startup, 시작→완료 = speech, 요청→완료 = 추정 대상.
- 완료 콜백이 있는 실제 Pleos/ko-KR만 분석한다. stop/error/missing_start/mock는 제외한다.
- 늦은/중복 콜백을 차단하고 attempt ID를 중복 제거한다.
- 세션 예상 수만큼 중단 없이 완료한 경우에만 첫 요청→마지막 완료를 전체 실측으로 사용한다.
- 저장 실패가 재생을 중단하지 않으며 프로세스 강제 종료 시 미저장 측정은 유실될 수 있다.

### 기본 계수로 세 옵션을 실제 재생

Pleos Connect v2.1.0 / API34 ARM64 / TTS 의존성 3.3.1, 승인 가상 3기사.
기존 식은 `문자 수 / 5 + 문장당 0.4초`다.

| 옵션 | 제공 문장 | 기존 예상 | 완료 콜백 실측 | 예상−실측 |
|---|---:|---:|---:|---:|
| 짧게 | 3 | 28.60초 | 19.621초 | +8.979초 |
| 중간 | 6 | 55.00초 | 34.470초 | +20.530초 |
| 길게 | 9 | 84.60초 | 53.456초 | +31.144초 |

18개 완료 시도, 중복 제외 9문장을 확보했다. startup 중앙값 29ms(5~256ms)였다.
기존 문자 속도가 이 환경보다 느리게 설정되어 과대 추정했다. startup과 문장당 고정 0.4초는 같은 개념이 아니다.

### 후보 보정과 새 재생 검증

문장별 반복 측정 중앙값으로 음수가 아닌 기울기·절편을 적합했다.
후보는 약 **7.75077자/초 + 문장당 0초**다. 0초는 제한된 표본의 회귀 절편이며 실제 SDK의 쉼을 제거하는 설정이 아니다.

| 평가 범위 | 기존 MAE | 후보 MAE |
|---|---:|---:|
| 9개 문장 중앙값, 학습 적합 | 3.595초 | 0.161초 |
| 기사 하나씩 제외한 3-fold, fold MAE 평균 | 약 3.595초 | 약 0.192초 |
| 계수 고정 후 새 9문장 재생 시도 | 3.628초 | 0.174초 |

기사 holdout은 같은 문장 해시를 학습에서 제외했다. 새 재생은 기존 attempt ID를 제외하고 no-fit로 평가했다. **새 시도도 학습과 같은 9문장**이므로 새로운 기사에 대한 일반화 검증은 아니다.

후보 설정을 로컬 서버 환경변수로만 임시 적용한 중간 편성은 9문장, 예상 52.253초에 실제 52.081초(+0.172초)였다. 같은 새 9문장을 기존 계수로 계산하면 84.600초다. 기존 중간 6문장과 새 중간 9문장은 내용 수가 달라 단순 비교하지 않는다. 실험 후 서버를 기본 설정으로 복구했다.

한글 25~39자, 전체 40~52자, 공백 8~12자, 숫자 0~10자, 문장부호는 모두 1개인 작은 표본이다. 문자 특성별 범위·잔차 상관을 기록했지만 숫자 읽기/문장부호/영문 효과를 분리할 수 없다. 긴 문장·다양한 수치/단위·엔진 버전·기기 조건에서 추가 측정해야 한다. 기본 계수는 변경하지 않았다. 개발 목표 30/60/120초도 확정 정책이 아니다.

이번 측정은 실제 기기 TTS 콜백과 화면 완료를 확인한 결과다. 에이전트가 소리를 직접 청취하거나 음향 파형을 측정한 것은 아니다. 이전 단계의 사용자 청취 확인과 이번 타이밍 검증을 구분한다.

### 측정 수집·재분석

앱 전용 external files의 `speech-timing-v1.jsonl`에 수치만 추가한다. 자동 업로드·운영 텔레메트리는 없다. 삭제/보존 기간·측정 opt-in 정책은 팀 협의 전 과제다.
ADB pull은 현재 사용자10 환경에서 Permission denied였다. 권한/OS를 바꾸지 않고 앱 UID에서 읽는 **명시적 진단 테스트**로 내보냈다.

테스트 APK 설치 후 실제 연결된 사용자 ID에 맞춰:
```sh
adb shell am instrument --user 10 -w -r -e drivebriefExport true -e class com.example.drivebrief.SpeechTimingExportTest com.example.drivebrief.test/androidx.test.runner.AndroidJUnitRunner
```

출력 중 drivebrief_timing_export JSON 배열을 로컬 JSONL로 보관한다. 일반 기기 테스트에서는 이 진단을 실행하지 않는다. 1MB 초과는 거부하므로 보존 정책을 정해야 한다. 해시도 원문과 연계 가능한 메타데이터이므로 공개하지 않는다.

backend에서:
```sh
.venv/bin/python -B -m drivebrief_api.timing_quality --input results/quality-speech-observed.jsonl --output results/my-timing-fit.json --candidate-config results/my-timing-config.json
.venv/bin/python -B -m drivebrief_api.timing_quality --input results/quality-speech-validation.jsonl --training-input results/quality-speech-observed.jsonl --config results/my-timing-config.json --no-fit --output results/my-timing-validation.json
```

18시도 학습 원본·9시도 검증 원본·분석 파일은 로컬 results에만 보관한다. Git에는 분석기와 합성 단위 테스트만 포함한다. SDK dependency와 locale이 혼합된 입력은 거부하며, 같은 dependency여도 실제 voice model/속도 환경 차이를 완전히 식별하지 못한다.

## 4. 요약 검증의 탐지 범위

자체 작성 가상 기사로 정상 1건과 오류 변형 12건을 만들었다. MockProvider만 사용했으며 외부 LLM 성능 평가가 아니다.

| 오류 | 현재 검사 결과 |
|---|---|
| 원문에 없는 숫자 | core 거부 |
| 날짜 구성 변경 | core 거부 |
| 역할이 있는 인물 변경 | core 거부 |
| 무관한 근거 구간 | core 거부 |
| 숫자와 단위의 조합 변경 | 추가 검토 경고 |
| 일부 조직명 변경 | 제한적 suffix 패턴 검토 경고 |
| 부정 누락 / 예정→확정 | 기존 위험 표현 경고, 검토 유지 |
| 역할 없는 인물 혼동 | 특정 인물 오류를 확실히 탐지 못함 |
| 새 숫자 없는 사건 창작 | 의미적 일치 검토 필요 |
| 동일 단위 값들의 관계 뒤바꿈 | 숫자 집합만으로 탐지 못함 |
| 안전 조건·예산 생략 | 미참조 원문 구간을 표시하나 중요도 판단은 사람 몫 |

총 13개 fixture 중 core 거부는 4개다. 나머지에 경고가 있다고 정확성이 입증되거나 승인되는 것은 아니다. 모든 요약은 기존처럼 사람의 검토가 필요하다.

`review inspect` 결과에 `quality_diagnostics`를 추가했다. 주장별 근거 ID·실제 원문, 자동 경고, 미참조 구간을 함께 본다. 원문 포함 검토 문서는 로컬에서만 사용한다. 기존 validation·승인 revision·캐시 정책을 바꾸지 않는 보조 정보이므로 validator version과 기존 승인 상태를 유지했다.

```sh
.venv/bin/python -B -m drivebrief_summary.quality_cases --output results/my-summary-quality.json
.venv/bin/python -B -m drivebrief_api.review inspect --id fiction-01 --output results/my-quality-review-fiction-01.json
```

기존 숫자/날짜/근거 검사에 의미적 entailment 능력이 있다고 간주하면 안 된다. 자동 승인 기능은 추가하지 않았다.

## 5. 테스트·남은 일

- Python 백엔드: 87개 통과. 기존 77개 + 품질 평가/타이밍/검토 진단 10개.
- 기존 크롤러: 5개 통과. 크롤러 코드는 수정하지 않았다.
- Android debug 빌드 및 JVM 단위 테스트: 성공, 10개 통과.
- Pleos 전체 기기 테스트: 35개 통과, 2개 제외. 기본 Android TTS 미지원 진단과 opt-in 측정 export가 제외 대상이다.
- 중간 실행에서 Compose lifecycle 관련 2개 실패를 확인했다. export 진단을 일반 suite에서 분리한 뒤 해당 5개 및 전체 suite를 재실행해 통과했다. 실패 원인을 측정 export 하나로 확정하지 않는다.
- 실제 API·3옵션 순차 재생 및 후보 계수의 새 중간 재생 완료를 확인했다. 이번 작업에서 실제 음향 청취·전화/내비 오디오 실환경·실차 검증은 하지 않았다.

```sh
# backend 디렉터리
.venv/bin/python -B -m unittest discover -s tests
# 저장소 루트
backend/.venv/bin/python -B -m unittest discover -s news_crawler/tests
./gradlew :app:assembleDebug :app:testDebugUnitTest
./gradlew :app:connectedDebugAndroidTest
```

출력 CLI는 기존 결과를 덮어쓰지 않는다. 재실행 시 새 경로를 지정한다. 실제 RSS snapshot·DB·검토 결과·실측 JSONL은 기존 .gitignore로 제외한다.

남은 작업은 정답 라벨 수집/판정자 합의, 독립 검증 표본, 최신 기사 부족 정책, 다양한 TTS 데이터, 보존 정책, 실제 권한 확인된 본문이다. 연동 데이터와 책임 경계는 [협의용 인터페이스 초안](INTERFACES_DRAFT.md)에 정리했다. 기존 API를 호환성 없이 변경하거나 새 운영 규격을 확정하지 않았다.
