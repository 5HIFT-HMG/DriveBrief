package com.example.drivebrief

import androidx.compose.ui.test.*
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.graphics.Color
import com.example.drivebrief.ui.theme.Ink
import com.example.drivebrief.ui.theme.InkSub
import androidx.compose.ui.test.junit4.createComposeRule
import com.example.drivebrief.audio.SpeechOutput
import com.example.drivebrief.data.*
import com.example.drivebrief.ui.DemoBriefingScreen
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

class RssShortPlaybackTest {
    @get:Rule val compose = createComposeRule()
    private val title = "화면에 표시할 합성 기사 제목"
    private val lead = "시청은 참가자가 자체 추산 3만 명이며 아직 확정되지 않았다고 밝혔습니다."

    private fun fixture(spoken: String = lead): String =
        JSONObject(autoRssFixture("짧게", 1)).apply {
            getJSONArray("articles").getJSONObject(0).apply {
                put("title", title); put("one_line", title)
                put("detail", lead + " 추가 운영 일정은 나중에 공지할 계획입니다.")
                put("tts_sentences", JSONArray(listOf(spoken)))
            }
        }.toString()

    @Test fun parsesTitleAndLeadAsSeparateFieldsAndKeepsSource() {
        val result = DemoBriefingClient.parse(fixture(), true)
        val article = result.articles.single()
        assertEquals(title, article.title)
        assertEquals(title, article.oneLine)
        assertEquals(listOf(lead), article.ttsSentences)
        assertEquals("https://fixture.example/0", article.sourceUrl)
        assertTrue(article.detail.startsWith(lead))
        assertEquals(result.articles, DemoBriefingClient.parse(result.rawJson, true).articles)
    }

    @Test fun screenKeepsTitleWhileSpeechReadsTitleThenExactLeadAndCompletes() {
        val texts = mutableListOf<String>()
        var finish: () -> Unit = {}
        val speech = object : SpeechOutput {
            override fun speak(text: String, onStarted: () -> Unit, onDone: () -> Unit, onFailure: (String) -> Unit) {
                texts.add(text); finish = onDone; onStarted()
            }
            override fun stop() = Unit
        }
        compose.setContent {
            DemoBriefingScreen(speech, DemoBriefingLoader {
                DemoBriefingClient.parse(fixture(), true)
            }, approvedMode = true, autoPlay = false)
        }
        compose.onNodeWithText(title, substring = false).performScrollTo().assertIsDisplayed()
        compose.runOnIdle { assertTrue(texts.isEmpty()) }
        assertTextColor(title, Ink)
        assertTextColor(lead, InkSub)
        compose.onNodeWithText("재생", substring = false).performScrollTo().performClick()
        compose.runOnIdle { assertEquals(listOf(title), texts) }
        assertTextColor(title, Ink)
        assertTextColor(lead, InkSub)
        compose.runOnIdle { finish() }
        compose.waitUntil { texts.size == 2 }
        compose.runOnIdle { assertEquals(listOf(title, lead), texts) }
        compose.onNodeWithText("브리핑 전체 재생 완료").assertDoesNotExist()
        assertTextColor(title, Ink)
        assertTextColor(lead, Ink)
        compose.onNodeWithText("일시정지", substring = false).performScrollTo().performClick()
        assertTextColor(lead, InkSub)
        compose.onNodeWithText("재개", substring = false).performScrollTo().performClick()
        compose.waitUntil { texts.size == 3 }
        compose.runOnIdle { assertEquals(listOf(title, lead, lead), texts) }
        assertTextColor(lead, Ink)
        compose.runOnIdle { finish() }
        compose.onNodeWithText("브리핑 전체 재생 완료").performScrollTo().assertIsDisplayed()
        assertTextColor(lead, InkSub)
    }

    private fun assertTextColor(text: String, expected: Color) {
        val layouts = mutableListOf<TextLayoutResult>()
        compose.onNodeWithText(text, substring = false)
            .performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(layouts) }
        assertEquals(expected, layouts.single().layoutInput.style.color)
    }

    @Test fun titleFallbackIsHighlightedAndSpokenOnlyOnce() {
        val texts = mutableListOf<String>()
        var finish: () -> Unit = {}
        val speech = object : SpeechOutput {
            override fun speak(text: String, onStarted: () -> Unit, onDone: () -> Unit, onFailure: (String) -> Unit) {
                texts.add(text); finish = onDone; onStarted()
            }
            override fun stop() = Unit
        }
        compose.setContent {
            DemoBriefingScreen(speech, DemoBriefingLoader {
                DemoBriefingClient.parse(fixture(title), true)
            }, approvedMode = true, autoPlay = false)
        }
        compose.onNodeWithText("재생", substring = false).performScrollTo().performClick()
        assertTextColor(title, Ink)
        compose.runOnIdle { assertEquals(listOf(title), texts); finish() }
        compose.onNodeWithText("브리핑 전체 재생 완료").performScrollTo().assertIsDisplayed()
        assertTextColor(title, Ink)
    }

    @Test fun legacyTitleFallbackStillParsesForStoredHistory() {
        val article = DemoBriefingClient.parse(fixture(title), true).articles.single()
        assertEquals(title, article.title)
        assertEquals(listOf(title), article.ttsSentences)
    }
}
