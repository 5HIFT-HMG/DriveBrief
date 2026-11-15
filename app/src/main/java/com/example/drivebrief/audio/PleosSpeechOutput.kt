package com.example.drivebrief.audio

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.util.Log
import ai.pleos.playground.tts.TextToSpeech
import ai.pleos.playground.tts.constant.ErrorType
import ai.pleos.playground.tts.constant.Mode
import ai.pleos.playground.tts.listener.EventListener
import ai.pleos.playground.tts.listener.OnInitializeListener
import java.util.Locale

/**
 * ON_DEVICE 전용: 서버 등록/자격증명 없이 동작한다.
 * SDK 콜백에 utterance id가 없어 요청별 세션과 세대 번호로 늦은 완료 콜백을 차단한다.
 * 모든 호출/이벤트는 main looper에서 처리한다.
 * 오디오 포커스는 문장마다가 아니라 브리핑 단위로 [BriefingFocus]가 요청한다(엔진은 포커스를 요청하지 않음).
 */
class PleosSpeechOutput(context: Context) : SpeechOutput {
    private val context = context.applicationContext
    private val main = Handler(Looper.getMainLooper())
    private var generation = 0L
    private var engine: TextToSpeech? = null
    private var events: EventListener? = null
    private var timeout: Runnable? = null
    private var closed = false
    private var requestFinished = false
    private var interruptedUntil = 0L

    override fun speak(text: String, onStarted: () -> Unit, onDone: () -> Unit, onFailure: (String) -> Unit) {
        check(Looper.myLooper() == Looper.getMainLooper())
        if (closed) { onFailure("TTS 세션이 종료되었습니다."); return }
        stop()
        val ticket = generation
        // SDK stop/release completes asynchronously and has no utterance identifier.
        // Coalesce rapid user controls before opening the next session; cancelled requests never start.
        val settling = interruptedUntil - android.os.SystemClock.elapsedRealtime()
        if (settling > 0) {
            main.postDelayed({ if (ticket == generation && !closed) speak(text, onStarted, onDone, onFailure) }, settling)
            return
        }
        fun fail(message: String) {
            if (ticket != generation) return
            Log.e("DriveBriefTTS", message)
            stop()
            onFailure(message)
        }
        try {
            val client = TextToSpeech(context, Mode.ON_DEVICE)
            engine = client
            var playbackStarted = false
            val listener = object : EventListener {
                override fun onReady() = Unit
                override fun onUpdatedRms(rms: Double) = Unit
                override fun onStart() { main.post {
                    if (ticket == generation) {
                        playbackStarted = true
                        timeout?.let(main::removeCallbacks)
                        timeout = Runnable { fail("TTS 문장 완료 응답 시간이 초과되었습니다.") }
                            .also { main.postDelayed(it, 120_000) }
                        Log.i("DriveBriefTTS", "onStart generation=$ticket")
                        onStarted()
                    }
                } }
                override fun onDone() { main.post {
                    if (ticket == generation && playbackStarted) {
                        Log.i("DriveBriefTTS", "onDone generation=$ticket")
                        requestFinished = true
                        stop()
                        onDone()
                    }
                } }
                override fun onStop() { main.post {
                    if (ticket == generation) fail("음성 재생이 중단되었습니다.")
                } }
                override fun onError(errorType: ErrorType) { main.post {
                    fail("TTS 오류: $errorType")
                } }
            }
            events = listener
            timeout = Runnable { fail("TTS 초기화 또는 시작 응답 시간이 초과되었습니다.") }
                .also { main.postDelayed(it, 20_000) }
            client.initialize(object : OnInitializeListener {
                override fun onFailure(errorType: ErrorType) { main.post {
                    fail("TTS 초기화 실패: $errorType")
                } }
                override fun onSuccess() { main.post {
                    if (ticket != generation) return@post
                    try {
                        client.addEventListener(listener)
                        client.setLocale(Locale.KOREA)
                        client.setAudioAttributes(BRIEFING_AUDIO_ATTRIBUTES)
                        Log.i("DriveBriefTTS", "initialized ON_DEVICE; ko-KR speak request generation=$ticket")
                        client.speak(text)
                    } catch (e: Exception) { fail("TTS 요청 실패: ${e.javaClass.simpleName}") }
                } }
            })
        } catch (e: Exception) { fail("TTS 연결 실패: ${e.javaClass.simpleName}") }
    }

    override fun stop() {
        generation++
        timeout?.let(main::removeCallbacks)
        timeout = null
        val oldEngine = engine
        val oldEvents = events
        val wasFinished = requestFinished
        requestFinished = false
        engine = null
        events = null
        try {
            if (oldEngine != null) {
                if (!wasFinished) interruptedUntil = android.os.SystemClock.elapsedRealtime() + 300L
                try { oldEvents?.let(oldEngine::removeEventListener) } finally {
                    // onDone 뒤 stop을 보내면 서비스의 지연 stop이 다음 문장을 취소할 수 있다.
                    try { if (!wasFinished) oldEngine.stop() } finally { oldEngine.release() }
                }
                Log.i("DriveBriefTTS", "stop/release")
            }
        } catch (e: Exception) {
            Log.w("DriveBriefTTS", "cleanup: ${e.javaClass.simpleName}")
        }
    }

    override fun close() {
        stop()
        closed = true
    }
}
