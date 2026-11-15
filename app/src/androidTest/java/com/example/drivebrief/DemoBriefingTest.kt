package com.example.drivebrief

import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import com.example.drivebrief.audio.SpeechOutput
import com.example.drivebrief.data.*
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import com.example.drivebrief.ui.DemoBriefingScreen
import org.junit.Rule
import org.junit.Test
import java.net.InetAddress
import java.net.ServerSocket
import kotlin.concurrent.thread

private val demoFixture = """
{
 "schema_version":"demo-briefing-v1","demo_only":true,"fictional_only":true,
 "playback_requires_user_action":true,
 "articles":[{
   "article_id":"test-fiction","title":"가상 API 테스트","source":"자체 가상 자료",
   "tts_sentences":["가상 첫 번째 문장입니다.","가상 두 번째 문장입니다."],
   "one_line":"가상 테스트의 한 줄 요약입니다.","detail":"가상 테스트의 상세 요약입니다.",
   "validation":{"status":"needs_review","approved":false,"review_required":true}
 }]
}
""".trimIndent()

class DemoBriefingClientTest {
    @Test fun parsesExactSentencesAndEmptyList() {
        val result = DemoBriefingClient.parse(demoFixture)
        assertEquals(listOf("가상 첫 번째 문장입니다.", "가상 두 번째 문장입니다."), result.articles[0].ttsSentences)
        val empty = org.json.JSONObject(demoFixture).put("articles", org.json.JSONArray()).toString()
        assertTrue(DemoBriefingClient.parse(empty).articles.isEmpty())
    }

    @Test fun rejectsNonDemoApprovedAndMalformedPayloads() {
        val invalid = listOf(
            demoFixture.replace("\"demo_only\":true", "\"demo_only\":false"),
            demoFixture.replace("\"approved\":false", "\"approved\":true"),
            demoFixture.replace("\"fictional_only\":true", "\"fictional_only\":\"true\""),
            "{invalid"
        )
        invalid.forEach {
            try { DemoBriefingClient.parse(it); fail("Expected guarded response rejection") }
            catch (_: DemoApiException) { }
        }
    }

    @Test fun httpSuccessAndConnectionFailure() {
        ServerSocket(0, 1, InetAddress.getByName("127.0.0.1")).use { server ->
            server.soTimeout = 10_000
            val worker = thread {
                server.accept().use { socket ->
                    socket.soTimeout = 5000
                    val reader = socket.getInputStream().bufferedReader()
                    while (true) { val line = reader.readLine() ?: break; if (line.isEmpty()) break }
                    val body = demoFixture.toByteArray(Charsets.UTF_8)
                    socket.getOutputStream().apply {
                        write("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: ${body.size}\r\nConnection: close\r\n\r\n".toByteArray())
                        write(body); flush()
                    }
                }
            }
            val result = runBlocking { DemoBriefingClient("http://127.0.0.1:${server.localPort}").load() }
            assertEquals("test-fiction", result.articles.single().articleId)
            worker.join(3000)
        }
        val closedPort = ServerSocket(0).use { it.localPort }
        runBlocking {
            try { DemoBriefingClient("http://127.0.0.1:$closedPort").load(); fail("Expected connection failure") }
            catch (e: DemoApiException) { assertTrue(e.message!!.contains("서버에 연결할 수 없습니다")) }
        }
    }
}

class DemoBriefingUiTest {
    @get:Rule val compose = createComposeRule()

    private class FakeSpeech : SpeechOutput {
        val texts = mutableListOf<String>()
        var onStart: () -> Unit = {}
        var onDone: () -> Unit = {}
        override fun speak(text: String, onStarted: () -> Unit, onDone: () -> Unit, onFailure: (String) -> Unit) {
            texts.add(text); onStart = onStarted; this.onDone = onDone
        }
        override fun stop() = Unit
    }

    @Test fun explicitPlayPauseResumeAndSkipUseServerSentences() {
        val speech = FakeSpeech()
        compose.setContent {
            DemoBriefingScreen(speech, DemoBriefingLoader { DemoBriefingClient.parse(demoFixture) })
        }
        compose.onNodeWithText("가상 API 테스트").performScrollTo().assertIsDisplayed()
        compose.runOnIdle { assertTrue(speech.texts.isEmpty()) }
        compose.onNodeWithText("데모 재생", substring = false).performScrollTo().performClick()
        lateinit var staleDone: () -> Unit
        compose.runOnIdle {
            assertEquals("가상 첫 번째 문장입니다.", speech.texts.last())
            speech.onStart()
            staleDone = speech.onDone
        }
        compose.onNodeWithText("일시정지", substring = false).performScrollTo().performClick()
        compose.runOnIdle { staleDone() }
        compose.onNodeWithText("재개", substring = false).performScrollTo().performClick()
        compose.runOnIdle {
            assertEquals("가상 첫 번째 문장입니다.", speech.texts.last())
            speech.onStart(); speech.onDone()
        }
        compose.waitForIdle()
        compose.runOnIdle { assertEquals("가상 두 번째 문장입니다.", speech.texts.last()) }
        compose.onNodeWithText("다음 문장", substring = false).performScrollTo().performClick()
        compose.onNodeWithText("데모 재생 종료(건너뛴 문장 있음)").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("데모 기사 재생 완료").assertDoesNotExist()
    }

    @Test fun completedDemoOffersExplicitRestart() {
        val speech = FakeSpeech()
        compose.setContent {
            DemoBriefingScreen(speech, DemoBriefingLoader { DemoBriefingClient.parse(demoFixture) })
        }
        compose.onNodeWithText("데모 재생", substring = false).performScrollTo().performClick()
        repeat(2) {
            compose.runOnIdle { speech.onStart(); speech.onDone() }
            compose.waitForIdle()
        }
        compose.onNodeWithText("데모 기사 재생 완료").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("다시 재생", substring = false).performScrollTo().performClick()
        compose.runOnIdle { assertEquals("가상 첫 번째 문장입니다.", speech.texts.last()) }
    }

    @Test fun serverUnavailableShowsRetryAndRecovers() {
        var attempts = 0
        val loader = DemoBriefingLoader {
            attempts++
            if (attempts == 1) throw DemoApiException("서버에 연결할 수 없습니다.")
            DemoBriefingClient.parse(demoFixture)
        }
        compose.setContent { DemoBriefingScreen(null, loader) }
        compose.onNodeWithText("서버에 연결할 수 없습니다.").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("재시도", substring = false).performScrollTo().performClick()
        compose.onNodeWithText("가상 API 테스트").performScrollTo().assertIsDisplayed()
    }

    @Test fun emptyNewsDoesNotOfferPlayback() {
        val empty = org.json.JSONObject(demoFixture).put("articles", org.json.JSONArray()).toString()
        compose.setContent { DemoBriefingScreen(null, DemoBriefingLoader { DemoBriefingClient.parse(empty) }) }
        compose.onNodeWithText("불러온 뉴스가 없습니다.").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("데모 재생", substring = false).assertDoesNotExist()
    }
}
