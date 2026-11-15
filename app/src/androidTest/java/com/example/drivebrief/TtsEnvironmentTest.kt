package com.example.drivebrief

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.util.Log
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import java.util.Locale
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/** 실제 엔진 검증. onDone은 엔진 완료 증거이며 사람이 들었다는 증거는 아니다. */
class TtsEnvironmentTest {
    @Test fun koreanGreetingWithPleosOnDevice() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val init = CountDownLatch(1)
        val done = CountDownLatch(1)
        var failure: String? = null
        lateinit var tts: ai.pleos.playground.tts.TextToSpeech
        val listener = object : ai.pleos.playground.tts.listener.EventListener {
            override fun onReady() { Log.i("DriveBriefTTS", "pleos onReady") }
            override fun onStart() { Log.i("DriveBriefTTS", "pleos onStart") }
            override fun onDone() { Log.i("DriveBriefTTS", "pleos onDone"); done.countDown() }
            override fun onStop() { Log.i("DriveBriefTTS", "pleos onStop") }
            override fun onUpdatedRms(rms: Double) = Unit
            override fun onError(errorType: ai.pleos.playground.tts.constant.ErrorType) {
                failure = errorType.toString()
                Log.e("DriveBriefTTS", "pleos onError=$errorType")
                done.countDown()
            }
        }
        instrumentation.runOnMainSync {
            tts = ai.pleos.playground.tts.TextToSpeech(instrumentation.targetContext,
                ai.pleos.playground.tts.constant.Mode.ON_DEVICE)
            tts.initialize(object : ai.pleos.playground.tts.listener.OnInitializeListener {
                override fun onSuccess() { Log.i("DriveBriefTTS", "pleos init success"); init.countDown() }
                override fun onFailure(errorType: ai.pleos.playground.tts.constant.ErrorType) {
                    failure = errorType.toString()
                    Log.e("DriveBriefTTS", "pleos init failure=$errorType")
                    init.countDown()
                }
            })
        }
        try {
            assertTrue("Pleos initialization timeout", init.await(20, TimeUnit.SECONDS))
            assertNull("Pleos initialization failure", failure)
            instrumentation.runOnMainSync {
                tts.addEventListener(listener)
                tts.setLocale(Locale.KOREA)
                Log.i("DriveBriefTTS", "pleos ko-KR speak request ON_DEVICE")
                tts.speak("안녕하세요. 차간신문 AI 브리핑을 시작합니다.")
            }
            assertTrue("Pleos playback completion timeout", done.await(30, TimeUnit.SECONDS))
            assertNull("Pleos playback failure", failure)
        } finally {
            instrumentation.runOnMainSync {
                tts.stop()
                tts.removeEventListener(listener)
                tts.release()
                Log.i("DriveBriefTTS", "pleos release")
            }
        }
    }

    @Test fun koreanGreetingWithInstalledAndroidEngine() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val init = CountDownLatch(1)
        val status = AtomicInteger(-99)
        lateinit var tts: TextToSpeech
        instrumentation.runOnMainSync {
            tts = TextToSpeech(context) { result ->
                status.set(result)
                Log.i("DriveBriefTTS", "probe init=$result")
                init.countDown()
            }
        }
        val audio = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        val attributes = AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA)
            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build()
        val focus = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
            .setAudioAttributes(attributes).setOnAudioFocusChangeListener { }.build()
        try {
            assertTrue("TTS init timed out", init.await(20, TimeUnit.SECONDS))
            Log.i("DriveBriefTTS", "probe engines=${tts.engines.map { it.name }} default=${tts.defaultEngine}")
            org.junit.Assume.assumeTrue("Android TTS unavailable: init=${status.get()} (see DriveBriefTTS logs)", status.get() == TextToSpeech.SUCCESS)
            val language = tts.isLanguageAvailable(Locale.KOREA)
            val set = tts.setLanguage(Locale.KOREA)
            Log.i("DriveBriefTTS", "probe ko-KR available=$language setLanguage=$set voices=${tts.voices}")
            assertTrue("ko-KR unavailable: $language/$set", language >= 0 && set >= 0)
            tts.setAudioAttributes(attributes)
            val done = CountDownLatch(1)
            val error = AtomicInteger(0)
            tts.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                override fun onStart(id: String?) { Log.i("DriveBriefTTS", "probe onStart id=$id") }
                override fun onDone(id: String?) { Log.i("DriveBriefTTS", "probe onDone id=$id"); done.countDown() }
                @Deprecated("Legacy callback")
                override fun onError(id: String?) { error.set(-1); done.countDown() }
                override fun onError(id: String?, code: Int) {
                    error.set(code); Log.e("DriveBriefTTS", "probe onError=$code"); done.countDown()
                }
            })
            assertEquals(AudioManager.AUDIOFOCUS_REQUEST_GRANTED, audio.requestAudioFocus(focus))
            val request = tts.speak("안녕하세요. 차간신문 AI 브리핑을 시작합니다.",
                TextToSpeech.QUEUE_FLUSH, null, "drivebrief-greeting")
            Log.i("DriveBriefTTS", "probe speak result=$request")
            assertEquals(TextToSpeech.SUCCESS, request)
            assertTrue("No completion callback", done.await(30, TimeUnit.SECONDS))
            assertEquals("Synthesis/playback error", 0, error.get())
        } finally {
            tts.stop()
            tts.shutdown()
            audio.abandonAudioFocusRequest(focus)
            Log.i("DriveBriefTTS", "probe shutdown")
        }
    }
}
