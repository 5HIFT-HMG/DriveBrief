package com.example.drivebrief.ui

import java.time.Duration
import java.time.Instant
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

/** 서버의 UTC ISO 시각을 운전자가 읽는 한국 시간 문구로 바꾼다. 해석할 수 없으면 null(원문을 노출하지 않음). */
object BriefingTime {
    private val SEOUL = ZoneId.of("Asia/Seoul")
    private val FORMAT = DateTimeFormatter.ofPattern("M월 d일 a h:mm", Locale.KOREA)

    /** 가장 최근 기사의 발행 시각과 경과 시간. 예: "11월 14일 오전 10:35 (3시간 전)" */
    fun line(latestSourceAt: String?, now: Instant = Instant.now()): String? {
        val latest = parse(latestSourceAt) ?: return null
        return "${format(latest)} (${ago(latest, now)})"
    }

    /** 청취 세션 시작 시각. 예: "11월 14일 오후 1:20" */
    fun clock(epochMillis: Long): String = format(Instant.ofEpochMilli(epochMillis))

    fun ago(time: Instant, now: Instant): String {
        val minutes = Duration.between(time, now).toMinutes().coerceAtLeast(0)
        return when {
            minutes < 1 -> "방금"
            minutes < 60 -> "${minutes}분 전"
            minutes < 24 * 60 -> "${minutes / 60}시간 전"
            else -> "${minutes / (24 * 60)}일 전"
        }
    }

    private fun parse(value: String?): Instant? =
        value?.let { runCatching { OffsetDateTime.parse(it).toInstant() }.getOrNull() }

    private fun format(time: Instant): String = time.atZone(SEOUL).format(FORMAT)
}
