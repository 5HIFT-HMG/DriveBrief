package com.example.drivebrief

import android.content.Intent
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import com.example.drivebrief.data.*
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Rule
import org.junit.Test

internal fun autoRssFixture(option: String = "중간", count: Int = 25): String {
    val limit = mapOf("짧게" to 1, "중간" to 3, "길게" to 5).getValue(option)
    val articles = JSONArray()
    repeat(count) { i ->
        articles.put(JSONObject().apply {
            put("article_id", "synthetic-rss-$i"); put("title", "합성 RSS 소식 $i"); put("source", "자체 합성 자료")
            put("published_at", "2026-11-14T00:00:00+00:00"); put("source_url", "https://fixture.example/$i")
            put("content_kind", "rss_metadata"); put("one_line", "합성 RSS 소식 $i"); put("detail", "합성 설명입니다.")
            put("tts_sentences", JSONArray((0 until limit).map { "합성 기사 $i 문장 $it" }))
            put("available_sentence_count", 5); put("sentence_indices", JSONArray((0 until limit).toList()))
            put("partial_tts", limit < 5); put("categories", JSONArray(listOf("사회")))
            put("order", i+1); put("group_id", "synthetic-group-$i"); put("importance_score", 0.5)
            put("validation", JSONObject().put("status", "rss_auto_validated")
                .put("method", "metadata_exact_extract_v1").put("human_reviewed", false))
        })
    }
    return JSONObject().apply {
        put("schema_version", "rss-briefing-v1"); put("content_kind", "rss_metadata")
        put("processing", "automatic_metadata_extraction"); put("usage_rights_status", "source_terms_not_verified")
        put("option_semantics", "article_detail"); put("playback_requires_user_action", true)
        put("catalog_id", "rss-synthetic-catalog"); put("input_revision", "synthetic-revision")
        put("briefing_id", "rss-synthetic-$limit"); put("length_option", option); put("sentence_limit", limit)
        put("generated_at", "2026-11-14T00:01:00+00:00"); put("latest_source_at", "2026-11-14T00:00:00+00:00")
        put("articles", articles)
    }.toString()
}

class RssAutoBriefingTest {
    @get:Rule val compose = createEmptyComposeRule()

    @Test fun parses25AndSameIdsWith135SentencesWithoutApproval() {
        val variants = listOf("짧게", "중간", "길게").map { DemoBriefingClient.parse(autoRssFixture(it), true) }
        assertEquals(25, variants[0].articles.size)
        assertEquals(variants[0].articles.map { it.articleId }, variants[1].articles.map { it.articleId })
        assertEquals(variants[0].articles.map { it.articleId }, variants[2].articles.map { it.articleId })
        assertEquals(listOf(1,3,5), variants.map { it.articles.first().ttsSentences.size })
        assertTrue(variants.all { it.targetSeconds == null && it.optionSemantics == "article_detail" })
        assertTrue(variants.all { it.articles.all { a -> a.mock == null } })
    }

    @Test fun rejectsForgedApprovalWrongLimitPrivateAndOversize() {
        val bad = JSONObject(autoRssFixture())
        bad.getJSONArray("articles").getJSONObject(0).getJSONObject("validation").put("approved", true)
        for (raw in listOf(bad.toString(), autoRssFixture(count=26),
            JSONObject(autoRssFixture()).put("sentence_limit", 5).toString())) {
            try { DemoBriefingClient.parse(raw, true); fail("Invalid automatic RSS accepted") }
            catch (_: DemoApiException) { }
        }
        assertTrue(DemoBriefingClient.parse(autoRssFixture(count=0), true).articles.isEmpty())
    }

    @Test fun anonymousPublishedRpcAcceptsAutomaticRssAndCategories() = runBlocking {
        val calls = mutableListOf<String>()
        val session = """{"access_token":"fixture-access","refresh_token":"fixture-refresh","expires_in":3600,"user":{"id":"12345678-1234-1234-1234-1234567890aa","is_anonymous":true}}"""
        val client = SupabaseNewsClient(openConnection = { url ->
            object : java.net.HttpURLConnection(url) {
                override fun connect() = Unit
                override fun disconnect() = Unit
                override fun usingProxy() = false
                override fun getOutputStream() = java.io.ByteArrayOutputStream()
                override fun getResponseCode() = 200
                override fun getInputStream(): java.io.InputStream {
                    calls.add(url.path)
                    return (if (url.path.endsWith("signup")) session else autoRssFixture()).byteInputStream()
                }
            }
        })
        val result = CloudBriefingLoader(client, "중간", listOf("사회")).load()
        assertEquals(25, result.articles.size)
        assertEquals(listOf("/auth/v1/signup", "/rest/v1/rpc/read_published_briefing"), calls)
        try { CloudBriefingLoader(client, "중간", listOf("IT")).load(); fail("Expected empty category") }
        catch (e: DemoApiException) { assertEquals(CloudBriefingLoader.NO_MATCH, e.message) }
    }

    @Test fun large25ArticleHistoryRestoresWithinCloudBudget() = runBlocking {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val name = "test_rss_budget_" + java.util.UUID.randomUUID()
        val raw = JSONObject(autoRssFixture("길게"))
        val items = raw.getJSONArray("articles")
        repeat(items.length()) { items.getJSONObject(it).put("detail", "가".repeat(2400)) }
        val briefing = DemoBriefingClient.parse(raw.toString(), true)
        val history = SessionHistory(context, name)
        history.awaitReady()
        var latest = ""
        repeat(20) { latest = history.start(briefing) }
        history.flush()
        val stored = context.getSharedPreferences(name, android.content.Context.MODE_PRIVATE).getString("sessions", null)!!
        assertTrue(stored.toByteArray(Charsets.UTF_8).size <= 450_000)
        val restored = SessionHistory(context, name)
        restored.awaitReady()
        assertNull(restored.state.value.error)
        assertEquals(latest, restored.state.value.sessions.first().sessionId)
        assertEquals(25, restored.state.value.sessions.first().briefing.articles.size)
        assertTrue(restored.state.value.sessions.size < 20)
        restored.close(); history.close()
    }

    /** Opt-in actual cloud path: ordinary MainActivity, no injected loader, local JSON or debug flag. */
    @Test fun liveNormalHomeRssPlaybackHistoryAndOptionalQr() {
        assumeTrue(InstrumentationRegistry.getArguments().getString("liveRss") == "true")
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val launchedAt = System.currentTimeMillis()
        ActivityScenario.launch<MainActivity>(Intent(context, MainActivity::class.java)).use {
            compose.onNodeWithText("짧게", substring=false).performScrollTo().performClick()
            compose.onNodeWithText("브리핑 시작(짧게)").performScrollTo().performClick()
            val history = SessionHistory.get(context)
            compose.waitUntil(45_000) {
                history.state.value.sessions.firstOrNull()?.let { s ->
                    s.createdAt >= launchedAt && s.briefing.optionSemantics == "article_detail"
                } == true
            }
            val session = history.state.value.sessions.first()
            assertEquals(25, session.briefing.articles.size)
            val first = session.briefing.articles.first()
            assertNotEquals(first.title, first.ttsSentences.single())
            assertTrue(first.detail.contains(first.ttsSentences.single()))
            compose.onNodeWithText(first.title, substring=false).performScrollTo().assertIsDisplayed()
            assertTrue(session.briefing.articles.all { a -> a.sourceUrl != null && !a.sourceUrl.contains("fixture.example") })
            compose.onAllNodesWithText("RSS 제목·설명 (AI 요약 아님)").assertCountEquals(0)
            compose.waitUntil(25_000) {
                history.state.value.sessions.first().progress.any { p -> p.started.isNotEmpty() }
            }
            InstrumentationRegistry.getInstrumentation().sendStatus(2, android.os.Bundle().apply {
                putString("drivebrief_live_rss", "normal_cloud_tts_started_25_articles")
            })
            compose.waitUntil(60_000) {
                history.state.value.sessions.first().progress.first().completed.contains(0)
            }
            compose.onNodeWithText("일시정지", substring=false).performScrollTo().performClick()
            compose.onNodeWithText("재개", substring=false).performScrollTo().performClick()
            compose.onNodeWithText("다음 기사", substring=false).performScrollTo().performClick()
            compose.waitUntil(30_000) {
                history.state.value.sessions.first().progress.any { p -> p.completed.isNotEmpty() }
            }
            compose.onNodeWithText("재생 중단(OnePaper)", substring=false).performScrollTo().performClick()
            compose.waitForIdle()
            runBlocking { history.flush() }
            assertTrue(history.state.value.sessions.first().ended)
            assertFalse(history.state.value.sessions.first().fullyCompleted)
            if (compose.onAllNodesWithText("브리핑 청취 기록").fetchSemanticsNodes().isEmpty())
                compose.onNodeWithText("OnePaper 보기").performClick()
            listOf("RSS 설명 보기", "원문 링크 열기", "브리핑 종료(미완료)").forEach { compose.onAllNodesWithText(it).assertCountEquals(0) }
            compose.waitUntil(40_000) { history.state.value.cloudStatus == "DB 동기화 완료" }
            if (InstrumentationRegistry.getArguments().getString("liveQr") == "true") {
                compose.onAllNodesWithText("폰으로 이어보기").onFirst().performScrollTo().performClick()
                compose.waitUntil(25_000) {
                    compose.onAllNodesWithContentDescription("OnePaper 링크 QR").fetchSemanticsNodes().isNotEmpty()
                }
            }
        }
    }
}
