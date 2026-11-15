package com.example.drivebrief.data

import android.content.Context
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.collectLatest
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest
import java.util.UUID

data class HistorySnapshot(val ready: Boolean = false,
    val sessions: List<ListeningSession> = emptyList(), val error: String? = null,
    val cloudStatus: String? = null)

/** App-private, bounded session snapshots. All disk IO is serialized on IO dispatcher. */
class SessionHistory(context: Context, private val storageName: String = "briefing_history_v1",
    private val privateRssPreview: Boolean = false) {
    init { require(!privateRssPreview || (com.example.drivebrief.BuildConfig.DEBUG && storageName == "private_rss_preview_history_v1")) }
    private var cloudJob: Job? = null
    private var cloud: HistoryCloudBridge? = null
    private var revision = 0L
    private val cloudChanges = kotlinx.coroutines.flow.MutableStateFlow<Pair<Long, String>?>(null)
    private val appContext = context.applicationContext
    private val mutable = MutableStateFlow(HistorySnapshot())
    val state: StateFlow<HistorySnapshot> = mutable
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private data class Save(val sessions: List<ListeningSession>?, val ack: CompletableDeferred<Unit>? = null, val revision: Long = 0)
    private val writes = Channel<Save>(Channel.UNLIMITED)

    init {
        scope.launch {
            val prefs = appContext.getSharedPreferences(storageName, Context.MODE_PRIVATE)
            try {
                val raw = prefs.getString("sessions", null)
                val restored = if (raw == null) emptyList() else decode(raw, privateRssPreview).map { it.restored() }
                revision = prefs.getLong("revision", 0)
                mutable.value = HistorySnapshot(true, restored)
            } catch (_: Exception) {
                mutable.value = HistorySnapshot(true, error = "저장된 청취 기록을 읽지 못했습니다. 원본을 보존했습니다.")
            }
            for (save in writes) {
                try {
                    save.sessions?.let {
                        val raw = encode(it)
                        val currentRevision = save.revision
                        check(prefs.edit().putString("sessions", raw).putLong("revision", currentRevision).commit())
                        cloudChanges.value = currentRevision to raw
                    }
                } catch (_: Exception) {
                    synchronized(this@SessionHistory) {
                        mutable.value = mutable.value.copy(error = "청취 기록 저장에 실패했습니다. 재시작 후 최근 기록이 없을 수 있습니다.")
                    }
                } finally { save.ack?.complete(Unit) }
            }
        }
    }

    @Synchronized fun start(briefing: DemoBriefing): String {
        check(mutable.value.ready && mutable.value.error == null)
        require(briefing.articles.isNotEmpty())
        val id = UUID.randomUUID().toString()
        val digest = MessageDigest.getInstance("SHA-256").digest(briefing.rawJson.toByteArray())
            .joinToString("") { "%02x".format(it) }
        val session = ListeningSession(id, briefing.briefingId ?: "legacy_$digest", briefing, System.currentTimeMillis())
        publish(listOf(session) + mutable.value.sessions.take(19))
        return id
    }

    @Synchronized fun event(id: String?, article: Int, sentence: Int, kind: String) {
        if (id == null || !mutable.value.ready) return
        val sessions = mutable.value.sessions
        val updated = sessions.map { if (it.sessionId == id) it.event(article, sentence, kind, System.currentTimeMillis()) else it }
        if (updated != sessions) publish(updated)
    }

    private fun publish(sessions: List<ListeningSession>) {
        revision = maxOf(revision + 1, System.currentTimeMillis())
        mutable.value = mutable.value.copy(sessions = sessions)
        writes.trySend(Save(sessions, revision = revision))
    }

    suspend fun awaitReady() { state.first { it.ready } }
    suspend fun flush() {
        awaitReady()
        val ack = CompletableDeferred<Unit>()
        writes.send(Save(null, ack))
        ack.await()
    }

    @Synchronized fun connectCloud(bridge: HistoryCloudBridge?) {
        require(!privateRssPreview || bridge == null) { "Private previews cannot sync or share" }
        cloudJob?.cancel()
        cloud = bridge
        if (bridge == null) return
        cloudJob = scope.launch {
            awaitReady()
            val initialRevision = synchronized(this@SessionHistory) { revision }
            try {
                val remote = bridge.restore()
                synchronized(this@SessionHistory) {
                    if (remote != null && remote.first > revision && revision == initialRevision) {
                        val restored = decode(remote.second).map { it.restored() }
                        val remoteIds = restored.map { it.sessionId }.toSet()
                        val merged = (restored + mutable.value.sessions.filter { it.sessionId !in remoteIds })
                            .sortedByDescending { it.createdAt }.take(20)
                        revision = remote.first
                        publish(merged)
                    } else if (remote != null) revision = maxOf(revision, remote.first)
                }
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) { mutable.value = mutable.value.copy(cloudStatus = "DB 연결 대기 · 로컬 기록 유지") }
            if (mutable.value.sessions.isNotEmpty()) {
                synchronized(this@SessionHistory) { publish(mutable.value.sessions) }
            }
            cloudChanges.collectLatest { pending ->
                if (pending == null) return@collectLatest
                delay(2000)
                while (true) {
                    try {
                        val accepted = bridge.save(pending.first, pending.second)
                        require(accepted == pending.first)
                        mutable.value = mutable.value.copy(cloudStatus = CLOUD_SYNCED)
                        break
                    } catch (e: CancellationException) { throw e }
                    catch (_: Exception) {
                        mutable.value = mutable.value.copy(cloudStatus = "DB 전송 대기 · 로컬 기록 유지")
                        delay(30_000)
                    }
                }
            }
        }
    }

    private val shares = mutableMapOf<String, OnePaperShare>()

    /** 최신 기록을 먼저 올린 뒤 서버가 그 세션을 복사해 공유 토큰을 만든다. 유효한 토큰은 메모리에서 재사용한다. */
    suspend fun share(sessionId: String): OnePaperShare {
        synchronized(shares) { shares[sessionId] }?.takeIf { it.expiresAt > System.currentTimeMillis() + 600_000 }?.let { return it }
        val bridge = synchronized(this) { cloud } ?: throw NewsListException("서버에 연결하는 중입니다. 인터넷 연결을 확인하고 잠시 후 다시 시도하세요.")
        flush()
        cloudChanges.value?.let { (pendingRevision, document) -> bridge.save(pendingRevision, document) }
        return bridge.share(sessionId).also { synchronized(shares) { shares[sessionId] = it } }
    }

    fun close() { cloudJob?.cancel(); writes.close() } // Tests only; app singleton lives for the process lifetime.

    companion object {
        @Volatile private var privatePreview: SessionHistory? = null
        fun getPrivatePreview(context: Context): SessionHistory = privatePreview ?: synchronized(this) {
            privatePreview ?: SessionHistory(context, "private_rss_preview_history_v1", true).also { privatePreview = it }
        }

        private val accounts = mutableMapOf<String, SessionHistory>()
        fun get(context: Context, userId: String): SessionHistory = synchronized(accounts) {
            accounts.getOrPut(userId) {
                val suffix = MessageDigest.getInstance("SHA-256").digest(userId.toByteArray())
                    .joinToString("") { "%02x".format(it) }
                SessionHistory(context, "briefing_history_user_$suffix")
            }
        }

        @Volatile private var shared: SessionHistory? = null
        fun get(context: Context): SessionHistory = shared ?: synchronized(this) {
            shared ?: SessionHistory(context).also { shared = it }
        }

        private fun encode(sessions: List<ListeningSession>): String {
            val items = JSONArray()
            sessions.forEach { session ->
                val states = JSONArray()
                session.progress.forEach { p ->
                    states.put(JSONObject().put("status", p.status.name)
                        .put("completed", JSONArray(p.completed.sorted()))
                        .put("skipped", JSONArray(p.skipped.sorted())).put("started", JSONArray(p.started.sorted()))
                        .put("cursor", p.cursor).put("interrupted_at", p.interruptedAt ?: JSONObject.NULL)
                        .put("reason", p.interruptionReason ?: JSONObject.NULL))
                }
                items.put(JSONObject().put("session_id", session.sessionId).put("briefing_id", session.briefingId)
                    .put("payload", session.briefing.rawJson).put("created_at", session.createdAt)
                    .put("ended", session.ended).put("progress", states))
            }
            val document = JSONObject().put("schema", 1).put("sessions", items)
            // Keep the newest complete sessions within the existing cloud payload budget.
            while (items.length() > 1 && document.toString().toByteArray(Charsets.UTF_8).size > 440_000)
                items.remove(items.length() - 1)
            return document.toString().also { require(it.toByteArray(Charsets.UTF_8).size <= 450_000) }
        }

        private fun decode(raw: String, privateRssPreview: Boolean = false): List<ListeningSession> {
            val root = JSONObject(raw)
            require(root.getInt("schema") == 1)
            val items = root.getJSONArray("sessions")
            require(items.length() <= 20)
            val ids = mutableSetOf<String>()
            return (0 until items.length()).map { i ->
                val item = items.getJSONObject(i)
                val id = item.getString("session_id")
                require(ids.add(id))
                val briefing = DemoBriefingClient.parse(item.getString("payload"), true, privateRssPreview)
                val states = item.getJSONArray("progress")
                require(states.length() == briefing.articles.size)
                val progress = briefing.articles.indices.map { j ->
                    val p = states.getJSONObject(j)
                    fun indices(key: String): Set<Int> {
                        val arr = p.getJSONArray(key)
                        val values = (0 until arr.length()).map { arr.getInt(it) }.toSet()
                        require(values.all { it in briefing.articles[j].ttsSentences.indices })
                        return values
                    }
                    val done = indices("completed"); val skipped = indices("skipped"); val started = indices("started")
                    require(done.all { it in started } && done.intersect(skipped).isEmpty())
                    val status = ListeningStatus.valueOf(p.getString("status"))
                    require(status != ListeningStatus.COMPLETED || done.size == briefing.articles[j].ttsSentences.size)
                    ArticleListening(status, done, skipped, started, p.getInt("cursor"),
                        if (p.isNull("interrupted_at")) null else p.getLong("interrupted_at"),
                        if (p.isNull("reason")) null else p.getString("reason"))
                }
                ListeningSession(id, item.getString("briefing_id"), briefing, item.getLong("created_at"),
                    progress, item.getBoolean("ended"))
            }
        }
    }
}

const val CLOUD_SYNCED = "DB 동기화 완료"
