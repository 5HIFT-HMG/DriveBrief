package com.example.drivebrief.audio

import java.security.MessageDigest
import java.util.UUID

data class TimingContext(val sessionId: String, val briefingId: String, val articleId: String,
    val sentenceIndex: Int, val lengthOption: String, val sessionSentenceCount: Int)
data class TextFeatures(val characters: Int, val hangul: Int, val spaces: Int,
    val digits: Int, val punctuation: Int, val latin: Int, val other: Int)
data class SpeechTiming(val attemptId: String, val engine: String, val context: TimingContext,
    val textSha256: String, val features: TextFeatures, val outcome: String,
    val requestedEpochMs: Long, val requestedMonotonicMs: Long, val startupMs: Long?,
    val startToDoneMs: Long?, val requestToDoneMs: Long)

/** Observer/decorator only: delegates to the existing Pleos engine, never queues or auto-replays. */
class MeasuredSpeechOutput(
    private val delegate: SpeechOutput,
    private val sink: (SpeechTiming) -> Unit,
    private val engine: String,
    private val monotonic: () -> Long = { System.nanoTime() / 1_000_000 },
    private val epoch: () -> Long = { System.currentTimeMillis() }
) : SpeechOutput {
    var context: TimingContext? = null
    private data class Pending(val context: TimingContext, val hash: String, val features: TextFeatures,
        val attempt: String, val epoch: Long, val requested: Long, var started: Long? = null)
    private var pending: Pending? = null
    private var generation = 0L

    override fun speak(text: String, onStarted: () -> Unit, onDone: () -> Unit, onFailure: (String) -> Unit) {
        stop()
        val ticket = generation
        val current = context
        if (current != null) pending = Pending(current, sha256(text), features(text), UUID.randomUUID().toString(), epoch(), monotonic())
        try {
            delegate.speak(text,
                onStarted = {
                    if (ticket == generation) {
                        if (pending?.started == null) pending?.started = monotonic()
                        onStarted()
                    }
                },
                onDone = {
                    if (ticket == generation) {
                        finish("completed")
                        generation++
                        onDone()
                    }
                },
                onFailure = {
                    if (ticket == generation) {
                        finish("error")
                        generation++
                        onFailure(it)
                    }
                })
        } catch (_: Exception) {
            if (ticket == generation) {
                finish("error"); generation++
                onFailure("음성 재생 요청에 실패했습니다.")
            }
        }
    }

    private fun finish(outcome: String) {
        val old = pending ?: return
        pending = null
        val now = monotonic()
        val effectiveOutcome = if (outcome == "completed" && old.started == null) "missing_start" else outcome
        runCatching {
            sink(SpeechTiming(old.attempt, engine, old.context, old.hash, old.features, effectiveOutcome,
                old.epoch, old.requested, old.started?.minus(old.requested),
                old.started?.let { now-it }, now-old.requested))
        } // Timing collection must never break playback.
    }
    override fun stop() {
        generation++
        finish("stopped")
        delegate.stop()
    }
    override fun close() { stop(); delegate.close() }

    companion object {
        fun sha256(text: String) = MessageDigest.getInstance("SHA-256").digest(text.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }
        fun features(text: String): TextFeatures {
            val cps = text.codePoints().toArray()
            var ko = 0; var space = 0; var digit = 0; var punctuation = 0; var latin = 0; var other = 0
            val types = setOf(Character.CONNECTOR_PUNCTUATION.toInt(), Character.DASH_PUNCTUATION.toInt(),
                Character.START_PUNCTUATION.toInt(), Character.END_PUNCTUATION.toInt(),
                Character.INITIAL_QUOTE_PUNCTUATION.toInt(), Character.FINAL_QUOTE_PUNCTUATION.toInt(),
                Character.OTHER_PUNCTUATION.toInt())
            cps.forEach {
                when {
                    it in 0xAC00..0xD7A3 -> ko++
                    Character.isWhitespace(it) -> space++
                    Character.isDigit(it) -> digit++
                    Character.getType(it) in types -> punctuation++
                    it in 65..90 || it in 97..122 -> latin++
                    else -> other++
                }
            }
            return TextFeatures(cps.size, ko, space, digit, punctuation, latin, other)
        }
    }
}
