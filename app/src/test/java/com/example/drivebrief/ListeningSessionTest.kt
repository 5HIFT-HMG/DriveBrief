package com.example.drivebrief

import com.example.drivebrief.data.*
import org.junit.Assert.*
import org.junit.Test

class ListeningSessionTest {
    private fun session(): ListeningSession {
        val items = (1..3).map { DemoNews("id-$it", "기사 $it", "가상", listOf("가상 첫 문장", "가상 두 문장"), "한 줄", "상세") }
        return ListeningSession("session", "brief", DemoBriefing(items, "{}"), 0)
    }
    @Test fun startsAreNotCompletionAndDuplicateDoneIgnored() {
        val initial = session()
        assertEquals(initial, initial.event(0, 0, "done", 1))
        val playing = initial.event(0, 0, "start", 2)
        assertEquals(ListeningStatus.PLAYING, playing.progress[0].status)
        val done = playing.event(0, 0, "done", 3)
        assertEquals(1, done.progress[0].completed.size)
        assertEquals(done, done.event(0, 0, "done", 4))
        assertFalse(done.fullyCompleted)
    }
    @Test fun pauseResumePreservesCursorAndDoneSet() {
        var s = session().event(0, 0, "start", 1).event(0, 0, "done", 2)
        s = s.event(0, 1, "start", 3).event(0, 1, "interrupt:pause", 4)
        assertEquals(ListeningStatus.INTERRUPTED, s.progress[0].status)
        assertEquals(1, s.progress[0].cursor)
        assertEquals(setOf(0), s.progress[0].completed)
        s = s.event(0, 1, "start", 5).event(0, 1, "done", 6)
        assertEquals(ListeningStatus.COMPLETED, s.progress[0].status)
    }
    @Test fun skipIsNotCompletionAndUnairedArticlesRemainUnheard() {
        var s = session().event(0, 0, "start", 1).event(0, 0, "skip_sentence", 2)
        s = s.event(0, 1, "start", 3).event(0, 1, "done", 4)
        assertEquals(ListeningStatus.SKIPPED, s.progress[0].status)
        assertEquals(1, s.progress[0].completed.size)
        assertEquals(ListeningStatus.UNHEARD, s.progress[2].status)
        assertFalse(s.event(0, 1, "end", 5).fullyCompleted)
    }
    @Test fun entireSessionCompletesOnlyWithAllCallbacks() {
        var s = session()
        for (a in 0..2) for (i in 0..1) s = s.event(a, i, "start", 1).event(a, i, "done", 2)
        assertFalse(s.fullyCompleted)
        s = s.event(2, 1, "end", 3)
        assertTrue(s.fullyCompleted)
        assertEquals(s, s.event(2, 1, "skip_article", 4))
    }
    @Test fun interruptionRestoreAndOutOfRange() {
        var s = session().event(0, 0, "start", 1).restored()
        assertEquals(ListeningStatus.INTERRUPTED, s.progress[0].status)
        assertEquals(s, s.event(20, 20, "done", 2))
        s = s.event(0, 0, "interrupt:stop", 3).event(0, 0, "end", 4)
        assertFalse(s.fullyCompleted)
        assertEquals(ListeningStatus.UNHEARD, s.progress[1].status)
    }
}
