package com.example.drivebrief.data

import java.net.HttpURLConnection
import java.net.URL
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

data class NewsSession(val id: String, val articles: List<DemoNews>, val raw: String)

class SessionClient(private val baseUrl: String = "http://10.0.2.2:8000") {
    private suspend fun request(path: String, body: String? = null): String = withContext(Dispatchers.IO) {
        val url = URL(baseUrl.trimEnd('/') + path)
        require(url.protocol == "http" && url.host in setOf("10.0.2.2", "127.0.0.1", "localhost"))
        val connection = url.openConnection() as HttpURLConnection
        try {
            connection.connectTimeout = 5000
            connection.readTimeout = 8000
            connection.instanceFollowRedirects = false
            connection.requestMethod = if (body == null) "GET" else "POST"
            connection.setRequestProperty("Accept", "application/json")
            if (body != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            }
            if (connection.responseCode !in 200..299) {
                throw DemoApiException("서버 응답 오류 (${connection.responseCode}). 다시 시도해 주세요.")
            }
            val output = java.io.ByteArrayOutputStream()
            connection.inputStream.use { input ->
                val buffer = ByteArray(4096)
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    if (output.size() + count > 256000) throw DemoApiException("응답 크기가 너무 큽니다.")
                    output.write(buffer, 0, count)
                }
            }
            output.toString("UTF-8")
        } finally {
            connection.disconnect()
        }
    }

    suspend fun create(categories: List<String>, length: String, budgetSeconds: Int? = null): NewsSession {
        val body = JSONObject().put("categories", JSONArray(categories)).put("length", length)
        budgetSeconds?.let {
            require(it in 30..7200)
            body.put("budget_seconds", it)
        }
        return parse(request("/v1/briefings", body.toString()))
    }

    suspend fun report(id: String, event: String) {
        require(id.matches(Regex("[A-Za-z0-9_-]{32,64}")))
        val result = JSONObject(request("/v1/sessions/$id/events", event))
        require(result.get("accepted") == true)
    }

    suspend fun onepaper(id: String): String {
        require(id.matches(Regex("[A-Za-z0-9_-]{32,64}")))
        val raw = request("/v1/sessions/$id/onepaper")
        val result = JSONObject(raw)
        require(result.getString("schema_version") == "onepaper-v1" && result.getString("session_id") == id)
        val articles = result.getJSONArray("articles")
        require(articles.length() <= 10)
        for (i in 0 until articles.length()) {
            val item = articles.getJSONObject(i)
            require(item.getString("state") in setOf("unplayed", "interrupted", "completed"))
            require(item.getString("summary_scope") == "full_article")
            for ((name, max) in listOf("title" to 300, "source" to 300, "one_line" to 250, "detail" to 2500)) {
                val value = item.get(name)
                require(value is String && value.isNotBlank() && value.length <= max)
            }
        }
        return raw
    }

    companion object {
        fun parse(raw: String): NewsSession {
            val root = JSONObject(raw)
            require(root.getString("schema_version") == "session-briefing-v1")
            require(root.get("playback_requires_user_action") == true)
            val id = root.getString("session_id")
            require(id.matches(Regex("[A-Za-z0-9_-]{32,64}")))
            val items = root.getJSONArray("articles")
            require(items.length() <= 10)
            val articles = (0 until items.length()).map { i ->
                val item = items.getJSONObject(i)
                val validation = item.getJSONObject("validation")
                require(validation.get("approved") == true && validation.get("review_required") == false)
                require(item.get("mock") is Boolean)
                val sentences = item.getJSONArray("tts_sentences")
                require(sentences.length() in 1..3)
                fun text(name: String, max: Int): String {
                    val value = item.get(name)
                    require(value is String && value.isNotBlank() && value.length <= max)
                    return value
                }
                DemoNews(text("article_id", 100), text("title", 300), text("source", 300),
                    (0 until sentences.length()).map { j ->
                        val sentence = sentences.get(j)
                        require(sentence is String && sentence.isNotBlank() && sentence.length <= 350)
                        sentence
                    }, text("one_line", 250), text("detail", 2500), item.getBoolean("mock"))
            }
            require(articles.map { it.articleId }.distinct().size == articles.size)
            return NewsSession(id, articles, raw)
        }
    }
}
