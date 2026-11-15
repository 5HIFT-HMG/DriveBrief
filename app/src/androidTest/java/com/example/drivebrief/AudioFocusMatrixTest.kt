package com.example.drivebrief

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.os.Handler
import android.os.Looper
import android.util.Log
import androidx.test.platform.app.InstrumentationRegistry
import com.example.drivebrief.audio.AndroidFocusPort
import com.example.drivebrief.audio.BriefingFocus
import com.example.drivebrief.audio.FocusPort
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.CopyOnWriteArrayList

/**
 * 실제 CarAudioService에서 경쟁 포커스를 만들어 브리핑 포커스가 받는 콜백을 확인한다.
 * 결과는 logcat의 AudioFocusMatrix 태그로 남긴다.
 */
class AudioFocusMatrixTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val audio = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
    private val main = Handler(Looper.getMainLooper())

    private class Recording(private val inner: FocusPort, val changes: MutableList<String>) : FocusPort {
        override fun request(onChange: (Int) -> Unit) =
            inner.request { changes.add(BriefingFocus.name(it)); onChange(it) }
        override fun abandon() = inner.abandon()
    }

    private data class Outcome(val label: String, val competitor: String, val briefing: List<String>, val events: List<String>)

    private fun scenario(label: String, usage: Int, gain: Int): Outcome {
        val changes = CopyOnWriteArrayList<String>()
        val events = CopyOnWriteArrayList<String>()
        val focus = BriefingFocus(Recording(AndroidFocusPort(context), changes), log = {})
        focus.listener = object : BriefingFocus.Listener {
            override fun onSystemPause(change: Int) { events.add("pause") }
            override fun onSystemResume() { events.add("resume") }
            override fun onPermanentLoss() { events.add("stop") }
        }
        var start: BriefingFocus.Start? = null
        InstrumentationRegistry.getInstrumentation().runOnMainSync { start = focus.start() }
        assertEquals(BriefingFocus.Start.GRANTED, start)
        val competitor = try {
            AudioFocusRequest.Builder(gain)
                .setAudioAttributes(AudioAttributes.Builder().setUsage(usage).build())
                .setOnAudioFocusChangeListener({ }, main).build()
        } catch (e: IllegalArgumentException) {
            InstrumentationRegistry.getInstrumentation().runOnMainSync { focus.release() }
            return Outcome(label, "요청 불가(${e.message?.take(40)})", changes, events)
        }
        val result = audio.requestAudioFocus(competitor)
        Thread.sleep(1_500)
        audio.abandonAudioFocusRequest(competitor)
        Thread.sleep(3_000)
        InstrumentationRegistry.getInstrumentation().runOnMainSync { focus.release() }
        return Outcome(label, BriefingFocus.requestName(result), changes.toList(), events.toList())
    }

    @Test fun competingFocusRequestsOnCarAudioService() {
        val outcomes = listOf(
            scenario("내비 안내", AudioAttributes.USAGE_ASSISTANCE_NAVIGATION_GUIDANCE, AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK),
            scenario("통화", AudioAttributes.USAGE_VOICE_COMMUNICATION, AudioManager.AUDIOFOCUS_GAIN_TRANSIENT),
            scenario("음성비서", AudioAttributes.USAGE_ASSISTANT, AudioManager.AUDIOFOCUS_GAIN_TRANSIENT),
            scenario("알림음", AudioAttributes.USAGE_NOTIFICATION, AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK),
            scenario("안전 알림", 1003 /* USAGE_SAFETY, 시스템 전용 */, AudioManager.AUDIOFOCUS_GAIN_TRANSIENT),
            scenario("긴급 알림", 1002 /* USAGE_EMERGENCY, 시스템 전용 */, AudioManager.AUDIOFOCUS_GAIN_TRANSIENT),
            scenario("다른 미디어 앱", AudioAttributes.USAGE_MEDIA, AudioManager.AUDIOFOCUS_GAIN),
        )
        outcomes.forEach { Log.i("AudioFocusMatrix", "${it.label} | 경쟁 요청 ${it.competitor} | 받은 콜백 ${it.briefing} | 처리 ${it.events}") }
        val byLabel = outcomes.associateBy { it.label }
        for (label in listOf("내비 안내", "통화", "음성비서")) {
            assertEquals("$label: ${byLabel[label]}", listOf("pause", "resume"), byLabel[label]!!.events)
        }
        assertEquals(listOf("stop"), byLabel["다른 미디어 앱"]!!.events)
    }
}
