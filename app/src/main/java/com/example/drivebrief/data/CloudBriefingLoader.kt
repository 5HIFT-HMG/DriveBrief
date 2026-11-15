package com.example.drivebrief.data

import org.json.JSONArray
import org.json.JSONObject

/** Supabase RSS 자동 브리핑과 기존 승인 자료를 구분 검증하고 선택 분야만 남긴다. */
class CloudBriefingLoader(
    private val client: SupabaseNewsClient,
    private val length: String,
    private val categories: List<String>
) : DemoBriefingLoader {
    override suspend fun load(): DemoBriefing {
        val raw = try { client.readPublishedBriefing(length) }
            catch (e: NewsListException) { throw DemoApiException(e.message ?: "서버에 연결할 수 없습니다.") }
            ?: throw DemoApiException(NOT_READY)
        DemoBriefingClient.parse(raw, true) // Validate all items before filtering can hide a corrupt one.
        return DemoBriefingClient.parse(onlyCategories(raw, categories), true)
    }

    companion object {
        const val NOT_READY = "아직 브리핑할 뉴스가 없습니다. 뉴스가 수집되면 다시 시도해 주세요."
        const val NO_MATCH = "선택한 분야에 준비된 브리핑이 없습니다. 다른 분야를 함께 선택해 보세요."

        fun onlyCategories(raw: String, categories: List<String>): String {
            val root = try { JSONObject(raw) } catch (e: Exception) { throw DemoApiException("브리핑 응답 형식이 올바르지 않습니다.") }
            val articles = root.optJSONArray("articles") ?: JSONArray()
            val kept = JSONArray()
            for (i in 0 until articles.length()) {
                val article = articles.getJSONObject(i)
                val own = article.optJSONArray("categories")?.let { a -> (0 until a.length()).map { a.getString(it) } }.orEmpty()
                if (own.any { it in categories }) kept.put(article)
            }
            if (kept.length() == 0) throw DemoApiException(if (articles.length() == 0) NOT_READY else NO_MATCH)
            return root.put("articles", kept).toString()
        }
    }
}
