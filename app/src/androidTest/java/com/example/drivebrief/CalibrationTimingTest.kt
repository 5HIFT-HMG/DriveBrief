package com.example.drivebrief

import android.os.Bundle
import androidx.test.platform.app.InstrumentationRegistry
import com.example.drivebrief.audio.*
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class CalibrationTimingTest {
    @Test fun measureExplicitCalibrationCorpus() {
        val phase = InstrumentationRegistry.getArguments().getString("calibrationPhase")
        assumeTrue("Explicit calibration recording only", phase in listOf("train", "validation"))
        val training = listOf(
            "가상 도서관은 오늘 문을 엽니다.",
            "가상 도서관은 새로 들어온 책을 주민들에게 소개했습니다.",
            "가상 도서관은 책 300권을 정리하고 열람실 의자 24개를 점검했습니다.",
            "가상 도서관은 어린이와 보호자가 함께 읽는 시간을 준비했으며, 야간 운영은 아직 확정하지 않았습니다.",
            "가상 보건소는 안내문을 공개했습니다.",
            "가상 보건소는 오전 9시부터 오후 6시까지 상담을 진행합니다.",
            "가상 보건소는 AI 안내와 API 연결을 시험하고 담당자에게 점검 결과를 전달했습니다.",
            "가상 보건소는 방문자가 많을 때에는 대기 시간을 알려 주고, 예약하지 않은 사람에게도 접수 방법을 안내합니다.",
            "가상 기상대는 비 소식을 전했습니다.",
            "가상 기상대는 내일 아침부터 바람이 강해질 가능성이 있다고 설명했습니다.",
            "가상 기상대의 관측 지점은 12곳이며 평균 기온은 18도, 이동 거리는 3.5킬로미터입니다.",
            "가상 기상대는 비가 그친 뒤에도 도로가 미끄러울 수 있으므로, 충분한 거리를 두고 천천히 이동해 달라고 안내했습니다."
        )
        val validation = listOf(
            "가상 박물관은 오늘 전시를 시작합니다.",
            "가상 박물관은 2026년 11월 25일부터 로봇 15대와 작은 모형을 소개합니다.",
            "가상 박물관은 AI 기술을 설명하지만, 추가 전시와 야간 개방은 아직 검토 중이며 확정된 일정은 없습니다.",
            "가상 체육관은 운동 기구를 점검했습니다.",
            "가상 체육관의 참가자는 120명이며, 참가비는 12,000원이고 준비한 물품은 300개입니다.",
            "가상 체육관은 달리기와 걷기를 준비했습니다. 비가 오면 실내로 옮길까요? 담당자는 안전 점검 뒤에 결정한다고 밝혔습니다."
        )
        val texts = if (phase == "train") training else validation
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val session = UUID.randomUUID().toString()
        val records = JSONArray()
        lateinit var output: MeasuredSpeechOutput
        instrumentation.runOnMainSync {
            output = MeasuredSpeechOutput(PleosSpeechOutput(instrumentation.targetContext), { row ->
                val c = row.context; val f = row.features
                records.put(JSONObject().put("schema", "speech-timing-v1").put("engine", row.engine)
                    .put("sdk_version", "3.3.1").put("locale", "ko-KR").put("attempt_id", row.attemptId)
                    .put("session_id", c.sessionId).put("briefing_id", c.briefingId).put("article_id", c.articleId)
                    .put("sentence_index", c.sentenceIndex).put("length_option", c.lengthOption)
                    .put("session_sentence_count", c.sessionSentenceCount).put("text_sha256", row.textSha256)
                    .put("outcome", row.outcome).put("requested_epoch_ms", row.requestedEpochMs)
                    .put("requested_monotonic_ms", row.requestedMonotonicMs)
                    .put("startup_ms", row.startupMs ?: JSONObject.NULL)
                    .put("start_to_done_ms", row.startToDoneMs ?: JSONObject.NULL)
                    .put("request_to_done_ms", row.requestToDoneMs)
                    .put("features", JSONObject().put("characters", f.characters).put("hangul", f.hangul)
                        .put("spaces", f.spaces).put("digits", f.digits).put("punctuation", f.punctuation)
                        .put("latin", f.latin).put("other", f.other)))
            }, "pleos-on-device")
        }
        try {
            texts.forEachIndexed { index, text ->
                val latch = CountDownLatch(1)
                var failure: String? = null
                instrumentation.runOnMainSync {
                    output.context = TimingContext(session, "timing-calibration-v1", "calibration-$phase-${index / (if (phase == "train") 4 else 3)}",
                        index, "measurement_only", texts.size)
                    output.speak(text, {}, { latch.countDown() }, { failure = it; latch.countDown() })
                }
                assertTrue("TTS completion timeout", latch.await(45, TimeUnit.SECONDS))
                assertNull(failure)
            }
            assertEquals(texts.size, records.length())
            assertTrue((0 until records.length()).all { records.getJSONObject(it).getString("outcome") == "completed" })
            instrumentation.sendStatus(2, Bundle().apply { putString("drivebrief_calibration_records", records.toString()) })
        } finally { instrumentation.runOnMainSync { output.close() } }
    }
}
