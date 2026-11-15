package com.example.drivebrief.data

import android.content.Context
import com.example.drivebrief.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject

/** Debug only, app-owned input. No credentials, auth signup, publishing or public QR. */
class PrivateRssPreviewLoader(
    context: Context, private val length: String, private val categories: List<String>
) : DemoBriefingLoader {
    private val file = java.io.File(context.applicationContext.filesDir, "private-rss-preview.json")
    override suspend fun load(): DemoBriefing = withContext(Dispatchers.IO) {
        if (!BuildConfig.DEBUG) throw DemoApiException("비공개 테스트는 debug 빌드에서만 가능합니다.")
        try {
            require(file.length() in 1..256_000)
            val raw = JSONObject(file.readText()).getJSONObject(length).toString()
            DemoBriefingClient.parse(raw, true, true)
            DemoBriefingClient.parse(CloudBriefingLoader.onlyCategories(raw, categories), true, true)
        } catch (e: DemoApiException) {
            throw e
        } catch (_: Exception) {
            throw DemoApiException("비공개 RSS 테스트 파일을 확인하세요.")
        }
    }
}
