package com.example.drivebrief.data

import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.time.OffsetDateTime
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject

data class CollectedNews(
    val articleId: String, val title: String, val category: String,
    val source: String, val publishedAt: String, val description: String, val sourceUrl: String
)
data class CollectedNewsPage(
    val articles: List<CollectedNews>, val total: Int, val available: Int,
    val offset: Int, val hasMore: Boolean
)
class NewsListException(message: String) : Exception(message)
fun interface NewsListLoader {
    suspend fun load(categories: List<String>?, offset: Int): CollectedNewsPage
}

/** Discovery metadata only: no summary/TTS API, no credentials, local debug host only. */
class NewsListClient(private val baseUrl: String = "http://10.0.2.2:8000") : NewsListLoader {
    override suspend fun load(categories: List<String>?, offset: Int): CollectedNewsPage = withContext(Dispatchers.IO) {
        val filters = categories.orEmpty().joinToString("") {
            "&categories=" + URLEncoder.encode(it, "UTF-8")
        }
        val url = URL(baseUrl.trimEnd('/') + "/v1/news?limit=20&offset=$offset" + filters)
        if (url.protocol != "http" || url.host !in setOf("10.0.2.2", "127.0.0.1", "localhost")) {
            throw NewsListException("로컬 개발 서버 주소만 사용할 수 있습니다.")
        }
        val connection = url.openConnection() as HttpURLConnection
        try {
            connection.connectTimeout = 5000
            connection.readTimeout = 8000
            connection.instanceFollowRedirects = false
            connection.setRequestProperty("Accept", "application/json")
            if (connection.responseCode != 200) throw NewsListException("뉴스 조회 오류입니다. 서버와 DB 설정을 확인하세요.")
            val raw = connection.inputStream.use { input ->
                val output = java.io.ByteArrayOutputStream()
                val buffer = ByteArray(4096)
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    if (output.size() + count > 1_000_000) throw NewsListException("뉴스 응답이 너무 큽니다.")
                    output.write(buffer, 0, count)
                }
                output.toString("UTF-8")
            }
            parse(raw)
        } catch (e: NewsListException) { throw e }
        catch (e: Exception) { throw NewsListException("뉴스 서버에 연결할 수 없습니다.") }
        finally { connection.disconnect() }
    }

    companion object {
        fun parse(raw: String): CollectedNewsPage {
            try {
                val root = JSONObject(raw)
                require(root.getString("schema_version") == "news-candidates-v1")
                fun integer(name: String): Int {
                    val value = root.get(name)
                    require(value is Int && value >= 0)
                    return value
                }
                fun text(item: JSONObject, key: String, max: Int, empty: Boolean = false): String {
                    val value = item.get(key)
                    require(value is String && value.length <= max && (empty || value.isNotBlank()))
                    return value
                }
                val items = root.getJSONArray("articles")
                require(items.length() <= 100)
                val news = (0 until items.length()).map {
                    val item = items.getJSONObject(it)
                    require(item.getString("content_level") == "rss_description")
                    require(item.getString("summary_status") == "not_available")
                    require(item.get("ai_eligible") is Boolean && !item.getBoolean("ai_eligible"))
                    require(!item.has("tts_sentences"))
                    val published = text(item, "published_at", 100)
                    OffsetDateTime.parse(published)
                    val link = text(item, "source_url", 10000)
                    val uri = java.net.URI(link)
                    require(uri.scheme in setOf("http", "https") && uri.host != null && uri.userInfo == null)
                    CollectedNews(text(item, "article_id", 100), text(item, "title", 1000),
                        text(item, "category", 30), text(item, "source", 300), published,
                        text(item, "description", 1500, true), link)
                }
                require(news.map { it.articleId }.distinct().size == news.size)
                require(root.get("has_more") is Boolean)
                return CollectedNewsPage(news, integer("total_candidates"), integer("available_count"),
                    integer("offset"), root.getBoolean("has_more"))
            } catch (e: Exception) { throw NewsListException("뉴스 목록 응답 형식이 올바르지 않습니다.") }
        }
    }
}
