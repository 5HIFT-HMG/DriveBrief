package com.example.drivebrief

import android.media.AudioManager
import com.example.drivebrief.audio.BriefingFocus
import com.example.drivebrief.audio.FocusPort
import org.junit.Assert.*
import org.junit.Test

class BriefingFocusTest {
    private class FakePort(var result: Int = AudioManager.AUDIOFOCUS_REQUEST_GRANTED) : FocusPort {
        var requests = 0
        var abandons = 0
        var onChange: ((Int) -> Unit)? = null
        override fun request(onChange: (Int) -> Unit): Int { requests++; this.onChange = onChange; return result }
        override fun abandon() { abandons++ }
    }
    private class Events : BriefingFocus.Listener {
        val log = mutableListOf<String>()
        override fun onSystemPause(change: Int) { log.add("pause") }
        override fun onSystemResume() { log.add("resume") }
        override fun onPermanentLoss() { log.add("stop") }
    }
    private class Clock { var time = 10_000L; val tasks = mutableListOf<Pair<Long, () -> Unit>>()
        fun schedule(delay: Long, action: () -> Unit): () -> Unit {
            val task = (time + delay) to action; tasks.add(task); return { tasks.remove(task) }
        }
        fun advance(ms: Long) { time += ms; tasks.filter { it.first <= time }.forEach { tasks.remove(it); it.second() } }
    }

    private fun focus(port: FakePort = FakePort(), clock: Clock = Clock()): Triple<BriefingFocus, Events, Clock> {
        val events = Events()
        val focus = BriefingFocus(port, { clock.time }, clock::schedule, log = {})
        focus.listener = events
        return Triple(focus, events, clock)
    }

    @Test fun transientLossesPauseAndGainResumes() {
        for (loss in listOf(AudioManager.AUDIOFOCUS_LOSS_TRANSIENT, AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK)) {
            val (focus, events, clock) = focus()
            assertEquals(BriefingFocus.Start.GRANTED, focus.start())
            clock.advance(5_000)
            focus.onChange(loss)
            assertEquals(BriefingFocus.State.SYSTEM_PAUSED, focus.state)
            focus.onChange(AudioManager.AUDIOFOCUS_GAIN)
            assertEquals(listOf("pause", "resume"), events.log)
            assertEquals(BriefingFocus.State.HOLDING, focus.state)
        }
    }

    @Test fun permanentLossStopsAbandonsAndNeverResumes() {
        val port = FakePort()
        val (focus, events, _) = focus(port)
        focus.start()
        focus.onChange(AudioManager.AUDIOFOCUS_LOSS)
        focus.onChange(AudioManager.AUDIOFOCUS_GAIN)
        assertEquals(listOf("stop"), events.log)
        assertEquals(1, port.abandons)
        assertEquals(BriefingFocus.State.IDLE, focus.state)
    }

    @Test fun userPauseReleasesFocusSoLaterGainDoesNothing() {
        val port = FakePort()
        val (focus, events, _) = focus(port)
        focus.start()
        focus.release()
        focus.onChange(AudioManager.AUDIOFOCUS_GAIN)
        assertTrue(events.log.isEmpty())
        assertEquals(1, port.abandons)
        assertEquals(BriefingFocus.Start.GRANTED, focus.start())
        assertEquals(2, port.requests)
    }

    @Test fun failedRequestDoesNotHoldFocus() {
        val port = FakePort(AudioManager.AUDIOFOCUS_REQUEST_FAILED)
        val (focus, events, _) = focus(port)
        assertEquals(BriefingFocus.Start.FAILED, focus.start())
        assertEquals(BriefingFocus.State.IDLE, focus.state)
        focus.onChange(AudioManager.AUDIOFOCUS_GAIN)
        assertTrue(events.log.isEmpty())
    }

    @Test fun delayedRequestStartsOnlyWhenGranted() {
        val (focus, events, _) = focus(FakePort(AudioManager.AUDIOFOCUS_REQUEST_DELAYED))
        assertEquals(BriefingFocus.Start.DELAYED, focus.start())
        assertEquals(BriefingFocus.Start.DELAYED, focus.start())
        assertTrue(events.log.isEmpty())
        focus.onChange(AudioManager.AUDIOFOCUS_GAIN)
        assertEquals(listOf("resume"), events.log)
        assertEquals(BriefingFocus.State.HOLDING, focus.state)
    }

    @Test fun lossRightAfterResumeDefersNextResume() {
        val (focus, events, clock) = focus()
        focus.start()
        clock.advance(5_000)
        focus.onChange(AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK)
        focus.onChange(AudioManager.AUDIOFOCUS_GAIN)
        clock.advance(300)
        focus.onChange(AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK)
        focus.onChange(AudioManager.AUDIOFOCUS_GAIN)
        assertEquals(listOf("pause", "resume", "pause"), events.log)
        clock.advance(1_000)
        // 지연 중 다시 손실되면 예약한 재개를 취소한다.
        focus.onChange(AudioManager.AUDIOFOCUS_LOSS_TRANSIENT)
        clock.advance(5_000)
        assertEquals(listOf("pause", "resume", "pause"), events.log)
        focus.onChange(AudioManager.AUDIOFOCUS_GAIN)
        clock.advance(2_000)
        assertEquals(listOf("pause", "resume", "pause", "resume"), events.log)
    }

    @Test fun releaseIsIdempotentAndCancelsDeferredResume() {
        val port = FakePort()
        val (focus, events, clock) = focus(port)
        focus.start()
        clock.advance(5_000)
        focus.onChange(AudioManager.AUDIOFOCUS_LOSS_TRANSIENT)
        focus.onChange(AudioManager.AUDIOFOCUS_GAIN)
        focus.onChange(AudioManager.AUDIOFOCUS_LOSS_TRANSIENT)
        focus.onChange(AudioManager.AUDIOFOCUS_GAIN)
        focus.release(); focus.release()
        clock.advance(10_000)
        assertEquals(listOf("pause", "resume", "pause"), events.log)
        assertEquals(1, port.abandons)
    }
}
