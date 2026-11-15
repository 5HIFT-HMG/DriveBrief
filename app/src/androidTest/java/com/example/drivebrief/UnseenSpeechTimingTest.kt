package com.example.drivebrief

import android.os.Bundle
import android.os.SystemClock
import androidx.test.platform.app.InstrumentationRegistry
import com.example.drivebrief.audio.*
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Opt-in experiment using authored unseen sentences, never changes service UI or approval DB. */
class UnseenSpeechTimingTest {
    @Test fun measureAuthoredUnseenSentences() {
        assumeTrue("Explicit local timing experiment only",
            InstrumentationRegistry.getArguments().getString("algorithmTiming") == "true")
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val session = UUID.randomUUID().toString()
        val texts = listOf(
            "가상 마을 도서관은 주민들이 함께 읽을 책을 고르고 있습니다.",
            "가상 마을 도서관은 토요일 오후에 문을 열지만 야간 운영은 아직 검토하고 있습니다.",
            "가상 마을 도서관의 새 책은 삼백 권이며 어린이 열람실에는 의자 스무 개를 준비했습니다.",
            "가상 연구소는 오늘 새로운 실험 장비의 안전 점검을 시작했습니다.",
            "가상 연구소의 시험비는 300만원이고 임대료는 500만원이며 연구원 12명이 참여합니다.",
            "가상 연구소는 2026년 11월 20일에 시험을 시작할 계획이며 아직 승인을 받지 않았습니다.",
            "가상 전시회에서는 로봇과 작은 모형 자동차를 함께 소개합니다.",
            "가상 전시회는 AI 기술과 API 연결 방법을 설명하고 한국어 안내를 제공합니다.",
            "가상 전시회는 3.5킬로미터 떨어진 행사장에서 열리며 입장료는 12,000원입니다.",
            "가상 체육회는 운동을 마친 참가자에게 충분히 쉬어 달라고 안내했습니다.",
            "가상 체육회는 달리기, 걷기, 스트레칭을 준비했습니다. 비가 오면 어떻게 될까요?",
            "가상 체육회는 안전 검사를 마친 경우에만 경기를 시작하며 승인 전에는 일정을 확정하지 않습니다."
        )
        lateinit var output: MeasuredSpeechOutput
        instrumentation.runOnMainSync {
            output = MeasuredSpeechOutput(PleosSpeechOutput(context),
                { SpeechTimingFile.get(context).append(it) }, "pleos-on-device")
        }
        try {
            texts.forEachIndexed { index, text ->
                val done = CountDownLatch(1)
                var failure: String? = null
                instrumentation.runOnMainSync {
                    output.context = TimingContext(session, "unseen-timing-v2", "unseen-v2-${index/3}",
                        index%3, "measurement_only", texts.size)
                    output.speak(text, {}, { done.countDown() }, { failure = it; done.countDown() })
                }
                assertTrue("Completion timeout at index $index", done.await(45, TimeUnit.SECONDS))
                assertNull("Playback failure at index $index", failure)
            }
            val file = File(context.getExternalFilesDir(null), "speech-timing-v1.jsonl")
            var records = JSONArray()
            val deadline = SystemClock.elapsedRealtime()+5000
            do {
                records = JSONArray()
                if (file.exists()) file.forEachLine(Charsets.UTF_8) { line ->
                    if (line.isNotBlank()) {
                        val row = JSONObject(line)
                        if (row.optString("session_id") == session) records.put(row)
                    }
                }
                if (records.length() < texts.size) SystemClock.sleep(100)
            } while (records.length() < texts.size && SystemClock.elapsedRealtime() < deadline)
            assertEquals(texts.size, records.length())
            instrumentation.sendStatus(2, Bundle().apply {
                putString("drivebrief_unseen_timing", records.toString())
            })
        } finally {
            instrumentation.runOnMainSync { output.close() }
        }
    }
}
