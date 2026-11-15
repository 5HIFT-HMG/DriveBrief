package com.example.drivebrief

import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import com.example.drivebrief.audio.SpeechOutput
import com.example.drivebrief.data.*
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.*
import com.example.drivebrief.ui.NewsListScreen
import com.example.drivebrief.ui.MockNews
import org.junit.Rule
import org.junit.Test
import java.net.InetAddress
import java.net.ServerSocket
import kotlin.concurrent.thread

private val newsFixture = """
{"schema_version":"news-candidates-v1","total_candidates":1,"available_count":1,"offset":0,"has_more":false,
 "articles":[{"article_id":"rss_fixture","title":"합성 IT 기사","category":"IT","source":"테스트 출처",
 "published_at":"2026-11-07T12:28:00+09:00","description":"RSS 설명",
 "source_url":"https://example.com/article","content_level":"rss_description",
 "summary_status":"not_available","ai_eligible":false}]}
""".trimIndent()

class NewsListClientTest {
    @Test fun parsesMetadataAndEmptyListWithoutSummary() {
        val page = NewsListClient.parse(newsFixture)
        assertEquals("IT", page.articles.single().category)
        assertEquals("https://example.com/article", page.articles.single().sourceUrl)
        val empty = JSONObject(newsFixture).put("articles", org.json.JSONArray()).toString()
        assertTrue(NewsListClient.parse(empty).articles.isEmpty())
    }

    @Test fun rejectsInventedSummaryAndInvalidTypes() {
        listOf(
            newsFixture.replace("\"ai_eligible\":false", "\"ai_eligible\":true"),
            newsFixture.replace("\"rss_description\"", "\"full_text\""),
            newsFixture.replace("\"not_available\"", "\"completed\""),
            newsFixture.replace("https://example.com/article", "javascript:alert(1)"),
            newsFixture.replace("2026-11-07T12:28:00+09:00", "not a date")
        ).forEach {
            try { NewsListClient.parse(it); fail("Expected metadata policy rejection") }
            catch (_: NewsListException) { }
        }
    }

    @Test fun localHttpSuccessAndServerUnavailable() {
        ServerSocket(0, 1, InetAddress.getByName("127.0.0.1")).use { server ->
            server.soTimeout = 10000
            val worker = thread {
                server.accept().use { socket ->
                    socket.soTimeout = 5000
                    val input = socket.getInputStream().bufferedReader()
                    while (true) { val line = input.readLine() ?: break; if (line.isEmpty()) break }
                    val body = newsFixture.toByteArray(Charsets.UTF_8)
                    socket.getOutputStream().apply {
                        write("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: ${body.size}\r\nConnection: close\r\n\r\n".toByteArray())
                        write(body); flush()
                    }
                }
            }
            val page = runBlocking { NewsListClient("http://127.0.0.1:${server.localPort}").load(listOf("IT"), 0) }
            assertEquals("rss_fixture", page.articles.single().articleId)
            worker.join(3000)
        }
        val port = ServerSocket(0).use { it.localPort }
        runBlocking {
            try { NewsListClient("http://127.0.0.1:$port").load(null, 0); fail("Expected unavailable server") }
            catch (e: NewsListException) { assertTrue(e.message!!.contains("연결할 수 없습니다")) }
        }
    }
}

class NewsListUiTest {
    @get:Rule val compose = createComposeRule()

    private fun page(offset: Int = 0, hasMore: Boolean = false) = CollectedNewsPage(
        listOf(CollectedNews("fixture-$offset", "합성 IT 기사 $offset", "IT", "테스트 출처",
            "2026-11-07T12:28:00+09:00", "RSS 설명", "https://example.com/$offset")),
        if (hasMore) 21 else 1, if (hasMore) 21 else 1, offset, hasMore)

    @Test fun interestAndCategoryFiltersNeverStartTts() {
        val requests = mutableListOf<List<String>?>()
        var spoken = false
        val speech = object : SpeechOutput {
            override fun speak(text: String, onStarted: () -> Unit, onDone: () -> Unit, onFailure: (String) -> Unit) { spoken = true }
            override fun stop() = Unit
        }
        val loader = NewsListLoader { categories, _ -> requests.add(categories); page() }
        // 관심 분야는 IT 하나만 고른 상태다.
        compose.setContent { NewsListScreen(1 shl MockNews.categories.indexOf("IT"), loader) }
        compose.onNodeWithText("합성 IT 기사 0").assertIsDisplayed()
        compose.runOnIdle { assertEquals(listOf("IT"), requests.last()); assertFalse(spoken) }
        compose.onNodeWithText("전체", substring = false).performClick()
        compose.runOnIdle { assertNull(requests.last()); assertFalse(spoken) }
        compose.onNodeWithText("IT", substring = false).performClick()
        compose.runOnIdle { assertEquals(listOf("IT"), requests.last()); assertFalse(spoken) }
        compose.onNodeWithText("발행 2026-11-07 12:28 KST").assertIsDisplayed()
    }

    @Test fun failureRetryAndEmptyResult() {
        var requests = 0
        val loader = NewsListLoader { _, _ ->
            requests++
            if (requests == 1) throw NewsListException("뉴스 서버에 연결할 수 없습니다.")
            CollectedNewsPage(emptyList(), 0, 0, 0, false)
        }
        compose.setContent { NewsListScreen(MockNews.categories.indices.sumOf { 1 shl it }, loader) }
        compose.onNodeWithText("뉴스 서버에 연결할 수 없습니다.").assertIsDisplayed()
        compose.onNodeWithText("재시도", substring = false).performClick()
        compose.onNodeWithText("해당 조건의 뉴스가 없습니다.").assertIsDisplayed()
    }

    @Test fun pagingRequestsNextOffset() {
        val offsets = mutableListOf<Int>()
        val loader = NewsListLoader { _, offset -> offsets.add(offset); page(offset, offset == 0) }
        compose.setContent { NewsListScreen(MockNews.categories.indices.sumOf { 1 shl it }, loader) }
        compose.onNode(hasScrollAction()).performScrollToNode(hasText("다음 20개"))
        compose.onNodeWithText("다음 20개").performClick()
        compose.runOnIdle { assertEquals(20, offsets.last()) }
        compose.onNodeWithText("합성 IT 기사 20").assertIsDisplayed()
    }
}
