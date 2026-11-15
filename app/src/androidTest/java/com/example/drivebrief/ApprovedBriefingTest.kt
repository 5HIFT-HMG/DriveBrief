package com.example.drivebrief

import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import com.example.drivebrief.audio.SpeechOutput
import com.example.drivebrief.data.*
import com.example.drivebrief.ui.DemoBriefingScreen
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

private fun approvedFixture(): String {
    val items = JSONArray()
    for (i in 1..3) items.put(JSONObject().apply {
        put("article_id", "fiction-$i"); put("title", "가상 기사 $i"); put("source", "자체 작성")
        put("tts_sentences", JSONArray(listOf("기사 ${i}의 첫 문장입니다.", "기사 ${i}의 다음 문장입니다.")))
        put("one_line", "가상 한 줄 요약"); put("detail", "가상 상세 요약"); put("mock", true)
        put("validation", JSONObject().put("status", "approved").put("approved", true).put("review_required", false))
    })
    return JSONObject().put("schema_version", "approved-briefing-v1").put("fictional_only", true)
        .put("playback_requires_user_action", true).put("articles", items).toString()
}

class ApprovedBriefingTest {
    @get:Rule val compose = createComposeRule()
    private class Speech : SpeechOutput {
        val texts = mutableListOf<String>()
        var done: () -> Unit = {}
        var fail: (String) -> Unit = {}
        override fun speak(text: String, onStarted: () -> Unit, onDone: () -> Unit, onFailure: (String) -> Unit) {
            texts.add(text); done = onDone; fail = onFailure; onStarted()
        }
        override fun stop() = Unit
    }
    private fun open(speech: Speech, loader: DemoBriefingLoader = DemoBriefingLoader {
        DemoBriefingClient.parse(approvedFixture(), true)
    }) {
        compose.setContent { DemoBriefingScreen(speech, loader, approvedMode = true, autoPlay = false) }
        compose.waitForIdle()
    }
    private fun click(text: String) = compose.onNodeWithText(text, substring = false).performScrollTo().performClick()

    @Test fun guardedParserRequiresHumanApprovalAndFictionalMode() {
        assertEquals(3, DemoBriefingClient.parse(approvedFixture(), true).articles.size)
        listOf(approvedFixture().replace("\"approved\":true", "\"approved\":false"),
            approvedFixture().replace("\"fictional_only\":true", "\"fictional_only\":false"),
            approvedFixture().replace("\"review_required\":false", "\"review_required\":true")).forEach {
            try { DemoBriefingClient.parse(it, true); fail("must reject") } catch (_: DemoApiException) {}
        }
        try { DemoBriefingClient.parse(approvedFixture()); fail("wrong channel") } catch (_: DemoApiException) {}
    }

    @Test fun threeArticlesAdvanceOnlyOnDoneAndComplete() {
        val speech = Speech(); open(speech)
        compose.runOnIdle { assertTrue(speech.texts.isEmpty()) }
        click("재생")
        repeat(6) { compose.runOnIdle { speech.done() }; compose.waitForIdle() }
        compose.runOnIdle {
            assertEquals(listOf("기사 1의 첫 문장입니다.", "기사 1의 다음 문장입니다.",
                "기사 2의 첫 문장입니다.", "기사 2의 다음 문장입니다.",
                "기사 3의 첫 문장입니다.", "기사 3의 다음 문장입니다."), speech.texts)
        }
        compose.onNodeWithText("브리핑 전체 재생 완료").performScrollTo().assertIsDisplayed()
    }

    @Test fun pauseStaleCallbackResumeSkipArticleAndStop() {
        val speech = Speech(); open(speech); click("재생")
        lateinit var stale: () -> Unit
        compose.runOnIdle { stale = speech.done }
        click("일시정지")
        compose.runOnIdle { stale() }
        click("재개")
        compose.runOnIdle { assertEquals("기사 1의 첫 문장입니다.", speech.texts.last()) }
        click("다음 기사")
        compose.runOnIdle { assertEquals("기사 2의 첫 문장입니다.", speech.texts.last()) }
        click("이전 기사")
        compose.runOnIdle { assertEquals("기사 1의 첫 문장입니다.", speech.texts.last()) }
        click("다음 기사")
        compose.runOnIdle { assertEquals("기사 2의 첫 문장입니다.", speech.texts.last()) }
        click("재생 중단(OnePaper)")
        compose.onNodeWithText("브리핑 중단(완료되지 않음)").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("브리핑 전체 재생 완료").assertDoesNotExist()
    }

    @Test fun focusFailureDoesNotAutoResume() {
        val speech = Speech(); open(speech); click("재생")
        compose.runOnIdle { speech.fail("포커스 상실") }
        compose.onNodeWithText("재개", substring = false).performScrollTo().assertIsDisplayed()
        compose.runOnIdle { assertEquals(1, speech.texts.size) }
    }

    @Test fun connectionFailureRetryAndEmpty() {
        var calls = 0
        val empty = JSONObject(approvedFixture()).put("articles", JSONArray()).toString()
        open(Speech(), DemoBriefingLoader {
            if (++calls == 1) throw DemoApiException("연결 실패")
            DemoBriefingClient.parse(empty, true)
        })
        click("재시도")
        compose.onNodeWithText("불러온 뉴스가 없습니다.").performScrollTo().assertIsDisplayed()
    }
}
