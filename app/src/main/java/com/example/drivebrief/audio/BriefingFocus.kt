package com.example.drivebrief.audio

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.os.Handler
import android.os.Looper
import android.util.Log

/** 브리핑 재생에 쓰는 오디오 속성. 포커스 요청과 TTS 엔진에 같은 값을 넘긴다. */
val BRIEFING_AUDIO_ATTRIBUTES: AudioAttributes = AudioAttributes.Builder()
    .setUsage(AudioAttributes.USAGE_MEDIA)
    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build()

/** AudioManager 포커스 요청을 감싼다. 테스트에서는 가짜로 바꾼다. */
interface FocusPort {
    /** AudioManager.AUDIOFOCUS_REQUEST_GRANTED / DELAYED / FAILED 중 하나를 돌려준다. */
    fun request(onChange: (Int) -> Unit): Int
    fun abandon()
}

/**
 * Pleos TTS 엔진은 포커스를 직접 요청하지 않아서(에뮬레이터 CarAudioService 기록으로 확인) 앱이 브리핑 단위로 요청한다.
 * 내비(MAY_DUCK)도 동시 재생으로 볼륨만 줄이지 않고 손실을 알려 받도록 setWillPauseWhenDucked(true)를 건다.
 */
class AndroidFocusPort(context: Context) : FocusPort {
    private val audio = context.applicationContext.getSystemService(Context.AUDIO_SERVICE) as AudioManager
    private val main = Handler(Looper.getMainLooper())
    private var current: AudioFocusRequest? = null

    override fun request(onChange: (Int) -> Unit): Int {
        abandon()
        val request = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN)
            .setAudioAttributes(BRIEFING_AUDIO_ATTRIBUTES)
            .setWillPauseWhenDucked(true)
            .setAcceptsDelayedFocusGain(true)
            .setOnAudioFocusChangeListener(onChange, main)
            .build()
        current = request
        return audio.requestAudioFocus(request)
    }

    override fun abandon() {
        current?.let(audio::abandonAudioFocusRequest)
        current = null
    }
}

/**
 * 브리핑 재생의 오디오 포커스 상태. 화면은 [listener]로 일시정지·재개·정지 지시를 받는다.
 * - 일시적 손실(LOSS_TRANSIENT, LOSS_TRANSIENT_CAN_DUCK): 시스템 일시정지, GAIN에서 자동 재개
 * - 영구 손실(LOSS): 정지하고 포커스를 반납, 자동 재개하지 않음
 * - 재개 직후 짧게 다시 손실되면 다음 재개를 [flapDelayMs]만큼 미뤄 같은 문장을 반복해서 처음부터 읽지 않는다.
 */
class BriefingFocus(
    private val port: FocusPort,
    private val now: () -> Long = System::currentTimeMillis,
    private val schedule: (delayMs: Long, action: () -> Unit) -> (() -> Unit) = ::mainSchedule,
    private val log: (String) -> Unit = { Log.i(TAG, it) },
    private val flapWindowMs: Long = 1_000,
    private val flapDelayMs: Long = 2_000,
) {
    enum class State { IDLE, WAITING, HOLDING, SYSTEM_PAUSED }
    enum class Start { GRANTED, DELAYED, FAILED }

    interface Listener {
        fun onSystemPause(change: Int)
        fun onSystemResume()
        fun onPermanentLoss()
    }

    var listener: Listener? = null
    var state = State.IDLE
        private set
    private var lastResumeAt = Long.MIN_VALUE / 2
    private var flapping = false
    private var cancelResume: (() -> Unit)? = null

    /** 재생 직전에 부른다. 이미 포커스가 있으면 그대로 GRANTED. */
    fun start(): Start {
        if (state == State.HOLDING) return Start.GRANTED
        if (state == State.WAITING) return Start.DELAYED
        cancelPendingResume()
        val result = port.request(::onChange)
        log("request usage=MEDIA content=SPEECH gain=GAIN pauseWhenDucked=true delayed=true result=${requestName(result)}")
        return when (result) {
            AudioManager.AUDIOFOCUS_REQUEST_GRANTED -> { state = State.HOLDING; lastResumeAt = now(); Start.GRANTED }
            AudioManager.AUDIOFOCUS_REQUEST_DELAYED -> { state = State.WAITING; Start.DELAYED }
            else -> { port.abandon(); state = State.IDLE; Start.FAILED }
        }
    }

    /** 브리핑 종료, 사용자 일시정지·중단, 화면 정리 때 포커스를 반납한다. */
    fun release() {
        cancelPendingResume()
        if (state != State.IDLE) {
            port.abandon()
            log("abandon from=$state")
        }
        state = State.IDLE
        flapping = false
    }

    fun onChange(change: Int) {
        log("change=${name(change)} state=$state")
        when (change) {
            AudioManager.AUDIOFOCUS_GAIN -> when (state) {
                State.WAITING -> resume("delayed_gain")
                State.SYSTEM_PAUSED ->
                    if (flapping) {
                        cancelPendingResume()
                        log("action=resume_deferred delayMs=$flapDelayMs")
                        cancelResume = schedule(flapDelayMs) { cancelResume = null; if (state == State.SYSTEM_PAUSED) resume("gain_after_flap") }
                    } else resume("gain")
                else -> Unit
            }
            AudioManager.AUDIOFOCUS_LOSS_TRANSIENT, AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK -> when (state) {
                State.HOLDING -> {
                    flapping = now() - lastResumeAt < flapWindowMs
                    state = State.SYSTEM_PAUSED
                    log("action=system_pause flapping=$flapping")
                    listener?.onSystemPause(change)
                }
                State.SYSTEM_PAUSED -> cancelPendingResume()
                else -> Unit
            }
            AudioManager.AUDIOFOCUS_LOSS -> if (state != State.IDLE) {
                cancelPendingResume()
                port.abandon()
                state = State.IDLE
                flapping = false
                log("action=stop_permanent_loss")
                listener?.onPermanentLoss()
            }
        }
    }

    private fun resume(reason: String) {
        state = State.HOLDING
        lastResumeAt = now()
        log("action=resume reason=$reason")
        listener?.onSystemResume()
    }

    private fun cancelPendingResume() {
        cancelResume?.invoke()
        cancelResume = null
    }

    companion object {
        const val TAG = "DriveBriefFocus"

        fun requestName(value: Int): String = when (value) {
            AudioManager.AUDIOFOCUS_REQUEST_GRANTED -> "GRANTED"
            AudioManager.AUDIOFOCUS_REQUEST_DELAYED -> "DELAYED"
            else -> "FAILED"
        }

        fun name(value: Int): String = when (value) {
            AudioManager.AUDIOFOCUS_GAIN -> "GAIN"
            AudioManager.AUDIOFOCUS_LOSS -> "LOSS"
            AudioManager.AUDIOFOCUS_LOSS_TRANSIENT -> "LOSS_TRANSIENT"
            AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK -> "LOSS_TRANSIENT_CAN_DUCK"
            else -> value.toString()
        }

        private fun mainSchedule(delayMs: Long, action: () -> Unit): () -> Unit {
            val handler = Handler(Looper.getMainLooper())
            val runnable = Runnable(action)
            handler.postDelayed(runnable, delayMs)
            return { handler.removeCallbacks(runnable) }
        }
    }
}
