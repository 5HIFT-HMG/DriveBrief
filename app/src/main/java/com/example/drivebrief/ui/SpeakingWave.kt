package com.example.drivebrief.ui

import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.unit.dp
import com.example.drivebrief.ui.theme.AccentSoft
import com.example.drivebrief.ui.theme.Ink
import com.example.drivebrief.ui.theme.InkFaint
import kotlin.math.abs
import kotlin.math.sin

private const val BARS = 61

/**
 * 읽는 중임을 알리는 파형 막대. Pleos TTS는 출력 음량을 주지 않으므로 실제 음량이 아니라 재생 상태 표시다.
 * 가운데가 크게 움직이고 바깥으로 갈수록 잦아든다. 멈추면 막대가 점으로 내려앉는다.
 */
@Composable
fun SpeakingWave(speaking: Boolean, modifier: Modifier = Modifier) {
    val level by animateFloatAsState(if (speaking) 1f else 0f, tween(400), label = "wave-level")
    val phase by rememberInfiniteTransition(label = "wave").animateFloat(
        0f, (2 * Math.PI).toFloat(), infiniteRepeatable(tween(1400, easing = LinearEasing)), label = "wave-phase")
    Canvas(modifier.fillMaxWidth().height(56.dp).semantics {
        contentDescription = "음성 재생 표시"
        stateDescription = if (speaking) "읽는 중" else "멈춤"
    }) {
        val gap = size.width / BARS
        val stroke = (gap * 0.45f).coerceAtMost(6.dp.toPx())
        val mid = size.height / 2
        for (i in 0 until BARS) {
            // 0(가장자리)~1(가운데) 사이 거리. 가운데일수록 크게 움직인다.
            val center = 1f - abs(i - (BARS - 1) / 2f) / ((BARS - 1) / 2f)
            val envelope = center * center
            val motion = 0.35f + 0.65f * abs(sin(phase * 2 + i * 0.55f) * sin(phase + i * 0.23f))
            val half = (stroke / 2 + (mid - stroke / 2) * envelope * motion * level).coerceAtLeast(stroke / 2)
            val color = when {
                level > 0f && center > 0.72f -> AccentSoft
                center > 0.3f -> Ink
                else -> InkFaint
            }
            val x = gap * (i + 0.5f)
            drawLine(color, Offset(x, mid - half), Offset(x, mid + half), stroke, StrokeCap.Round)
        }
    }
}
