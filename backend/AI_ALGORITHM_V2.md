# AI 알고리즘 v2 실험·검증 기록

기준: PR #6이 main에 병합된 `d9df157`에서 `feature/ai-algorithm-v2` 생성.
평가일: 2026-11-13. 모델 설치·외부 LLM 호출·RSS 재수집은 하지 않았다.

## 적용 범위

**실제 반영:** 평가 CLI, 사람 라벨용 자료, 주장–근거 보조 진단, 고정 TTS 계수의 새로운 문장 검증 도구, opt-in 기기 진단 테스트.

**실험 후보:** 조사 정규화 그룹화, 보도량/다양성 가중치 및 균형 감점 조합, 최소 맥락 prefix + 배낭 편성. 기존 서비스 알고리즘으로 교체하지 않았다.

**유지:** 크롤러·Android main 소스/UI·OnePaper·기존 API·DB·승인 기록·기본 계수/가중치/임계값. 편성 입력은 여전히 승인된 가상 자료만 허용한다.

## 알고리즘별 비교

| 항목 | 기존 방식 | 확인된 문제 | 후보/반영 사항 | 전→후와 한계 |
|---|---|---|---|---|
| 그룹화 | 제목 2-gram/설명 token Jaccard, 충돌 검사, complete-link | 자체 작성 조사 변형에서 공통 token 부족으로 분리 | 원래 exact dedup 유지 후 조사 정규화된 비교를 시간 조건이 있는 complete-link에만 사용 | 합성 5사례 정답 일치 4→5. 실제 RSS 정답 0이므로 실제 P/R/F1 없음 |
| 중요도 | .35/.15/.20/.20/.10, 균형 감점 .15 | 현재 후보가 모두 오래됐고 단일 출처 사건이 대부분. 보도량·다양성 기여 중복 가능 | .35/.05/.15/.25/.20 및 감점 .075 비교, pooled NDCG/P@K 도구 | 관심 IT·사회 상위20 순위 변화0. 실제 중요도 개선 증거 없음 |
| 주장 검토 | 숫자 집합·날짜·일부 인물·원문 ID | 같은 수치를 다른 대상에 붙여도 기존 core 통과 | 대상–수량, 조직–역할–인물, 조건/부정/확정, 다중 구간 결합 경고 | 기존 수치 대상 교환 사례에 구체 경고 추가. 새 targeted fixture6개에서 지정 경고6개. 실제 LLM 정확도 아님 |
| 길이 편성 | 첫 문장 우선 + 추가 prefix round-robin | 조건이 두 번째 문장에 있으면 짧은 편성에서 빠짐 | 승인 prefix 다중 선택 배낭 + 검토된 최소 prefix 제약 | 합성 짧게 조건 누락 기사1→0, 기사3→2. 의미적/사용자 품질 평가는 아님 |
| TTS | 5자/초+.4초, 실험 후보7.75077자/초 | 이전 검증이 같은 9문장 반복이었음 | 학습 해시·기사 ID·attempt ID와 분리된 새12문장, 계수 고정 | 실제 Pleos MAE3.237→.461초, RMSE3.324→.611초. 한 기기·작은 표본 |

## 1. 그룹화 평가와 검토 자료

이전 `results/quality-pairs-final.json/.csv`의 동일한 snapshot/60쌍을 재사용했다.
사용자가 아직 정답을 작성하지 않았다고 확인했다. 기존 병합3쌍·유사 미병합39쌍·대조18쌍에 자동 정답을 넣지 않았다.

`algorithm_evaluation pairs`는 원문 메타데이터·시간차·기존 pair match·후보 판단을 JSON 감사자료로 저장한다. 별도 Markdown은 예측을 숨기고 양쪽 제목·출처·시각·RSS 설명·링크를 보여준다. 실제 기사 내용이 있는 결과는 results 아래 로컬에만 둔다.

- 실제 60쌍에서 후보와 기존 판단 차이: **0쌍**, 양쪽 모두 병합3쌍.
- 실제 오병합/누락 확정: **미판정**.
- 동일 사건/동일 주제, 속보/후속 보도 경계를 사람이 판정해야 한다.
- 날짜·장소·기업·사건 차이가 의심되어도 메타데이터만으로 정답을 추측하지 않는다.
- 원래 CSV에 `same_event / different_event / uncertain`, reviewer, notes를 작성한다.
- uncertain/빈 값은 음성 정답이 아니다. 기존 evaluate의 snapshot/중복/판정자 검사를 재사용한다.
- 표본은 유사 기사 중심으로 추출되어 모집단 Recall을 대표하지 않는다.

후보는 3자 이상 한국어 어근 뒤의 제한된 조사 suffix만 처리한다. 형태소 모델이 아니며 단어 자체를 잘못 바꿀 위험이 있다.
처음 실험한 단순 title 치환은 정규화된 제목이 exact key가 되어 시간 검사를 우회할 수 있어 제외했다. 현재는 **원래 제목/URL로 exact unit을 만든 뒤**, 정규화 비교를 시간·개체·수치 검사와 함께 complete-link에만 적용한다. 입력 ID 순서를 정렬해 결과 설명의 재현성도 확보했다.

자체 작성 5사례는 조사 변형 동일 사건, 다른 날짜, 다른 장소, 다른 행동, 서로 다른 수치를 포함한다. 4→5는 이 작은 회귀 fixture에서의 일치 수이며 실제 RSS 성능이 아니다. 임계값은 튜닝하지 않았다.

backend에서:
```sh
.venv/bin/python -B -m drivebrief_api.algorithm_evaluation pairs --bundle results/quality-pairs-final.json --labels results/quality-pairs-final.csv --output results/my-v2-pairs.json
```

동시에 생성된 Markdown으로 검토하고 **기존 CSV**에 정답을 입력한 후 새 출력 경로로 재실행한다.
실제 라벨 이후에만 전후 P/R/F1을 계산한다. 정규화 후보가 새로 놓치는 오병합과 속보/후속 관계는 별도의 판정 메모로 분석해야 한다.

## 2. 중요도와 사람 순위 평가

실험 가중치와 균형 감점은 `samples/algorithm_v2_candidate.json`에서 바꿀 수 있다. 이 파일은 서비스 기본 설정이 아니며 실험기는 이 파일의 weights와 balance_penalty만 사용한다.

비교는 고정 시각 `2026-11-13T12:00:00+09:00`, 관심 분야 `IT·사회`, K=20이다.
이전 문서의 전체 분야 평가(SBS16/전자신문4)와 조건이 다르므로 혼동하지 않는다.

| 지표 | 기본 | 후보 |
|---|---:|---:|
| 순위 위치 변화 | 기준 | 0 |
| 사회 / IT | 10 / 10 | 10 / 10 |
| SBS / 전자신문 | 10 / 10 | 10 / 10 |
| 관심 일치율 / fallback | 100% / 0 | 100% / 0 |
| 단일 raw 출처 그룹 | 19/20 | 19/20 |
| 48시간 초과 | 20/20 | 20/20 |
| 기사 나이 min / median / max | 143.53 / 145.57 / 162.87시간 | 동일 |

전자신문 raw source는 IT5·SW/AI5다. 이들은 기존 alias 정책에서 같은 언론사로 취급된다.

점수 기여도 평균:
| 항목 | 기본 | 후보 |
|---|---:|---:|
| 최신성 | .004658 | .004658 |
| 보도량 | .037500 | .012500 |
| 출처 다양성 | .066667 | .050000 |
| 관심 | .200000 | .250000 |
| 품질 | .100000 | .200000 |

현재 표본에서는 보도량·다양성 항목의 기여가 거의 일정해 가중치 변화가 순위를 바꾸지 않았다.
선호 분야 우선은 기존 정렬의 hard priority이므로 관심 가중치만 바꾼 효과라고 해석하면 안 된다. 감점까지 함께 바꾼 후보는 조합 실험이며 개별 요인의 인과 효과도 아니다.

단독 기사 불이익, 다수 출처 보도의 이중 보상, 출처 집중, 과거 중요 뉴스와 최신성의 균형은 실제 중요도 라벨이 있어야 판단할 수 있다. 최신 기사가 없는 입력에 가중치 조정만 적용해 수집 문제를 해결할 수 없다. 뉴스 부족/관심 분야 부족·fallback·평균 기여도·나이 분포는 보고서로 확인한다.

### 사람 라벨과 지표
```sh
.venv/bin/python -B -m drivebrief_api.algorithm_evaluation ranking --bundle results/quality-pairs-final.json --as-of 2026-11-13T12:00:00+09:00 --categories IT 사회 --output results/my-v2-ranking.json
```

- JSON: 두 방식의 순위·점수·선정 이유·진단.
- Markdown: 제목·출처·발행일·점수·기여도·선정 이유 비교표.
- CSV: 두 상위 목록의 합집합. 순위를 숨기고 기준시각·관심 분야·제목·출처를 제시한다.
- relevance: 0(관련/중요성 낮음), 1(약함), 2(중요), 3(매우 중요), 또는 uncertain. 이 기준은 실험용이며 판정자 합의가 필요하다.
- reviewer와 판정 근거를 작성한다. pool 해시는 목록·시각·관심 분야·K에 묶여 다른 조건의 라벨 오사용을 차단한다.

```sh
.venv/bin/python -B -m drivebrief_api.algorithm_evaluation ranking-evaluate --bundle results/my-v2-ranking.json --labels results/my-v2-ranking.csv --output results/my-v2-ranking-metrics.json
```

전체 pool을 판정하기 전에는 지표를 반환하지 않는다. NDCG@K는 gain `2^grade-1`, discount `log2(rank+1)`, ideal은 **판정된 합집합 안에서** 계산한다. Precision@K는 grade>=2 개수/K다. 전체 pool에 관련 기사가 없으면 NDCG는 null이다.
현재 pool20개·판정0개로 NDCG/P@K를 측정하지 않았다. 전체 RSS 모집단의 최적 순위 성능으로 해석하지 않는다.

## 3. 사실·관계 진단

기존 core 검증·validator version·캐시·사람 승인 절차는 그대로다.
`quality_diagnostics.diagnostic_version`은 `human-quality-warnings-v2`이며 기존 필드에 관계 진단을 추가한다. 실제 서비스 API에 검토 원문/내부 진단을 노출하지 않는다.

추가 경고:
- 명시적 `대상은/는/이/가 수치+단위` 관계의 수치 불일치.
- 한 조직·역할에 연결된 인물을 다른 조직의 인물로 바꾼 경우.
- 원문에 있던 부정·조건이 주장에 없거나 검토/예정을 확정으로 표현한 경우.
- 여러 ID를 연결한 주장 및 구간별 수치를 조합한 주장.

경고에는 대상·단위·주장 값·근거 값 등을 포함해 검토자가 원문과 비교할 수 있다. 자동 거부하지 않으며, ID 존재만으로 의미가 일치한다고 판단하지 않는다.

기존 시험비/임대료 수치 교환 fixture는 기존 core와 수치 집합 검사에서 통과하되 이제 구체 관계 경고를 받는다. 확장 실험 10개에는 targeted 오류6개, 정상 control3개, 새 사실 생성 blindspot1개를 포함한다. targeted6개에서 지정 경고6개를 확인했다.
**올바른 다중 문장 결합도 경고하는 정상 control**을 함께 제공한다. 경고6/6을 precision이나 실제 LLM 사실 정확도로 표시하지 않는다.

새 사건 창작, 한국어의 다양한 주어/목적어 재서술, 복잡한 조직/직함, 조건의 중요도·정당한 생략은 여전히 해결하지 못한다.
중요 정보 판단은 원문과 전체 요약·미참조 구간을 사람이 검토해야 한다.
core에서 자동 거부하는 숫자/날짜/인물/근거 ID 오류와, 보조 경고/미탐지를 구분해 결과에 남긴다.

```sh
.venv/bin/python -B -m drivebrief_api.algorithm_bench --output results/my-v2-bench.json
```

모든 fixture는 자체 작성이다. 벤치마크의 approved 필드는 입력 검증을 시험하는 **메모리 내 합성 상태**이며 실제 기사나 SQLite의 승인을 만들지 않는다.

### 추가 모델 검토 (도입하지 않음)
| 방식 | 기대 가능성 | 이번에 미확인인 비용·위험 |
|---|---|---|
| 현재 관계 규칙 | 결정적·추가 설치/외부 비용 없음, 설명 가능 | 제한된 문법, 관계 누락·정상 결합 오경고 |
| 한국어 embedding | 표현 차이가 큰 쌍의 후보 탐색 | 같은 기업의 다른 사건도 가까울 수 있음. entailment 검사 아님. 모델별 메모리·지연·정확도 미측정 |
| 한국어 NLI | 주장–근거 관계 분류 실험 가능 | 숫자/조건의 오판·도메인 차이, 설치·추론 자원·threshold 평가 필요. 실제 수치 미측정 |
| 추가 LLM 검증 | 복잡한 재서술 검토 보조 가능 | 비용·개인정보/권한·일관성·외부 API 필요. 이번 작업에서 호출하지 않음 |

작은 합성 fixture만으로 새 모델이 필요하다고 단정하지 않았다. 향후 동일한 실제 사람 라벨/오류 fixture/정상 control에서 탐지율·오경고율·속도·프로세스 RSS 메모리를 함께 비교해야 한다.

## 4. 승인 prefix 편성 후보

기존 `plan`을 재사용해 승인/가상자료/중복/순서 검사를 수행한다.
그 뒤 기사별 후보는 skip 또는 원래 문장 순서의 prefix뿐이다. 중간 문장만 떼거나 승인 문장을 편집하지 않는다.

- 비용: 문장별 예상시간을 millisecond 단위로 올림. 합계가 목표를 넘지 않게 한다.
- 실험 utility: `(1+importance_score)/(rank+1) * (1+log2(prefix_length))`.
- 다중 선택 배낭 방식으로 목표 내 utility 최대 조합을 찾는다.
- 동일 문장 중복 포함을 차단하며 상태 수50,000을 넘으면 명시적 오류를 반환한다. 운영 대규모 최적화기가 아니다.
- 필수 설명 위치가 있으면 사람이 `minimum_prefix`를 지정한다. reviewer와 승인 TTS 배열 해시가 필요하며 원문 수정 후에는 제약을 다시 검토한다.
- 제약은 기사 자체의 승인과 별개다. 메타데이터의 reviewer 문자열이 실제 검토를 증명하는 인증 체계는 아니다. 현재는 로컬 실험 경계다.
- 제약을 만족할 시간이 없으면 해당 기사를 제외한다. 의미 검증/필수 문장 자동 탐지는 구현하지 않았다.

합성 기사마다 안전 조건이 두 번째 문장에 있다고 실험 작성자가 표시한 결과:
| 옵션 | 기존 | 후보 | 해석 |
|---|---|---|---|
| 짧게 | 3기사5문장·28.8초, 조건 미포함 기사1 | 2기사5문장·29.2초, 조건 미포함 기사0 | 폭넓은 기사 수와 맥락 보존의 trade-off |
| 중간 | 3기사9문장·52.2초 | 동일 | 남은7.8초를 반복으로 채우지 않음 |
| 길게 | 3기사9문장·52.2초 | 동일 | 자료 부족67.8초를 인정 |

이는 합성 편성 제약 만족 결과이며 사용자 만족/실제 중요도/실제 소요시간 개선이 아니다. 30/60/120초는 계속 개발용 placeholder다.
제약 없이 배낭 utility만 적용해도 핵심 맥락 보존이 보장되지 않는다. 서비스 기본 편성/API는 변경하지 않았다.

## 5. 미학습 문장 Pleos 실측

기존18시도/9문장으로 구한 **7.750769230118592자/초, 추가 고정시간0** 후보를 동결했다.
현재 데이터에 다시 fitting하지 않았다. 고정0은 실제 음성 쉼을 제거한다는 뜻이 아니다.

별도 opt-in `UnseenSpeechTimingTest`가 기존 PleosSpeechOutput + MeasuredSpeechOutput을 사용해 자체 작성12문장을 재생했다. Android main/UI/SDK 코드는 변경하지 않았다.
4개 가상 주제별3문장, 문장 해시·기사 ID·attempt ID가 기존 학습과 겹치지 않음을 비교 도구로 확인했다. 같은 기기·SDK3.3.1·ko-KR이다.

| 평가 | 기존 5자/초+.4초 | 고정 후보7.75077자/초 |
|---|---:|---:|
| 새12문장 요청→완료 MAE | 3.237초 | .461초 |
| RMSE | 3.324초 | .611초 |
| 평균 부호 오차 | +3.237초 | -.286초 |
| 12문장 예상 합 | 110.400초 | 68.122초 |
| 전체 실제 완료 시간 | 71.694초 | 동일 |
| 전체 예상−실제 | +38.706초 | -3.572초 |

실제 요청→완료 합71.552초, 문장 사이 간격 합.142초다.
startup 5~137ms·중앙값11ms, 시작→완료 평균5.929초로 요청 지연과 발화 구간을 분리했다.
이는 SDK 완료 콜백 시간이며 실제 음향 파형/사람의 청취 확인이 아니다.

새 주제별 문장 MAE (모두 기존 학습 기사와 분리):
| 가상 주제 | 기존 | 고정 후보 |
|---|---:|---:|
| 도서관 | 3.134초 | .578초 |
| 연구소·금액·날짜 | 2.947초 | .694초 |
| 전시회·영문·거리 | 3.094초 | .264초 |
| 체육회·문장부호·조건 | 3.775초 | .307초 |

새 표본 특성: 전체34~53자, 한글25~40자, 공백7~12자, 숫자0~8자, 문장부호1~4자, 영문0~5자.
날짜·금액·영문 AI/API·질문/쉼표를 포함했지만 동일 내용을 한 변수만 바꾼 통제 실험은 아니다. 보고서의 특성별 상관관계는 원인 추정에 사용할 수 없다. 긴 기사·다양한 voice model·여러 기기 환경으로 일반화할 수 없다.

후보는 이전 동일 문장 검증 MAE .174초보다 새 문장에서 오차가 커졌다. 특히 글자 수가 비슷해도 읽는 방식에 따라 오차가 달라졌다. 더 많은 독립 문장과 반복 측정이 필요하므로 **기본 설정에는 적용하지 않았다**.
이번 12문장 세션은 길이 옵션 편성 실험이 아니라 고정 문장 예측 실험이다.

### 재현
기기 진단은 명시적으로 실행할 때만 재생한다. 일반 connected suite에서는 skip한다.
테스트 APK를 설치한 뒤 연결된 사용자 ID에 맞춰:
```sh
adb shell am instrument --user 10 -w -r -e algorithmTiming true -e class com.example.drivebrief.UnseenSpeechTimingTest com.example.drivebrief.test/androidx.test.runner.AndroidJUnitRunner
```

숫자/해시만 포함한 `drivebrief_unseen_timing` 배열을 JSONL로 내보낸다. 기존 앱 측정 파일은 삭제하지 않는다.
현재 원본 `results/algorithm-v2-unseen-verified.jsonl`과 분석 결과는 Git 제외다.
backend에서:
```sh
.venv/bin/python -B -m drivebrief_api.timing_holdout --training results/quality-speech-observed.jsonl --test results/algorithm-v2-unseen-verified.jsonl --candidate-config results/quality-timing-candidate.json --output results/my-v2-holdout.json
```

학습/평가 해시·기사·attempt 겹침과 SDK/locale 차이는 거부한다. mock·stop/error는 기존 측정 필터에서 제외한다. SDK dependency가 같아도 voice model 버전/부하를 완벽히 식별하지 못한다.
실측 파일 없는 새 체크아웃에서는 실제 TTS 성능을 재현할 수 없고 합성 테스트만 실행할 수 있다.

## 6. 팀 연동 제안·미확정 사항

기존 API를 변경하지 않았다. [기존 경계 문서](INTERFACES_DRAFT.md)에 추가해 협의할 내용:
- 수집 → 선정: stable article ID, canonical URL, raw/정규화 source, category, timezone, updated/retracted, 수집 오류/신선도.
- 그룹화 평가: 동일 사건/후속 사건 정의, 판정자·라벨 revision, topic과 event 구분, 독립 holdout.
- 선정 평가: 사용자 관심·기준시각에 따른 relevance rubric, 단독/과거 중요 뉴스, 분야/출처 편중 허용치.
- 요약 → 검토: 주장별 근거 ID뿐 아니라 대상·수치·단위·인물/조직 관계의 보조 findings. 경고는 승인과 별개.
- 검토 → 편성: `minimum_prefix / approved_text_hash / reviewer`의 별도 sidecar 제안. 아직 wire API·DB schema로 확정하지 않았다.
- TTS: 엔진/voice version·속도·기기·부하 측정조건, 다양한 문장, 보존·삭제 정책.
- 승인 문장이 바뀌면 편성 제약도 재검토해야 한다. 뉴스 선정을 이용 권한으로 간주하지 않는다.

## 7. 테스트와 다음 우선순위

실행 결과:
- Python backend: 102개 통과 (기존87 + 신규15). 실제 LLM 호출 없음.
- 기존 크롤러: 5개 통과. 뉴스 SQLite SHA256이 이전 값과 같고, 실제 평가 자료·실측 파일·승인 DB의 Git 제외를 확인했다.
- Android Studio Gradle debug/app-test APK 빌드·JVM 테스트 성공.
- Pleos 전체 회귀: 35개 통과·3개 제외 (Android 기본 TTS 미지원, export 진단, 새 실측 opt-in).
- 새 문장 실측을 별도로 opt-in 실행: 1개 통과, 12문장 완료.
- 기존 Android JVM 테스트 10개 통과. Android main/UI·크롤러·기본 설정 파일에는 변경이 없다.

터미널 Gradle은 Java Runtime 경로 문제로 한 차례 실패했다. Android Studio의 Gradle 도구를 사용해 재검증했다. OS/JDK 설정은 바꾸지 않았다.
후보 입력 순서 재현성 테스트 실패를 ID 정렬로 수정한 뒤 Python 전체를 재실행해 통과했다.

```sh
# backend에서
.venv/bin/python -B -m unittest discover -s tests
# 루트에서
backend/.venv/bin/python -B -m unittest discover -s news_crawler/tests
./gradlew :app:assembleDebug :app:testDebugUnitTest
./gradlew :app:connectedDebugAndroidTest
```

CLI는 출력 파일을 덮어쓰지 않는다. 재실행 시 새 경로를 지정한다.
추가 모델/의존성 설치 없이 Python 3.9 호환 범위에서 구현했다. 실제 RSS snapshot·라벨·벤치 결과·실측 JSONL은 results에만 보관하고 공개하지 않는다.

다음 순서:
1. 60쌍 정답과 상위20 pooled 중요도 라벨 수집·판정자 불일치 해결.
2. 학습/검증 분리 후 그룹화 false merge/누락 및 가중치 ablation 평가.
3. 정상 재서술 control·복합 관계 오류 데이터 확대, 보조 경고 오경고율 측정.
4. 여러 기사·긴 문장·날짜/금액/영문/부호 통제 문장으로 TTS 재측정.
5. 사람이 표시한 필수 맥락을 사용해 기사 폭과 설명 깊이 utility를 비교한 후 서비스 적용 여부 협의.
