package com.example.drivebrief

import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import com.example.drivebrief.audio.SpeechOutput
import com.example.drivebrief.data.*
import com.example.drivebrief.ui.DriveBriefApp
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

private class HomeConnection(url: java.net.URL, private val code: Int, private val body: String) : java.net.HttpURLConnection(url) {
    val sent = java.io.ByteArrayOutputStream()
    override fun connect() { }
    override fun disconnect() { }
    override fun usingProxy() = false
    override fun getOutputStream() = sent
    override fun getInputStream() = java.io.ByteArrayInputStream(body.toByteArray())
    override fun getResponseCode() = code
}

class HomeBriefingTest {
    @get:Rule val compose = createComposeRule()
    private class Speech : SpeechOutput {
        val texts = mutableListOf<String>()
        override fun speak(text: String, onStarted: () -> Unit, onDone: () -> Unit, onFailure: (String) -> Unit) { texts.add(text) }
        override fun stop() = Unit
    }

    @Test fun homeHasNoDevelopmentEntriesAndStartsServerBriefing() {
        val requests = mutableListOf<Pair<String, List<String>>>()
        val speech = Speech()
        compose.setContent {
            DriveBriefApp(speech, newsLoader = NewsListLoader { _, _ -> error("no news screen") },
                briefingLoader = { length, categories ->
                    requests.add(length to categories)
                    DemoBriefingLoader { DemoBriefingClient.parse(plannedFixture(), true) }
                })
        }
        listOf("개발용", "개발용 AI 브리핑 불러오기", "검토 승인 브리핑 불러오기", "개발용 실제 뉴스 목록").forEach {
            compose.onNodeWithText(it, substring = false).assertDoesNotExist()
        }
        compose.onNodeWithText("짧게", substring = false).performScrollTo().performClick()
        compose.onNodeWithText("스포츠", substring = false).performScrollTo().performClick()
        compose.onNodeWithText("브리핑 시작(짧게)").performScrollTo().performClick()
        compose.onNodeWithText("오늘의 브리핑", substring = false).assertIsDisplayed()
        compose.onNodeWithText("연동 기사 1").performScrollTo().assertIsDisplayed()
        compose.runOnIdle {
            assertEquals("짧게" to listOf("경제", "사회", "정치", "IT"), requests.single())
            // 브리핑 시작을 누르면 재생 버튼 없이 첫 문장부터 읽는다.
            assertEquals("첫 문장 1", speech.texts.last())
        }
        compose.onNodeWithText("기사 재생 중", substring = false).performScrollTo().assertIsDisplayed()
        val wave = compose.onNodeWithContentDescription("음성 재생 표시")
        wave.assert(SemanticsMatcher.expectValue(SemanticsProperties.StateDescription, "읽는 중"))
        compose.onNodeWithText("일시정지", substring = false).performScrollTo().performClick()
        compose.onNodeWithText("기사 일시정지됨", substring = false).performScrollTo().assertIsDisplayed()
        wave.assert(SemanticsMatcher.expectValue(SemanticsProperties.StateDescription, "멈춤"))
    }

    @Test fun missingPublishedBriefingShowsGuidanceAndRetry() {
        compose.setContent {
            DriveBriefApp(null, newsLoader = NewsListLoader { _, _ -> error("no news screen") },
                briefingLoader = { _, _ -> DemoBriefingLoader { throw DemoApiException(CloudBriefingLoader.NOT_READY) } })
        }
        compose.onNodeWithText("브리핑 시작(중간)").performScrollTo().performClick()
        compose.onNodeWithText(CloudBriefingLoader.NOT_READY).performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("재시도", substring = false).assertIsDisplayed()
        compose.onNodeWithText("재생", substring = false).assertDoesNotExist()
    }

    @Test fun cloudLoaderOpensAnonymousSessionReadsRpcAndFiltersCategories() = runBlocking {
        val anonymous = """{"access_token":"anon","refresh_token":"r","expires_in":3600,"user":{"id":"12345678-1234-1234-1234-1234567890aa","is_anonymous":true}}"""
        val calls = mutableListOf<HomeConnection>()
        val client = SupabaseNewsClient(openConnection = { url ->
            HomeConnection(url, 200, if (url.path == "/auth/v1/signup") anonymous else plannedFixture()).also { calls.add(it) }
        })
        val briefing = CloudBriefingLoader(client, "짧게", listOf("경제")).load()
        assertEquals(listOf("/auth/v1/signup", "/rest/v1/rpc/read_published_briefing"), calls.map { it.url.path })
        assertEquals("짧게", JSONObject(calls.last().sent.toString("UTF-8")).getString("p_length"))
        assertEquals("Bearer anon", calls.last().getRequestProperty("Authorization"))
        assertEquals(3, briefing.articles.size)
        try { CloudBriefingLoader(client, "짧게", listOf("스포츠")).load(); fail("Expected no match") }
        catch (e: DemoApiException) { assertEquals(CloudBriefingLoader.NO_MATCH, e.message) }
    }

    @Test fun cloudLoaderReportsNothingPublishedAndKeepsFictionalGuard() = runBlocking {
        val anonymous = """{"access_token":"anon","refresh_token":"r","expires_in":3600,"user":{"id":"12345678-1234-1234-1234-1234567890aa","is_anonymous":true}}"""
        var reply = "null"
        val client = SupabaseNewsClient(openConnection = { url ->
            HomeConnection(url, 200, if (url.path == "/auth/v1/signup") anonymous else reply)
        })
        try { CloudBriefingLoader(client, "중간", listOf("경제")).load(); fail("Expected not ready") }
        catch (e: DemoApiException) { assertEquals(CloudBriefingLoader.NOT_READY, e.message) }
        reply = plannedFixture().replace("\"fictional_only\":true", "\"fictional_only\":false")
        try { CloudBriefingLoader(client, "중간", listOf("경제")).load(); fail("Real articles stay blocked until policy changes") }
        catch (_: DemoApiException) { }
    }
}
