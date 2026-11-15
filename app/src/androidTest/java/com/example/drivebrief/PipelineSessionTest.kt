package com.example.drivebrief

import android.content.Context
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.test.platform.app.InstrumentationRegistry
import com.example.drivebrief.audio.SpeechOutput
import com.example.drivebrief.data.*
import com.example.drivebrief.ui.DemoBriefingScreen
import com.example.drivebrief.ui.SessionPaper
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import java.util.UUID

internal fun plannedFixture(): String {
    val articles = JSONArray()
    for (i in 1..3) articles.put(JSONObject().apply {
        put("article_id", "pipeline-$i"); put("title", "연동 기사 $i"); put("source", "가상 출처")
        put("tts_sentences", JSONArray(listOf("첫 문장 $i", "둘째 문장 $i")))
        put("one_line", "한 줄 $i"); put("detail", "전체 상세 $i")
        put("mock", true); put("source_url", JSONObject.NULL); put("approved_sentence_count", 3); put("partial_tts", true)
        put("categories", JSONArray(listOf("경제"))); put("sentence_indices", JSONArray(listOf(0, 1)))
        put("validation", JSONObject().put("status", "approved").put("approved", true).put("review_required", false))
    })
    return JSONObject().put("schema_version", "approved-briefing-v1").put("fictional_only", true)
        .put("playback_requires_user_action", true).put("briefing_id", "brief_test")
        .put("policy_status", "development_placeholder_not_team_policy").put("length_option", "중간")
        .put("target_seconds", 60).put("estimated_seconds", 12).put("articles", articles).toString()
}

private fun journal(): SessionHistory {
    val context = InstrumentationRegistry.getInstrumentation().targetContext
    val history = SessionHistory(context, "test_history_" + UUID.randomUUID())
    runBlocking { withTimeout(5000) { history.awaitReady() } }
    return history
}

class SessionStorageTest {
    @Test fun durableRoundTripDuplicateCallbacksAndRecovery() = runBlocking {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val key = "test_history_" + UUID.randomUUID()
        val history = SessionHistory(context, key)
        withTimeout(5000) { history.awaitReady() }
        val id = history.start(DemoBriefingClient.parse(plannedFixture(), true))
        history.event(id, 0, 0, "start"); history.event(id, 0, 0, "done")
        history.event(id, 0, 0, "done"); history.event(id, 0, 1, "start")
        withTimeout(5000) { history.flush() }; history.close()
        val restored = SessionHistory(context, key)
        withTimeout(5000) { restored.awaitReady() }
        val session = restored.state.value.sessions.single()
        assertEquals(id, session.sessionId)
        assertEquals(1, session.progress[0].completed.size)
        assertEquals(ListeningStatus.INTERRUPTED, session.progress[0].status)
        assertEquals(0, session.progress[1].completed.size)
        assertEquals("전체 상세 1", session.briefing.articles[0].detail)
        restored.close()
    }

    @Test fun corruptStorageIsPreservedAndNotSilentlyReplaced() = runBlocking {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val key = "test_history_" + UUID.randomUUID()
        context.getSharedPreferences(key, Context.MODE_PRIVATE).edit().putString("sessions", "broken").commit()
        val history = SessionHistory(context, key)
        withTimeout(5000) { history.awaitReady() }
        assertNotNull(history.state.value.error)
        assertEquals("broken", context.getSharedPreferences(key, Context.MODE_PRIVATE).getString("sessions", ""))
        try { history.start(DemoBriefingClient.parse(plannedFixture(), true)); fail("must preserve corrupt file") }
        catch (_: IllegalStateException) {}
        history.close()
    }

    @Test fun plannedParsingAndInvalidTiming() {
        val parsed = DemoBriefingClient.parse(plannedFixture(), true)
        assertEquals("중간", parsed.lengthOption)
        assertEquals(3, parsed.articles[0].approvedSentenceCount)
        assertEquals("brief_test", parsed.briefingId)
        try { DemoBriefingClient.parse(plannedFixture().replace("\"target_seconds\":60", "\"target_seconds\":-1"), true); fail("invalid") }
        catch (_: DemoApiException) {}
        val wrongIndices = JSONObject(plannedFixture())
        wrongIndices.getJSONArray("articles").getJSONObject(0).put("sentence_indices", JSONArray(listOf(1, 2)))
        try { DemoBriefingClient.parse(wrongIndices.toString(), true); fail("must reject untracked source sentence indices") }
        catch (_: DemoApiException) {}
    }
}

class PipelineSessionUiTest {
    @get:Rule val compose = createComposeRule()
    private class Speech : SpeechOutput {
        var done: () -> Unit = {}
        var failed: (String) -> Unit = {}
        override fun speak(text: String, onStarted: () -> Unit, onDone: () -> Unit, onFailure: (String) -> Unit) {
            done = onDone; failed = onFailure; onStarted()
        }
        override fun stop() = Unit
    }
    private fun click(text: String) = compose.onNodeWithText(text, substring = false).performScrollTo().performClick()

    @Test fun callbacksMatchOnePaperAndStorage() {
        val history = journal(); val speech = Speech()
        var paper by mutableStateOf(false)
        compose.setContent {
            val snapshot by history.state.collectAsState()
            if (paper) Column(Modifier.verticalScroll(rememberScrollState())) {
                SessionPaper(snapshot, selected = snapshot.sessions.firstOrNull()?.sessionId)
            }
            else DemoBriefingScreen(speech, DemoBriefingLoader { DemoBriefingClient.parse(plannedFixture(), true) }, true, history, autoPlay = false)
        }
        click("재생")
        repeat(6) { compose.runOnIdle { speech.done() }; compose.waitForIdle() }
        compose.runOnIdle {
            assertTrue(history.state.value.sessions.single().fullyCompleted)
            paper = true
        }
        compose.onNodeWithText("1. 연동 기사 1").performScrollTo().assertIsDisplayed()
        compose.onAllNodesWithText("전체 요약에는 미청취 내용이 포함됩니다.").assertCountEquals(0)
        compose.runOnIdle { assertTrue(history.state.value.sessions.single().progress.all { it.completed.size == 2 }) }
        runBlocking { withTimeout(5000) { history.flush() } }; history.close()
    }

    @Test fun pauseResumeSkipInterruptNeverFakesCompletion() {
        val history = journal(); val speech = Speech()
        compose.setContent { DemoBriefingScreen(speech, DemoBriefingLoader {
            DemoBriefingClient.parse(plannedFixture(), true)
        }, true, history, autoPlay = false) }
        click("재생")
        compose.runOnIdle { speech.done() }; compose.waitForIdle()
        click("일시정지")
        compose.runOnIdle {
            val p = history.state.value.sessions.single().progress[0]
            assertEquals(1, p.completed.size); assertEquals(ListeningStatus.INTERRUPTED, p.status)
        }
        click("재개"); click("다음 기사"); click("재생 중단(OnePaper)")
        compose.runOnIdle {
            val s = history.state.value.sessions.single()
            assertFalse(s.fullyCompleted); assertTrue(s.ended)
            assertEquals(ListeningStatus.SKIPPED, s.progress[0].status)
            assertEquals(ListeningStatus.INTERRUPTED, s.progress[1].status)
            assertEquals(ListeningStatus.UNHEARD, s.progress[2].status)
        }
        history.close()
    }
}
