package com.example.drivebrief

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.test.platform.app.InstrumentationRegistry
import com.example.drivebrief.data.*
import com.example.drivebrief.ui.SessionPaper
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Rule
import org.junit.Test
import java.util.UUID

class OnePaperListTest {
    @get:Rule val compose = createComposeRule()

    @Test fun sessionRowsOpenDetailAndLongContentFoldsToThreeLines() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val history = SessionHistory(context, "test_onepaper_list_" + UUID.randomUUID())
        runBlocking { withTimeout(5000) { history.awaitReady() } }
        val long = List(12) { "긴 기사 내용의 ${it + 1}번째 문장이 이어집니다." }.joinToString(" ")
        history.start(DemoBriefingClient.parse(plannedFixture(), true))
        history.start(DemoBriefingClient.parse(plannedFixture().replace("전체 상세 1", long), true))
        var selected by mutableStateOf<String?>(null)
        compose.setContent {
            val snapshot by history.state.collectAsState()
            Column(Modifier.verticalScroll(rememberScrollState())) {
                SessionPaper(snapshot, selected = selected, onSelect = { selected = it })
            }
        }

        compose.onNodeWithText("청취 일시").assertIsDisplayed()
        compose.onAllNodesWithText("3건").assertCountEquals(2)
        compose.onNodeWithText("1. 연동 기사 1").assertDoesNotExist()

        // 최신 세션이 첫 행이다. 긴 내용은 3줄로 접히고, 짧은 내용에는 더보기가 없다.
        compose.onAllNodesWithText("3건").onFirst().performClick()
        compose.onNodeWithText("‹ 목록으로").assertIsDisplayed()
        compose.onNodeWithText("1. 연동 기사 1").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("전체 상세 2").performScrollTo().assertIsDisplayed()
        compose.onAllNodesWithText("더보기").assertCountEquals(1)
        compose.onNodeWithText("더보기").performScrollTo().performClick()
        compose.onNodeWithText("접기").performScrollTo().assertIsDisplayed()
        compose.onAllNodesWithText("RSS", substring = true).assertCountEquals(0)

        compose.onNodeWithText("‹ 목록으로").performScrollTo().performClick()
        compose.onNodeWithText("청취 일시").assertIsDisplayed()
        runBlocking { withTimeout(5000) { history.flush() } }
        history.close()
    }
}
