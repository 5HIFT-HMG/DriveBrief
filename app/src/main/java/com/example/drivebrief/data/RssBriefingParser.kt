package com.example.drivebrief.data

import org.json.JSONObject
import java.net.URL
import java.time.OffsetDateTime

/** Normal production-path RSS metadata. This is NOT a human-approved AI summary. */
object RssBriefingParser {
    fun parse(raw: String): DemoBriefing {
        try {
            val root = JSONObject(raw)
            fun text(obj: JSONObject, name: String, max: Int): String =
                (obj.get(name) as String).also { require(it.isNotBlank() && it.length <= max) }
            fun bool(obj: JSONObject, name: String, expected: Boolean) {
                require(obj.get(name) is Boolean && obj.getBoolean(name) == expected)
            }
            require(root.getString("schema_version") == "rss-briefing-v1")
            require(root.getString("content_kind") == "rss_metadata")
            require(root.getString("processing") == "automatic_metadata_extraction")
            require(root.getString("option_semantics") == "article_detail")
            require(root.getString("usage_rights_status") == "source_terms_not_verified")
            require(!root.has("target_seconds") && !root.has("approved") && !root.optBoolean("preview_only"))
            bool(root, "playback_requires_user_action", true)
            val option = root.getString("length_option")
            val limit = mapOf("짧게" to 1, "중간" to 3, "길게" to 5)[option] ?: error("option")
            require(root.get("sentence_limit") is Int && root.getInt("sentence_limit") == limit)
            val generated = text(root, "generated_at", 60)
            val latest = text(root, "latest_source_at", 60)
            OffsetDateTime.parse(generated); OffsetDateTime.parse(latest)
            text(root, "catalog_id", 100); text(root, "input_revision", 100)
            val array = root.getJSONArray("articles")
            require(array.length() <= 25)
            val articles = (0 until array.length()).map { i ->
                val item = array.getJSONObject(i)
                val validation = item.getJSONObject("validation")
                require(validation.getString("status") == "rss_auto_validated")
                require(validation.getString("method") == "metadata_exact_extract_v1")
                require(!validation.has("approved") && !validation.has("review_required"))
                bool(validation, "human_reviewed", false)
                require(item.getString("content_kind") == "rss_metadata")
                require(!item.has("approved_sentence_count") && !item.has("mock"))
                OffsetDateTime.parse(text(item, "published_at", 60))
                val url = text(item, "source_url", 2000)
                URL(url).also { require(it.protocol in setOf("http", "https") && it.host.isNotBlank() && it.userInfo == null) }
                val sentences = item.getJSONArray("tts_sentences")
                require(item.get("available_sentence_count") is Int)
                val available = item.getInt("available_sentence_count")
                require(available in 1..5 && sentences.length() == minOf(limit, available))
                val indices = item.getJSONArray("sentence_indices")
                require(indices.length() == sentences.length())
                val spoken = (0 until sentences.length()).map { j ->
                    require(indices.get(j) is Int && indices.getInt(j) == j)
                    (sentences.get(j) as String).also { require(it.isNotBlank() && it.length <= 350 && !it.contains('\n')) }
                }
                bool(item, "partial_tts", spoken.size < available)
                val categories = item.getJSONArray("categories").let { a -> (0 until a.length()).map { a.getString(it) } }
                require(categories.isNotEmpty() && categories.all { it in setOf("경제", "사회", "정치", "IT", "스포츠") })
                DemoNews(text(item, "article_id", 100), text(item, "title", 250), text(item, "source", 300),
                    spoken, text(item, "one_line", 250), text(item, "detail", 2500),
                    null, url, categories, available, "rss_metadata")
            }
            require(articles.map { it.articleId }.distinct().size == articles.size)
            return DemoBriefing(articles, raw, text(root, "briefing_id", 100), option,
                optionSemantics = "article_detail", generatedAt = generated, latestSourceAt = latest)
        } catch (_: Exception) {
            throw DemoApiException("RSS 자동 브리핑의 데이터 형식이 올바르지 않습니다.")
        }
    }
}
