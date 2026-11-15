package com.example.drivebrief

import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import com.example.drivebrief.audio.SpeechOutput
import com.example.drivebrief.data.*
import com.example.drivebrief.ui.DriveBriefApp
import com.example.drivebrief.ui.QR_PARK_ONLY
import com.example.drivebrief.ui.SessionPaper
import kotlinx.coroutines.flow.MutableStateFlow
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

class GearOnePaperTest {
    @get:Rule val compose = createComposeRule()
    private class MemoryStore : KeyValueStore {
        val values = mutableMapOf<String, String>()
        override fun get(key: String) = values[key]
        override fun put(key: String, value: String?) { if (value == null) values.remove(key) else values[key] = value }
    }
    private class Speech : SpeechOutput {
        override fun speak(text: String, onStarted: () -> Unit, onDone: () -> Unit, onFailure: (String) -> Unit) = onStarted()
        override fun stop() = Unit
    }

    private fun open(gear: MutableStateFlow<GearState>, pending: PendingOnePaper) {
        compose.setContent {
            DriveBriefApp(Speech(), newsLoader = NewsListLoader { _, _ -> error("unused") },
                briefingLoader = { _, _ -> DemoBriefingLoader { DemoBriefingClient.parse(plannedFixture(), true) } },
                gear = gear, pendingOnePaper = pending)
        }
    }
    private fun playThenStop() {
        compose.onNodeWithText("브리핑 시작(중간)").performScrollTo().performClick()
        // 기기에 쌓인 청취 기록을 다 읽어야 재생 화면이 나오고, 브리핑 시작만으로 재생된다.
        compose.waitUntil(10_000) { compose.onAllNodesWithText("기사 재생 중", substring = false).fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("재생 중단(OnePaper)", substring = false).performScrollTo().performClick()
        compose.waitForIdle()
    }

    @Test fun finishingWhileDrivingDefersOnePaperUntilPark() {
        val gear = MutableStateFlow(GearState.DRIVING)
        val pending = PendingOnePaper(MemoryStore())
        open(gear, pending)
        playThenStop()
        compose.onNodeWithText("오늘의 이동,\n나만의 브리핑").assertIsDisplayed()
        compose.onNodeWithText("정차 후 읽는 나의 브리핑").assertDoesNotExist()
        val deferred = pending.sessionId.value
        assertNotNull(deferred)

        gear.value = GearState.PARK
        compose.waitUntil(5_000) { compose.onAllNodesWithText("정차 후 읽는 나의 브리핑").fetchSemanticsNodes().isNotEmpty() }
        compose.onAllNodesWithText("폰으로 이어보기").onFirst().assertExists()
        assertNull(pending.sessionId.value)

        // 한 번 보여준 세션은 다시 자동으로 띄우지 않는다.
        compose.onNodeWithText("홈으로").performClick()
        gear.value = GearState.DRIVING
        gear.value = GearState.PARK
        compose.waitForIdle()
        compose.onNodeWithText("정차 후 읽는 나의 브리핑").assertDoesNotExist()
    }

    @Test fun finishingWhileParkedOpensOnePaperWithoutPending() {
        val gear = MutableStateFlow(GearState.PARK)
        val pending = PendingOnePaper(MemoryStore())
        open(gear, pending)
        playThenStop()
        compose.onNodeWithText("정차 후 읽는 나의 브리핑").assertIsDisplayed()
        // 방금 들은 세션 상세가 바로 열린다.
        compose.onNodeWithText("‹ 목록으로").assertExists()
        compose.onNodeWithText("1. 연동 기사 1").performScrollTo().assertIsDisplayed()
        assertNull(pending.sessionId.value)
    }

    @Test fun pendingSessionFromEarlierDriveOpensOnLaunchInPark() {
        val pending = PendingOnePaper(MemoryStore()).apply { mark("earlier-session") }
        open(MutableStateFlow(GearState.PARK), pending)
        compose.waitUntil(5_000) { compose.onAllNodesWithText("정차 후 읽는 나의 브리핑").fetchSemanticsNodes().isNotEmpty() }
        assertNull(pending.sessionId.value)
    }

    @Test fun pendingSessionStaysWhileGearIsStillChecking() {
        val pending = PendingOnePaper(MemoryStore()).apply { mark("earlier-session") }
        open(MutableStateFlow(GearState.CHECKING), pending)
        compose.waitForIdle()
        compose.onNodeWithText("정차 후 읽는 나의 브리핑").assertDoesNotExist()
        assertEquals("earlier-session", pending.sessionId.value)
    }

    @Test fun qrIsRefusedWhileDrivingAndClosesWhenLeavingPark() {
        val history = runCatching {
            val context = androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().targetContext
            SessionHistory(context, "test_gear_qr_" + java.util.UUID.randomUUID())
        }.getOrThrow()
        kotlinx.coroutines.runBlocking { history.awaitReady() }
        val sessionId = history.start(DemoBriefingClient.parse(plannedFixture(), true))
        val allowed = mutableStateOf(false)
        val share = OnePaperShare("AbCdEfGhIjKlMnOpQr_-12", System.currentTimeMillis() + 3_600_000)
        compose.setContent {
            val snapshot = history.state.collectAsState().value
            // 앱의 OnePaper 화면처럼 스크롤 열 안에 둔다.
            androidx.compose.foundation.layout.Column(androidx.compose.ui.Modifier
                .verticalScroll(androidx.compose.foundation.rememberScrollState())) {
                SessionPaper(snapshot, { share }, qrAllowed = allowed.value, selected = sessionId)
            }
        }
        compose.onNodeWithText("폰으로 이어보기").performScrollTo().performClick()
        compose.onNodeWithText(QR_PARK_ONLY, substring = true).assertExists()
        compose.onNodeWithContentDescription("OnePaper 링크 QR").assertDoesNotExist()

        allowed.value = true
        compose.onNodeWithText("폰으로 이어보기").performScrollTo().performClick()
        compose.onNodeWithContentDescription("OnePaper 링크 QR").assertExists()
        allowed.value = false
        compose.waitForIdle()
        compose.onNodeWithContentDescription("OnePaper 링크 QR").assertDoesNotExist()
        kotlinx.coroutines.runBlocking { history.flush() }
        history.close()
    }
}
