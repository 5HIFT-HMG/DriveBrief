# Pleos 시간 보정과 편성 검증

기준 main f77e9ec, 브랜치 feature/tts-time-calibration.

## 변경 범위

현재 앱 선택은 짧게·중간·길게이며 30/60/120초는 개발용 설정이다. 팀이 확정한 값이 아니므로 10/20/30분으로 기본값을 바꾸지 않았다.

기존 MeasuredSpeechOutput, timing_quality의 두 계수 모델, 승인 문장 접두부 편성을 재사용한다. 예측은 글자 수 / characters_per_second + sentence_pause_seconds이다. 두 번째 계수는 문장 요청의 고정 비용이며 쉼표별 휴지시간이 아니다. 소량 데이터에 다변량 모델을 추가하지 않았다.

학습·검증의 문장 해시, 기사, 시도 ID 중복을 거부한다. 검증 중 계수를 재학습하지 않는다. 검증 MAE가 기본 모델보다 10% 이상 개선되고 SDK/언어가 일치하는 프로필만 사용한다. 경로가 없거나 요청 SDK/언어가 다르면 기존 모델을 사용한다. 잘못된 프로필은 오류를 반환한다.

편성은 명시적으로 켰을 때만 기존 budget_candidate를 통해 예산에 가까운 승인 문장 접두부를 선택한다. 동률에는 기존 utility를 사용한다. 중요도 점수와 그룹화 계산은 변경하지 않았다. 예산 채우기가 우선이므로 일부 높은 순위 기사 대신 더 잘 맞는 기사가 선택될 수 있다. 문장을 생성하거나 반복하여 시간을 채우지 않는다. 최대 상태 수 초과 시 기존 편성으로 돌아간다. 예측시간 기준 예산 이하이며 실제 재생시간 상한을 보장하지 않는다. 사람 검토와 승인 정책은 유지한다.

## 실제 Pleos 측정

2026-11-13, Pleos 에뮬레이터, SDK 3.3.1, ko-KR. 자체 작성 가상 문장만 재생했다. 학습 12문장/3기사의 측정 뒤 계수를 고정하고 다른 주제 6문장/2기사를 재생했다. 모두 completed, 제외 0건. 녹음 파형이 아닌 SDK 요청~완료 콜백 경과시간이다.

| 검증 6문장 | 기존 모델 | 보정 모델 |
| --- | ---: | ---: |
| MAE, 초/문장 | 3.3403 | 0.3600 |
| RMSE, 초/문장 | 3.6347 | 0.4015 |
| 평균 부호오차, 초/문장 | +3.3403 | -0.1222 |

학습 계수: 9.433656082652679 글자/초 + 고정 비용 1.1046112385321116초. 기존 기본값은 5글자/초 + 0.4초다. 소규모 가상 문장 검증으로 실뉴스 전체나 차량 실기기 정확도를 대표하지 않는다. 긴 세션의 대기·전환·취소, 숫자·영문 발음 차이는 추가 측정 대상이다. 10/20/30분 전체 실제 재생은 측정하지 않았다.

## 재현

일반 instrumentation에서는 음성을 재생하지 않고 측정 테스트를 건너뛴다. 명시적 측정:

```sh
adb shell am instrument -w -e class com.example.drivebrief.CalibrationTimingTest -e calibrationPhase train com.example.drivebrief.test/androidx.test.runner.AndroidJUnitRunner
```

출력 drivebrief_calibration_records 배열을 JSONL로 저장한다. 문장 본문이나 인증정보는 기록하지 않는다. backend에서:

```sh
python -m drivebrief_api.timing_calibration train --input results/calibration-training.jsonl --output results/timing-trained.json
```

그 뒤 calibrationPhase validation으로 별도 재생하여 저장하고:

```sh
python -m drivebrief_api.timing_calibration validate --model results/timing-trained.json --input results/calibration-validation.jsonl --output results/timing-validated.json
```

출력 덮어쓰기를 거부한다. 원본 측정과 프로필은 ignored results에 보관한다. 시험하려면 백엔드 환경에 명시한다:

```sh
DRIVEBRIEF_TIMING_MODEL=/absolute/path/to/results/timing-validated.json
DRIVEBRIEF_BUDGET_PACKING=1
```

앱의 승인 브리핑 요청은 X-DriveBrief-TTS-SDK: 3.3.1, X-DriveBrief-TTS-Locale: ko-KR를 보낸다. 환경 설정 없이는 기존 모델과 편성을 유지한다.

## 검증 범위

백엔드 138개 테스트 통과(기준 main 128개). 추가 테스트는 학습 누출, SDK 불일치, 미검증·비정상 계수, 가중치 보존, 승인 경계, 접두부, 중복, 상태 제한 fallback, 빈 기사와 짧은 예산을 확인한다. 비용 6/5/5초 및 예산 10초의 합성 사례에서 기존 6초 대비 10초 편성이다. 30/60/120/600/1200/1800초 뉴스 부족 조건에서 반복·초과 없이 종료한다. 이는 합성 단위 테스트이며 긴 세션 실측이 아니다. Android debug와 androidTest 빌드, JVM 테스트 및 실제 측정 instrumentation 2회(학습/검증)가 통과했다.
