package com.example.drivebrief

import com.example.drivebrief.ui.BriefingTime
import com.example.drivebrief.ui.visibleSentences
import org.junit.Assert.*
import org.junit.Test
import java.time.Instant

class BriefingTimeTest {
    private val now = Instant.parse("2026-11-14T03:45:00Z")

    @Test fun serverUtcIsShownInSeoulTimeWithAge() {
        assertEquals("11월 14일 오전 10:35 (2시간 전)", BriefingTime.line("2026-11-14T01:35:00+00:00", now))
    }

    @Test fun dateRollsOverToSeoulDay() {
        assertEquals("11월 14일 오전 12:10 (12시간 전)", BriefingTime.line("2026-11-13T15:10:00Z", now))
    }

    @Test fun relativeAgeUnits() {
        assertEquals("방금", BriefingTime.ago(now.plusSeconds(30), now))
        assertEquals("방금", BriefingTime.ago(now.minusSeconds(30), now))
        assertEquals("59분 전", BriefingTime.ago(now.minusSeconds(59 * 60), now))
        assertEquals("1시간 전", BriefingTime.ago(now.minusSeconds(60 * 60), now))
        assertEquals("1일 전", BriefingTime.ago(now.minusSeconds(24 * 3600), now))
        assertEquals("3일 전", BriefingTime.ago(now.minusSeconds(3 * 24 * 3600 + 100), now))
    }

    @Test fun unreadableValuesHideTheLine() {
        assertNull(BriefingTime.line(null, now))
        assertNull(BriefingTime.line("not-a-time", now))
    }

    @Test fun sentenceRepeatingTheTitleIsNotShownAgain() {
        val title = "'3D 디지털 휴먼' 지상파 데뷔…오모션·KBS 합작"
        val sentences = listOf(" $title ", "오모션이 가상인간을 선보였다.", "두 번째 설명.")
        assertEquals(listOf(1, 2), visibleSentences(title, sentences).map { it.index })
        assertEquals(listOf(0, 1), visibleSentences("다른 제목", sentences.drop(1)).map { it.index })
    }
}
