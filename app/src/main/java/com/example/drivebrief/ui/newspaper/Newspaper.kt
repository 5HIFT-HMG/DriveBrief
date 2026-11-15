package com.example.drivebrief.ui.newspaper

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.RectangleShape
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Fill
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.text.PlatformTextStyle
import androidx.compose.ui.text.style.LineHeightStyle
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import com.example.drivebrief.ui.theme.*
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.Locale

// 신문 지면 공통 컴포넌트. 화면 코드는 여기 있는 괘선, 제호, 버튼만 쓴다.

@Composable
fun HRule(thickness: Dp = 1.dp, modifier: Modifier = Modifier) {
    Box(modifier.fillMaxWidth().height(thickness).background(Ink))
}

@Composable
fun VRule(thickness: Dp = 2.dp, modifier: Modifier = Modifier) {
    Box(modifier.fillMaxHeight().width(thickness).background(Ink))
}

@Composable
fun DashedRule(modifier: Modifier = Modifier) {
    Canvas(modifier.fillMaxWidth().height(1.dp)) {
        drawLine(InkFaint, Offset(0f, 0f), Offset(size.width, 0f), 1.dp.toPx(),
            pathEffect = PathEffect.dashPathEffect(floatArrayOf(12f, 8f)))
    }
}

/**
 * 제호. compact는 날짜 줄을 빼고 제호를 56sp로 줄인 재생 화면과 OnePaper용이다.
 * menu가 없으면 띠를 그리지 않는다.
 */
@Composable
fun Masthead(compact: Boolean = false, menu: (@Composable () -> Unit)? = null) {
    Column(Modifier.fillMaxWidth()) {
        if (!compact) {
            val date = LocalDate.now().format(DateTimeFormatter.ofPattern("yyyy년 M월 d일 EEEE", Locale.KOREA))
            Text(date, Modifier.padding(bottom = 8.dp), style = sansStyle(), color = InkSub)
            HRule()
        }
        val size = if (compact) 56.sp else 108.sp
        // 글꼴 위아래 여백을 잘라 글자 높이 기준으로 놓고, 괘선과의 간격은 padding으로만 같게 맞춘다.
        val gap = if (compact) 24.dp else 32.dp
        // 마지막 글자 뒤 자간만큼 앞을 띄워 가운데를 맞춘다.
        Text("차간신문",
            Modifier.fillMaxWidth().padding(start = (size.value * 0.12f).dp, top = gap, bottom = gap),
            style = TextStyle(fontFamily = MastheadFont, fontWeight = FontWeight.ExtraBold,
                fontSize = size, letterSpacing = 0.12.em, textAlign = TextAlign.Center,
                lineHeight = 1.em,
                platformStyle = PlatformTextStyle(includeFontPadding = false),
                lineHeightStyle = LineHeightStyle(LineHeightStyle.Alignment.Center, LineHeightStyle.Trim.Both)),
            color = Ink)
        HRule(6.dp)
        Spacer(Modifier.height(5.dp))
        HRule()
        if (menu != null) {
            Row(Modifier.fillMaxWidth().height(80.dp), horizontalArrangement = Arrangement.End,
                verticalAlignment = Alignment.CenterVertically) {
                menu()
            }
            HRule(2.dp)
        }
    }
}

/** 띠 메뉴 버튼. 왼쪽에만 세로선을 긋는다. */
@Composable
fun MenuButton(label: String, onClick: () -> Unit) {
    Surface(onClick = onClick, color = Color.Transparent, contentColor = Ink, shape = RectangleShape,
        modifier = Modifier.fillMaxHeight().widthIn(min = 76.dp).drawBehind {
            drawLine(Ink, Offset(0f, 0f), Offset(0f, size.height), 1.dp.toPx())
        }) {
        Row(Modifier.padding(horizontal = 32.dp), verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            Text(label, style = serifStyle(30.sp))
            ChevronMark(Ink)
        }
    }
}

/** 주요 실행 버튼 (예: 브리핑 시작). */
@Composable
fun PrimaryAction(label: String, modifier: Modifier = Modifier, enabled: Boolean = true, onClick: () -> Unit) {
    Button(onClick = onClick, enabled = enabled, shape = RectangleShape,
        colors = ButtonDefaults.buttonColors(containerColor = Ink, contentColor = Paper,
            disabledContainerColor = InkFaint, disabledContentColor = Paper),
        contentPadding = PaddingValues(horizontal = 48.dp),
        modifier = modifier.height(152.dp)) {
        PlayMark(Paper, 40.dp)
        Spacer(Modifier.width(32.dp))
        Text(label, style = serifStyle(52.sp))
    }
}

/** 일반 버튼. filled는 바탕을 먹색으로 채운다. */
@Composable
fun PaperButton(label: String, modifier: Modifier = Modifier, filled: Boolean = false, enabled: Boolean = true, onClick: () -> Unit) {
    Button(onClick = onClick, enabled = enabled, shape = RectangleShape,
        colors = ButtonDefaults.buttonColors(
            containerColor = if (filled) Ink else Color.Transparent,
            contentColor = if (filled) Paper else Ink,
            disabledContainerColor = if (filled) InkFaint else Color.Transparent,
            disabledContentColor = if (filled) Paper else InkFaint),
        border = BorderStroke(2.dp, if (enabled) Ink else InkFaint),
        contentPadding = PaddingValues(horizontal = 36.dp, vertical = 12.dp),
        modifier = modifier.heightIn(min = 80.dp)) {
        Text(label, style = serifStyle(32.sp))
    }
}

/**
 * 관심 분야와 길이 선택 버튼. multi는 복수 선택이라 오른쪽 끝에 체크 상태를 그린다.
 * 선택 상태는 selectable 의미로 노출한다.
 */
@Composable
fun ChoiceButton(
    label: String,
    selected: Boolean,
    modifier: Modifier = Modifier,
    fontSize: TextUnit = 36.sp,
    multi: Boolean = false,
    onClick: () -> Unit
) {
    Surface(selected = selected, onClick = onClick, shape = RectangleShape,
        color = if (selected) Ink else Color.Transparent,
        contentColor = if (selected) Paper else Ink,
        border = BorderStroke(2.dp, Ink),
        modifier = modifier.height(96.dp)) {
        Row(Modifier.padding(horizontal = 32.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(label, Modifier.weight(1f), style = serifStyle(fontSize, bold = selected),
                textAlign = if (multi) TextAlign.Start else TextAlign.Center, maxLines = 1)
            if (multi) {
                if (selected) CheckMark(Paper)
                else Box(Modifier.size(28.dp).border(2.dp, Ink))
            }
        }
    }
}

/** 개발용 버튼. 점선 테두리로 실제 기능과 구분한다. */
@Composable
fun DevButton(label: String, modifier: Modifier = Modifier, onClick: () -> Unit) {
    Surface(onClick = onClick, color = Color.Transparent, contentColor = Ink, shape = RectangleShape,
        modifier = modifier.heightIn(min = 80.dp).drawBehind {
            val w = 2.dp.toPx()
            drawRect(InkFaint, topLeft = Offset(w / 2, w / 2), size = Size(size.width - w, size.height - w),
                style = Stroke(w, pathEffect = PathEffect.dashPathEffect(floatArrayOf(12f, 8f))))
        }) {
        Box(Modifier.padding(horizontal = 28.dp, vertical = 12.dp), contentAlignment = Alignment.Center) {
            Text(label, style = sansStyle(), textAlign = TextAlign.Center)
        }
    }
}

/** 섹션 머리: 빨간 번호 + 이름, 아래 2dp 괘선. */
@Composable
fun SectionHead(number: String, title: String, modifier: Modifier = Modifier) {
    Column(modifier.fillMaxWidth()) {
        Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
            Text(number, Modifier.alignByBaseline(), style = serifStyle(44.sp), color = Accent)
            Text(title, Modifier.alignByBaseline(), style = serifStyle(40.sp), color = Ink)
        }
        Spacer(Modifier.height(12.dp))
        HRule(2.dp)
    }
}

/**
 * 제목, 요약처럼 길 수 있는 글. maxLines를 넘으면 단어 단위로 잘라 "···"를 붙인다.
 * 띄어쓰기가 없는 긴 단어 하나만 남으면 그때는 글자 단위로 자른다.
 */
@Composable
fun ClampText(
    text: String,
    style: TextStyle,
    color: Color,
    maxLines: Int,
    modifier: Modifier = Modifier
) {
    var base by remember(text) { mutableStateOf(text) }
    Text(if (base == text) text else "$base···", modifier, style = style, color = color,
        maxLines = maxLines, overflow = TextOverflow.Clip,
        onTextLayout = { layout ->
            if (layout.hasVisualOverflow) {
                val visible = base.take(layout.getLineEnd(maxLines - 1, visibleEnd = true)).trimEnd()
                val space = visible.lastIndexOf(' ')
                base = if (space > 0) visible.substring(0, space).trimEnd() else visible.dropLast(1)
            }
        })
}

/** 북마크 토글. 꺼짐은 빈 리본, 켜짐은 채운 리본. */
@Composable
fun BookmarkToggle(checked: Boolean, onCheckedChange: (Boolean) -> Unit) {
    Surface(checked = checked, onCheckedChange = onCheckedChange, shape = RectangleShape,
        color = Color.Transparent, contentColor = Ink, border = BorderStroke(2.dp, Ink),
        modifier = Modifier.size(80.dp).semantics { contentDescription = "북마크" }) {
        Box(contentAlignment = Alignment.Center) { BookmarkMark(checked, Ink, 40.dp) }
    }
}

/** 북마크 기호. filled가 false면 테두리만 그린다. */
@Composable
fun BookmarkMark(filled: Boolean, color: Color, size: Dp, modifier: Modifier = Modifier) {
    Canvas(modifier.size(size * 0.7f, size)) {
        val stroke = 3.dp.toPx()
        val inset = if (filled) 0f else stroke / 2
        val ribbon = Path().apply {
            moveTo(inset, inset)
            lineTo(this@Canvas.size.width - inset, inset)
            lineTo(this@Canvas.size.width - inset, this@Canvas.size.height - inset)
            lineTo(this@Canvas.size.width / 2, this@Canvas.size.height * 0.72f)
            lineTo(inset, this@Canvas.size.height - inset)
            close()
        }
        drawPath(ribbon, color, style = if (filled) Fill else Stroke(stroke, join = StrokeJoin.Miter))
    }
}

/** 진행 막대. 둥근 끝 없이 테두리와 채움만 쓴다. */
@Composable
fun ProgressRule(fraction: Float, modifier: Modifier = Modifier) {
    Box(modifier.fillMaxWidth().height(12.dp).border(2.dp, Ink)) {
        Box(Modifier.fillMaxHeight().fillMaxWidth(fraction.coerceIn(0f, 1f)).background(Ink))
    }
}

@Composable
private fun PlayMark(color: Color, size: Dp) {
    Canvas(Modifier.size(size)) {
        drawPath(Path().apply {
            moveTo(this@Canvas.size.width * 0.15f, 0f)
            lineTo(this@Canvas.size.width, this@Canvas.size.height / 2)
            lineTo(this@Canvas.size.width * 0.15f, this@Canvas.size.height)
            close()
        }, color)
    }
}

@Composable
private fun ChevronMark(color: Color) {
    Canvas(Modifier.size(14.dp, 24.dp)) {
        drawPath(Path().apply {
            moveTo(0f, 0f)
            lineTo(size.width, size.height / 2)
            lineTo(0f, size.height)
        }, color, style = Stroke(3.dp.toPx(), cap = StrokeCap.Butt, join = StrokeJoin.Miter))
    }
}

@Composable
private fun CheckMark(color: Color) {
    Canvas(Modifier.size(28.dp)) {
        drawPath(Path().apply {
            moveTo(size.width * 0.05f, size.height * 0.5f)
            lineTo(size.width * 0.38f, size.height * 0.82f)
            lineTo(size.width * 0.95f, size.height * 0.15f)
        }, color, style = Stroke(4.dp.toPx(), cap = StrokeCap.Butt, join = StrokeJoin.Miter))
    }
}
