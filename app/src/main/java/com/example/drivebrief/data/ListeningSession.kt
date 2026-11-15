package com.example.drivebrief.data

enum class ListeningStatus(val label: String) {
    UNHEARD("미청취"), PLAYING("재생 중"), COMPLETED("청취 완료"),
    SKIPPED("건너뜀"), INTERRUPTED("중단")
}

data class ArticleListening(
    val status: ListeningStatus = ListeningStatus.UNHEARD,
    val completed: Set<Int> = emptySet(),
    val skipped: Set<Int> = emptySet(),
    val started: Set<Int> = emptySet(),
    val cursor: Int = 0,
    val interruptedAt: Long? = null,
    val interruptionReason: String? = null
)

data class ListeningSession(
    val sessionId: String,
    val briefingId: String,
    val briefing: DemoBriefing,
    val createdAt: Long,
    val progress: List<ArticleListening> = briefing.articles.map { ArticleListening() },
    val ended: Boolean = false
) {
    val fullyCompleted: Boolean get() = ended && progress.isNotEmpty() &&
        progress.all { it.status == ListeningStatus.COMPLETED }

    /** Immutable reducer. Completion is accepted only after onStarted, once per sentence. */
    fun event(article: Int, sentence: Int, kind: String, now: Long): ListeningSession {
        if (kind == "end") return if (ended) this else copy(ended = true)
        if (ended) return this
        val item = briefing.articles.getOrNull(article) ?: return this
        if (sentence !in item.ttsSentences.indices) return this
        val old = progress[article]
        val next = when (kind) {
            "start" -> if (old.status == ListeningStatus.COMPLETED) old else
                old.copy(status = ListeningStatus.PLAYING, started = old.started + sentence, cursor = sentence)
            "done" -> {
                if (sentence !in old.started || sentence in old.completed || sentence in old.skipped) old
                else {
                    val done = old.completed + sentence
                    old.copy(completed = done, cursor = sentence,
                        status = if (done.size == item.ttsSentences.size) ListeningStatus.COMPLETED
                            else if (old.skipped.isNotEmpty()) ListeningStatus.SKIPPED else ListeningStatus.PLAYING)
                }
            }
            "skip_sentence" -> if (sentence in old.completed) old else
                old.copy(status = ListeningStatus.SKIPPED, skipped = old.skipped + sentence, cursor = sentence)
            "skip_article" -> if (old.status == ListeningStatus.COMPLETED) old else
                old.copy(status = ListeningStatus.SKIPPED,
                    skipped = old.skipped + item.ttsSentences.indices.filter { it !in old.completed }, cursor = sentence)
            else -> if (kind.startsWith("interrupt:") && old.status != ListeningStatus.COMPLETED) {
                if (old.interruptionReason == kind && old.cursor == sentence && old.status != ListeningStatus.PLAYING) old
                else old.copy(status = if (old.skipped.isNotEmpty()) ListeningStatus.SKIPPED
                        else if (old.started.isEmpty()) ListeningStatus.UNHEARD else ListeningStatus.INTERRUPTED,
                    cursor = sentence, interruptedAt = now, interruptionReason = kind)
            } else old
        }
        return if (next == old) this else copy(progress = progress.mapIndexed { i, state -> if (i == article) next else state })
    }

    fun restored(): ListeningSession = copy(progress = progress.map {
        if (it.status == ListeningStatus.PLAYING) it.copy(status = ListeningStatus.INTERRUPTED,
            interruptionReason = "interrupt:process_restore") else it
    })
}
