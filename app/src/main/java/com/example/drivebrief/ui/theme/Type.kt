package com.example.drivebrief.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.intl.LocaleList
import androidx.compose.ui.text.style.LineBreak
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import com.example.drivebrief.R

/** 제호 "차간신문"에만 쓴다. */
val MastheadFont = FontFamily(Font(R.font.nanum_myeongjo_extrabold, FontWeight.ExtraBold))

/** 제목, 버튼, 섹션 이름. 600과 900만 넣었다. */
val SerifFont = FontFamily(
    Font(R.font.noto_serif_kr_semibold, FontWeight.SemiBold),
    Font(R.font.noto_serif_kr_black, FontWeight.Black)
)

/** 안내 문구와 보조 라벨. 기기 기본 한글 고딕(Noto Sans CJK)을 쓴다. */
val SansFont = FontFamily.SansSerif

// 단어(어절) 중간에서 줄을 바꾸지 않는다. 한국어 규칙으로 끊도록 locale을 고정한다.
// API 33 미만에서는 기본 줄바꿈이 된다.
private val WordBreak = LineBreak(LineBreak.Strategy.Simple, LineBreak.Strictness.Strict, LineBreak.WordBreak.Phrase)
private val Korean = LocaleList("ko-KR")

val Typography = Typography(
    bodyLarge = TextStyle(
        fontFamily = SansFont,
        fontWeight = FontWeight.Medium,
        fontSize = 24.sp,
        lineHeight = 1.4.em,
        lineBreak = WordBreak,
        localeList = Korean
    ),
    labelLarge = TextStyle(
        fontFamily = SerifFont,
        fontWeight = FontWeight.Black,
        fontSize = 28.sp,
        lineBreak = WordBreak,
        localeList = Korean
    )
)

/** 명조 제목. bold가 false면 600(SemiBold). */
fun serifStyle(size: TextUnit, bold: Boolean = true) = TextStyle(
    fontFamily = SerifFont,
    fontWeight = if (bold) FontWeight.Black else FontWeight.SemiBold,
    fontSize = size,
    lineHeight = 1.3.em,
    lineBreak = WordBreak,
    localeList = Korean
)

/** 고딕 안내 문구. bold가 true면 700. */
fun sansStyle(size: TextUnit = 24.sp, bold: Boolean = false) = TextStyle(
    fontFamily = SansFont,
    fontWeight = if (bold) FontWeight.Bold else FontWeight.Medium,
    fontSize = size,
    lineHeight = 1.4.em,
    lineBreak = WordBreak,
    localeList = Korean
)
