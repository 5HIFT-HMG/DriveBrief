package com.example.drivebrief

import com.example.drivebrief.audio.*
import org.junit.Assert.*
import org.junit.Test

class SpeechTimingTest {
    private class Fake : SpeechOutput {
        var start: () -> Unit = {}
        var done: () -> Unit = {}
        var error: (String) -> Unit = {}
        override fun speak(text: String, onStarted: () -> Unit, onDone: () -> Unit, onFailure: (String) -> Unit) {
            start = onStarted; done = onDone; error = onFailure
        }
        override fun stop() = Unit
    }
    private fun context() = TimingContext("session", "brief", "fiction", 0, "중간", 1)

    @Test fun measuresStartupAndPlaybackSeparatelyExactlyOnce() {
        var clock = 100L
        val records = mutableListOf<SpeechTiming>(); val fake = Fake()
        val out = MeasuredSpeechOutput(fake, records::add, "mock-test", { clock }, { 1000 })
        out.context = context()
        var finished = 0
        out.speak("가상 12명.", {}, { finished++ }, {})
        clock = 120; fake.start()
        clock = 620; fake.done(); fake.done(); out.stop()
        assertEquals(1, finished); assertEquals(1, records.size)
        assertEquals(20L, records[0].startupMs)
        assertEquals(500L, records[0].startToDoneMs)
        assertEquals(520L, records[0].requestToDoneMs)
        assertEquals("completed", records[0].outcome)
    }
    @Test fun stoppedAndLateCallbacksAreNotCompletedObservations() {
        var clock = 0L
        val fake = Fake(); val records = mutableListOf<SpeechTiming>()
        val out = MeasuredSpeechOutput(fake, records::add, "mock-test", { clock }, { 0 })
        out.context = context()
        var finished = 0
        out.speak("가상", {}, { finished++ }, {})
        fake.start(); clock = 50; val stale = fake.done
        out.stop(); stale()
        assertEquals(0, finished)
        assertEquals("stopped", records.single().outcome)
    }
    @Test fun featureCountsHandleUnicodeAndCollectorFailureDoesNotBreakPlayback() {
        val f = MeasuredSpeechOutput.features("가나 12, AB🙂")
        assertEquals(10, f.characters)
        assertEquals(2, f.hangul); assertEquals(2, f.digits); assertEquals(2, f.spaces)
        assertEquals(1, f.punctuation); assertEquals(2, f.latin); assertEquals(1, f.other)
        val fake = Fake()
        val out = MeasuredSpeechOutput(fake, { error("collector failed") }, "mock-test", { 1 }, { 0 })
        out.context = context()
        var done = false
        out.speak("가상", {}, { done = true }, {})
        fake.start(); fake.done()
        assertTrue(done)
    }
}
