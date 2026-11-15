package com.example.drivebrief

import androidx.compose.foundation.layout.width
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.hasText
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.drivebrief.ui.newspaper.ClampText
import com.example.drivebrief.ui.theme.Ink
import com.example.drivebrief.ui.theme.serifStyle
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class ClampTextTest {
    @get:Rule val compose = createComposeRule()

    private fun shownText(): String = compose.onNode(hasText("", substring = true))
        .fetchSemanticsNode().config[SemanticsProperties.Text].joinToString("")

    @Test
    fun longTitleIsCutAtWordBoundaryWithDots() {
        val title = "아주 긴 기사 제목이 한 줄에 다 들어가지 않을 때 단어 단위로 잘라야 합니다"
        compose.setContent {
            ClampText(title, serifStyle(40.sp), Ink, maxLines = 1, modifier = Modifier.width(400.dp))
        }
        compose.waitForIdle()
        val shown = shownText()
        assertTrue(shown, shown.endsWith("···"))
        val kept = shown.removeSuffix("···")
        assertTrue(shown, title.startsWith(kept) && title[kept.length] == ' ')
    }

    @Test
    fun shortTitleIsUnchanged() {
        compose.setContent {
            ClampText("짧은 제목", serifStyle(40.sp), Ink, maxLines = 1, modifier = Modifier.width(400.dp))
        }
        compose.waitForIdle()
        assertEquals("짧은 제목", shownText())
    }
}
