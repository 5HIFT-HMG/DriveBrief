package com.example.drivebrief.data

import java.time.OffsetDateTime
import org.json.JSONObject

/** 폰 조회 페이지(정적 사이트) 주소. 토큰은 서버 로그에 남지 않도록 # 뒤에 붙인다. */
const val SHARE_BASE_URL = "https://carpaper-onepager.pages.dev"

data class OnePaperShare(val token: String, val expiresAt: Long) {
    init { require(token.matches(TOKEN)) }
    val url: String get() = "$SHARE_BASE_URL/#$token"

    companion object {
        private val TOKEN = Regex("^[A-Za-z0-9_-]{22}$")

        fun parse(raw: String): OnePaperShare = try {
            val data = JSONObject(raw)
            OnePaperShare(data.getString("token"),
                OffsetDateTime.parse(data.getString("expires_at")).toInstant().toEpochMilli())
        } catch (e: Exception) {
            throw NewsListException("공유 링크 응답 형식을 확인할 수 없습니다.")
        }
    }
}
