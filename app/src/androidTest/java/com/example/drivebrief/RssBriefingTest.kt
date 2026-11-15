package com.example.drivebrief

import android.content.Intent
import android.util.Base64
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import com.example.drivebrief.data.*
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Rule
import org.junit.Test
import java.io.File

class RssBriefingTest {
    @get:Rule val compose = createEmptyComposeRule()

    private fun rss(preview: Boolean = false): String {
        val root = JSONObject(plannedFixture())
            .put("fictional_only", false).put("content_kind", "rss_metadata")
        val items = root.getJSONArray("articles")
        for (i in 0 until items.length()) items.getJSONObject(i)
            .put("content_kind", "rss_metadata").put("mock", false)
            .put("source_url", "https://example.test/synthetic/$i")
        if (preview) {
            root.put("schema_version", "private-rss-preview-v1").put("preview_only", true).put("publication_allowed", false)
            for (i in 0 until items.length()) items.getJSONObject(i).put("validation",
                JSONObject().put("status", "needs_review").put("approved", false).put("review_required", true))
        }
        return root.toString()
    }

    @Test fun approvedRssParsesAndUnapprovedCannotUseOrdinaryPath() {
        val approved = DemoBriefingClient.parse(rss(), true)
        assertEquals("rss_metadata", approved.articles.first().contentKind)
        assertFalse(approved.articles.first().mock!!)
        try { DemoBriefingClient.parse(rss(true), true); fail("Private data must not use ordinary parser") }
        catch (_: DemoApiException) { }
        val preview = DemoBriefingClient.parse(rss(true), true, true)
        assertEquals(3, preview.articles.size)
        val invalid = JSONObject(rss(true)).put("publication_allowed", true).toString()
        try { DemoBriefingClient.parse(invalid, true, true); fail("Preview must forbid publishing") }
        catch (_: DemoApiException) { }
    }

    @Test fun invalidOriginApprovalAndMissingUrlAreRejected() {
        for (raw in listOf(
            JSONObject(rss()).put("fictional_only", true).toString(),
            JSONObject(rss()).also { it.getJSONArray("articles").getJSONObject(0).remove("source_url") }.toString(),
            JSONObject(rss()).also { it.getJSONArray("articles").getJSONObject(0).getJSONObject("validation").put("approved", false) }.toString()
        )) {
            try { DemoBriefingClient.parse(raw, true); fail("Expected invalid RSS rejection") }
            catch (_: DemoApiException) { }
        }
    }

    /** Explicitly opted-in private RSS only. No Supabase auth, history upload or QR writes. */
    @Test fun privateRealRssHomePlaybackControlsAndLocalPaper() {
        val encoded = InstrumentationRegistry.getArguments().getString("privateRssBundle")
        assumeTrue("Pass an explicit private RSS bundle to exercise actual Pleos audio", encoded != null)
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val bundle = String(Base64.decode(encoded, Base64.DEFAULT), Charsets.UTF_8)
        val document = JSONObject(bundle).getJSONObject("짧게").toString()
        val expected = DemoBriefingClient.parse(document, true, true)
        assertTrue(expected.articles.isNotEmpty())
        File(context.filesDir, "private-rss-preview.json").writeText(bundle)
        ActivityScenario.launch<MainActivity>(
            Intent(context, MainActivity::class.java).putExtra("private_rss_preview", true)
        ).use {
            compose.onNodeWithText("짧게", substring = false).performScrollTo().performClick()
            compose.onNodeWithText("브리핑 시작(짧게)").performScrollTo().performClick()
            compose.waitUntil(10_000) { compose.onAllNodesWithText(expected.articles.first().title).fetchSemanticsNodes().isNotEmpty() }
            compose.onNodeWithText("비공개 RSS 테스트 · 미승인 · 게시 불가").performScrollTo().assertIsDisplayed()
            compose.onNodeWithText("재생", substring = false).performScrollTo().performClick()
            compose.waitUntil(20_000) { compose.onAllNodesWithText("기사 재생 중").fetchSemanticsNodes().isNotEmpty() }
            compose.onNodeWithText("일시정지", substring = false).performScrollTo().performClick()
            compose.onNodeWithText("재개", substring = false).performScrollTo().performClick()
            if (expected.articles.size > 1) {
                compose.onNodeWithText("다음 기사", substring = false).performScrollTo().performClick()
                compose.onNodeWithText("이전 기사", substring = false).performScrollTo().performClick()
            }
            compose.onNodeWithText("재생 중단(OnePaper)", substring = false).performScrollTo().performClick()
            compose.waitForIdle()
            val history = SessionHistory.getPrivatePreview(context)
            assertTrue(history.state.value.sessions.first().ended)
            assertFalse(history.state.value.sessions.first().fullyCompleted)
            // main now opens OnePaper in P, or returns home and defers it while driving.
            if (compose.onAllNodesWithText("홈으로", substring = false).fetchSemanticsNodes().isNotEmpty())
                compose.onNodeWithText("홈으로", substring = false).performClick()
            compose.onNodeWithText("브리핑 시작(짧게)").performScrollTo().performClick()
            compose.onNodeWithText("재생", substring = false).performScrollTo().performClick()
            compose.waitUntil(120_000) { history.state.value.sessions.first().fullyCompleted }
            compose.waitForIdle()
            kotlinx.coroutines.runBlocking { history.flush() }
            val restored = SessionHistory(context, "private_rss_preview_history_v1", true)
            kotlinx.coroutines.runBlocking { restored.awaitReady() }
            assertNull(restored.state.value.error)
            assertTrue(restored.state.value.sessions.first().fullyCompleted)
            restored.close()
            it.recreate()
            compose.onNodeWithText("일시정지", substring = false).assertDoesNotExist()
            if (compose.onAllNodesWithText("미승인 RSS 비공개 테스트 기록").fetchSemanticsNodes().isEmpty())
                compose.onNodeWithText("OnePaper 보기", substring = false).performClick()
            compose.onNodeWithText("미승인 RSS 비공개 테스트 기록").performScrollTo().assertIsDisplayed()
            compose.onAllNodesWithText(expected.articles.first().title, substring = true).onFirst().performScrollTo().assertIsDisplayed()
            compose.onNodeWithText("폰으로 이어보기").assertDoesNotExist()
        }
    }
}
