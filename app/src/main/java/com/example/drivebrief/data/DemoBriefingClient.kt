package com.example.drivebrief.data

import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject

data class DemoNews(
    val articleId: String, val title: String, val source: String,
    val ttsSentences: List<String>, val oneLine: String, val detail: String, val mock: Boolean? = null,
    val sourceUrl: String? = null, val categories: List<String> = emptyList(),
    val approvedSentenceCount: Int = ttsSentences.size,
    val contentKind: String = "fictional"
) { val availableSentenceCount: Int get() = approvedSentenceCount }

data class DemoBriefing(val articles: List<DemoNews>, val rawJson: String,
    val briefingId: String? = null, val lengthOption: String? = null,
    val targetSeconds: Double? = null, val estimatedSeconds: Double? = null,
    val optionSemantics: String? = null, val generatedAt: String? = null, val latestSourceAt: String? = null)
class DemoApiException(message: String) : Exception(message)

fun interface DemoBriefingLoader {
    suspend fun load(): DemoBriefing
}

/** Local fictional demo only. Never stores keys or logs payload/error bodies. */
class DemoBriefingClient(
    private val baseUrl: String = "http://10.0.2.2:8000",
    private val approvedMode: Boolean = false,
    private val lengthOption: String? = null,
    private val categories: List<String> = emptyList()
) : DemoBriefingLoader {
    override suspend fun load(): DemoBriefing = withContext(Dispatchers.IO) {
        val query = lengthOption?.let {
            require(approvedMode && it in listOf("짧게", "중간", "길게"))
            require(categories.all { c -> c in listOf("경제", "사회", "정치", "IT", "스포츠") })
            "/v1/briefings/plan?length=" + URLEncoder.encode(it, "UTF-8") +
                categories.joinToString("") { c -> "&categories=" + URLEncoder.encode(c, "UTF-8") }
        }
        val path = query ?: if (approvedMode) "/v1/briefings/current" else "/v1/demo/briefing?allow_unreviewed_fictional=true"
        val url = URL(baseUrl.trimEnd('/') + path)
        if (url.protocol != "http" || url.host !in setOf("10.0.2.2", "127.0.0.1", "localhost")) {
            throw DemoApiException("로컬 개발 서버 주소만 사용할 수 있습니다.")
        }
        val connection = url.openConnection() as HttpURLConnection
        try {
            connection.connectTimeout = 5_000
            connection.readTimeout = 8_000
            connection.instanceFollowRedirects = false
            connection.requestMethod = "GET"
            connection.setRequestProperty("Accept", "application/json")
            if (approvedMode) {
                connection.setRequestProperty("X-DriveBrief-TTS-SDK", "3.3.1")
                connection.setRequestProperty("X-DriveBrief-TTS-Locale", "ko-KR")
            }
            when (connection.responseCode) {
                200 -> Unit
                403 -> throw DemoApiException("서버의 개발 데모 활성화 설정을 확인하세요.")
                503 -> throw DemoApiException("서버에 저장된 데모 결과 파일이 없습니다.")
                else -> throw DemoApiException("데모 서버 응답 오류입니다. 서버 데이터를 확인하세요.")
            }
            val bytes = connection.inputStream.use { it.readBytesLimited(256_000) }
            parse(bytes.toString(Charsets.UTF_8), approvedMode)
        } catch (e: DemoApiException) {
            throw e
        } catch (e: Exception) {
            throw DemoApiException("서버에 연결할 수 없습니다. Mac 데모 서버와 연결을 확인하세요.")
        } finally {
            connection.disconnect()
        }
    }

    private fun java.io.InputStream.readBytesLimited(limit: Int): ByteArray {
        val output = java.io.ByteArrayOutputStream()
        val buffer = ByteArray(4096)
        while (true) {
            val count = read(buffer)
            if (count < 0) break
            if (output.size() + count > limit) throw DemoApiException("데모 응답 크기가 너무 큽니다.")
            output.write(buffer, 0, count)
        }
        return output.toByteArray()
    }

    companion object {
        fun parse(raw: String, approvedMode: Boolean = false, allowPrivateRssPreview: Boolean = false): DemoBriefing {
            try {
                val root = JSONObject(raw)
                if (approvedMode && root.optString("schema_version") == "rss-briefing-v1")
                    return RssBriefingParser.parse(raw)
                val preview = root.optString("schema_version") == "private-rss-preview-v1"
                require(!preview || (com.example.drivebrief.BuildConfig.DEBUG && allowPrivateRssPreview && approvedMode))
                require(root.getString("schema_version") == if (preview) "private-rss-preview-v1" else if (approvedMode) "approved-briefing-v1" else "demo-briefing-v1")
                fun boolean(obj: JSONObject, name: String, value: Boolean) {
                    require(obj.get(name) is Boolean && obj.getBoolean(name) == value)
                }
                fun text(obj: JSONObject, name: String, max: Int): String {
                    val value = obj.get(name)
                    require(value is String && value.isNotBlank() && value.length <= max)
                    return value
                }
                if (!approvedMode) boolean(root, "demo_only", true)
                val rss = root.optString("content_kind") == "rss_metadata"
                require(!rss || approvedMode)
                boolean(root, "fictional_only", !rss)
                if (preview) {
                    require(rss)
                    boolean(root, "preview_only", true)
                    boolean(root, "publication_allowed", false)
                } else require(!root.optBoolean("preview_only", false))
                boolean(root, "playback_requires_user_action", true)
                val items = root.getJSONArray("articles")
                require(items.length() <= 10)
                val news = (0 until items.length()).map { index ->
                    val item = items.getJSONObject(index)
                    val validation = item.getJSONObject("validation")
                    val mustBeApproved = approvedMode && !preview
                    require(validation.getString("status") == if (mustBeApproved) "approved" else "needs_review")
                    boolean(validation, "approved", mustBeApproved)
                    boolean(validation, "review_required", !mustBeApproved)
                    if (rss) {
                        require(root.has("briefing_id") && item.getString("content_kind") == "rss_metadata")
                        boolean(item, "mock", false)
                        val source = URL(item.getString("source_url"))
                        require(source.protocol == "https" && source.host.isNotBlank() && source.userInfo == null)
                    }
                    if (approvedMode) require(item.get("mock") is Boolean)
                    val sentences = item.getJSONArray("tts_sentences")
                    require(sentences.length() in 1..8)
                    if (root.has("briefing_id")) {
                        val indices = item.getJSONArray("sentence_indices")
                        require(indices.length() == sentences.length())
                        for (i in 0 until indices.length()) require(indices.get(i) is Int && indices.getInt(i) == i)
                        require(item.get("approved_sentence_count") is Int)
                        boolean(item, "partial_tts", sentences.length() < item.getInt("approved_sentence_count"))
                    }
                    DemoNews(
                        text(item, "article_id", 100), text(item, "title", 300), text(item, "source", 300),
                        (0 until sentences.length()).map {
                            val sentence = sentences.get(it)
                            require(sentence is String && sentence.isNotBlank() && sentence.length <= 350)
                            sentence
                        },
                        text(item, "one_line", 250), text(item, "detail", 2500),
                        if (approvedMode) item.getBoolean("mock") else null,
                        item.optString("source_url").takeIf { it.isNotBlank() && it != "null" }?.also {
                            val u = URL(it); require(u.protocol in setOf("https", "http") && u.host.isNotBlank() && u.userInfo == null)
                        },
                        item.optJSONArray("categories")?.let { array -> (0 until array.length()).map { array.getString(it) } }.orEmpty(),
                        item.optInt("approved_sentence_count", sentences.length()).also { require(it in sentences.length()..8) },
                        if (rss) "rss_metadata" else "fictional"
                    )
                }
                require(news.map { it.articleId }.distinct().size == news.size)
                val planned = root.has("briefing_id")
                if (planned) {
                    require(approvedMode)
                    require(root.getString("policy_status") == "development_placeholder_not_team_policy")
                    require(root.getString("length_option") in listOf("짧게", "중간", "길게"))
                    require(root.getDouble("target_seconds").isFinite() && root.getDouble("target_seconds") > 0)
                    require(root.getDouble("estimated_seconds").isFinite() && root.getDouble("estimated_seconds") >= 0)
                    require(root.getDouble("estimated_seconds") <= root.getDouble("target_seconds") + 0.001)
                }
                return DemoBriefing(news, raw,
                    if (planned) text(root, "briefing_id", 100) else null,
                    if (planned) root.getString("length_option") else null,
                    if (planned) root.getDouble("target_seconds") else null,
                    if (planned) root.getDouble("estimated_seconds") else null)
            } catch (e: Exception) {
                throw DemoApiException("브리핑의 출처·승인 상태 또는 응답 형식이 올바르지 않습니다.")
            }
        }
    }
}
