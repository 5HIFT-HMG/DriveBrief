package com.example.drivebrief.audio

import android.content.Context
import android.util.Log
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import org.json.JSONObject
import java.io.File

/** Local numeric metadata only; never records sentence text, keys or provider payloads. */
class SpeechTimingFile private constructor(context: Context) {
    private val directory = context.applicationContext.getExternalFilesDir(null)
    private val writes = Channel<SpeechTiming>(Channel.UNLIMITED)
    init {
        CoroutineScope(SupervisorJob() + Dispatchers.IO).launch {
            for (record in writes) {
                try {
                    check(directory != null)
                    val c = record.context; val f = record.features
                    val value = JSONObject().put("schema", "speech-timing-v1").put("engine", record.engine)
                        .put("sdk_version", "3.3.1").put("locale", "ko-KR")
                        .put("attempt_id", record.attemptId).put("session_id", c.sessionId)
                        .put("briefing_id", c.briefingId).put("article_id", c.articleId)
                        .put("sentence_index", c.sentenceIndex).put("length_option", c.lengthOption)
                        .put("session_sentence_count", c.sessionSentenceCount).put("text_sha256", record.textSha256)
                        .put("outcome", record.outcome).put("requested_epoch_ms", record.requestedEpochMs)
                        .put("requested_monotonic_ms", record.requestedMonotonicMs)
                        .put("startup_ms", record.startupMs ?: JSONObject.NULL)
                        .put("start_to_done_ms", record.startToDoneMs ?: JSONObject.NULL)
                        .put("request_to_done_ms", record.requestToDoneMs)
                        .put("features", JSONObject().put("characters", f.characters).put("hangul", f.hangul)
                            .put("spaces", f.spaces).put("digits", f.digits).put("punctuation", f.punctuation)
                            .put("latin", f.latin).put("other", f.other))
                    File(directory, "speech-timing-v1.jsonl").appendText(value.toString()+"\n", Charsets.UTF_8)
                } catch (_: Exception) {
                    Log.w("DriveBriefTiming", "Local timing write failed; no text or error body logged")
                }
            }
        }
    }
    fun append(record: SpeechTiming) { writes.trySend(record) }
    companion object {
        @Volatile private var shared: SpeechTimingFile? = null
        fun get(context: Context): SpeechTimingFile = shared ?: synchronized(this) {
            shared ?: SpeechTimingFile(context).also { shared = it }
        }
    }
}
