package com.example.drivebrief.ui.theme

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable

private val PaperColorScheme = lightColorScheme(
    primary = Ink,
    onPrimary = Paper,
    secondary = Ink,
    onSecondary = Paper,
    secondaryContainer = Ink,
    onSecondaryContainer = Paper,
    background = Paper,
    onBackground = Ink,
    surface = Paper,
    onSurface = Ink,
    surfaceVariant = Paper,
    onSurfaceVariant = InkSub,
    outline = Ink,
    error = Accent
)

private val Square = RoundedCornerShape(0)
private val SquareShapes = Shapes(Square, Square, Square, Square, Square)

/** 신문 지면 테마. 시스템 다크 모드나 동적 색과 관계없이 같은 색을 쓴다. */
@Composable
fun DriveBriefTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = PaperColorScheme,
        typography = Typography,
        shapes = SquareShapes,
        content = content
    )
}
