package com.example.drivebrief

import com.example.drivebrief.data.*
import org.junit.Assert.*
import org.junit.Test

class OnePaperGateTest {
    private class MemoryStore(val values: MutableMap<String, String> = mutableMapOf()) : KeyValueStore {
        override fun get(key: String) = values[key]
        override fun put(key: String, value: String?) { if (value == null) values.remove(key) else values[key] = value }
    }

    @Test fun onlyParkOrUnreadableGearShowsOnePaperAndQr() {
        assertTrue(OnePaperGate.showOnFinish(GearState.PARK))
        assertTrue(OnePaperGate.showOnFinish(GearState.UNKNOWN))
        assertFalse(OnePaperGate.showOnFinish(GearState.DRIVING))
        assertFalse(OnePaperGate.showOnFinish(GearState.CHECKING))
        assertTrue(OnePaperGate.qrAllowed(GearState.PARK))
        assertTrue(OnePaperGate.qrAllowed(GearState.UNKNOWN))
        assertFalse(OnePaperGate.qrAllowed(GearState.DRIVING))
        assertFalse(OnePaperGate.qrAllowed(GearState.CHECKING))
    }

    @Test fun pendingSessionSurvivesRestartAndIsShownOnce() {
        val disk = MemoryStore()
        PendingOnePaper(disk).mark("session-1")
        val restarted = PendingOnePaper(disk)
        assertEquals("session-1", restarted.sessionId.value)
        assertNull(OnePaperGate.takeAutoShow(GearState.DRIVING, restarted))
        assertNull(OnePaperGate.takeAutoShow(GearState.CHECKING, restarted))
        assertEquals("session-1", OnePaperGate.takeAutoShow(GearState.PARK, restarted))
        assertNull(OnePaperGate.takeAutoShow(GearState.PARK, restarted))
        assertNull(PendingOnePaper(disk).sessionId.value)
    }

    @Test fun newerSessionReplacesOlderPending() {
        val pending = PendingOnePaper(MemoryStore())
        pending.mark("old")
        pending.mark("new")
        assertEquals("new", pending.take())
        assertNull(pending.take())
    }
}
