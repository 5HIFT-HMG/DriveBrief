package com.example.drivebrief.ui

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.RectangleShape
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import com.example.drivebrief.data.*
import com.example.drivebrief.ui.newspaper.ClampText
import com.example.drivebrief.ui.newspaper.HRule
import com.example.drivebrief.ui.newspaper.PaperButton
import com.example.drivebrief.ui.theme.*
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch

const val QR_PARK_ONLY = "폰으로 이어보기는 기어를 P로 바꾼 뒤에 이용할 수 있습니다."

/**
 * OnePaper. selected가 없으면 청취 세션 목록(표), 있으면 그 세션의 기사 지면을 보여준다.
 * 목록에 없는 세션 ID면 목록으로 돌아간다.
 */
@Composable
fun SessionPaper(snapshot: HistorySnapshot, onShare: (suspend (String) -> OnePaperShare)? = null,
    qrAllowed: Boolean = true, privateRssPreview: Boolean = false,
    selected: String? = null, onSelect: (String?) -> Unit = {}) {

    Text(if (privateRssPreview) "미승인 RSS 비공개 테스트 기록" else "브리핑 청취 기록", style = serifStyle(32.sp), color = Ink)
    // 정상 동기화는 알리지 않고, 연결·전송 대기처럼 확인이 필요한 상태만 보인다.
    snapshot.cloudStatus?.takeIf { it != CLOUD_SYNCED }?.let { Text(it, style = sansStyle(), color = InkSub) }
    snapshot.error?.let { Text(it, style = sansStyle(bold = true), color = Accent) }
    if (!snapshot.ready) Text("저장된 기록을 불러오는 중", style = sansStyle(), color = InkSub)
    if (snapshot.ready && snapshot.sessions.isEmpty()) Text("브리핑 기록이 없습니다.", style = sansStyle(), color = InkSub)

    val session = snapshot.sessions.firstOrNull { it.sessionId == selected }
    if (session == null) SessionTable(snapshot.sessions, onSelect)
    else SessionDetail(session, onShare, qrAllowed) { onSelect(null) }
}

@Composable
private fun SessionTable(sessions: List<ListeningSession>, onSelect: (String) -> Unit) {
    if (sessions.isEmpty()) return
    Column(Modifier.fillMaxWidth()) {
        HRule(2.dp)
        TableRow(Modifier.padding(vertical = 12.dp), "청취 일시", "길이", "기사", header = true)
        HRule()
        sessions.forEach { session ->
            Surface(onClick = { onSelect(session.sessionId) }, shape = RectangleShape,
                color = Color.Transparent, contentColor = Ink, modifier = Modifier.fillMaxWidth()) {
                TableRow(Modifier.heightIn(min = 96.dp),
                    BriefingTime.clock(session.createdAt), session.briefing.lengthOption ?: "-",
                    "${session.briefing.articles.size}건")
            }
            HRule()
        }
    }
}

@Composable
private fun TableRow(modifier: Modifier, time: String, length: String, count: String, header: Boolean = false) {
    val style = if (header) sansStyle(bold = true) else serifStyle(32.sp, bold = false)
    val color = if (header) InkSub else Ink
    Row(modifier.fillMaxWidth().padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(time, Modifier.weight(3f), style = style, color = color)
        Text(length, Modifier.weight(1f), style = style, color = color)
        Text(count, Modifier.weight(1f), style = style, color = color)
        Text(if (header) "" else "›", Modifier.width(32.dp), style = serifStyle(40.sp), color = InkSub)
    }
}

@Composable
private fun SessionDetail(session: ListeningSession, onShare: (suspend (String) -> OnePaperShare)?,
    qrAllowed: Boolean, onBack: () -> Unit) {
    val scope = rememberCoroutineScope()
    var sharing by remember { mutableStateOf(false) }
    var shareError by remember { mutableStateOf<String?>(null) }
    var shown by remember { mutableStateOf<OnePaperShare?>(null) }
    // P가 아니면 QR을 띄우지 않고, 떠 있던 QR도 닫는다.
    LaunchedEffect(qrAllowed) { if (!qrAllowed) shown = null }
    val canShowQr by rememberUpdatedState(qrAllowed)
    if (qrAllowed) shown?.let { OnePaperQrDialog(it) { shown = null } }

    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        PaperButton("‹ 목록으로", onClick = onBack)
        HRule(2.dp)
        Text("${BriefingTime.clock(session.createdAt)} · ${session.briefing.lengthOption ?: "-"}",
            style = sansStyle(), color = InkSub)
        if (onShare != null) {
            PaperButton(if (sharing) "QR 준비 중" else "폰으로 이어보기") {
                if (sharing) return@PaperButton
                if (!qrAllowed) { shareError = QR_PARK_ONLY; return@PaperButton }
                sharing = true
                shareError = null
                scope.launch {
                    try { onShare(session.sessionId).let { if (canShowQr) shown = it else shareError = QR_PARK_ONLY } }
                    catch (e: CancellationException) { throw e }
                    catch (e: Exception) { shareError = e.message ?: "잠시 후 다시 시도하세요." }
                    finally { sharing = false }
                }
            }
            shareError?.let { Text("$it(다시 누르면 재시도합니다)", style = sansStyle(bold = true), color = Accent) }
        }
        session.briefing.articles.forEachIndexed { i, article ->
            ClampText("${i + 1}. ${article.title}", serifStyle(36.sp), Ink, maxLines = 2)
            // RSS는 한 줄 요약이 제목과 같아, 설명(detail)을 기사 내용으로 보여준다.
            listOf(article.detail, article.oneLine).firstOrNull { !sameText(it, article.title) }?.let {
                MoreText(it, key = session.sessionId + ":" + article.articleId)
            }
            HRule()
        }
    }
}

/** 3줄까지 보여주고 넘칠 때만 더보기/접기를 단다. 처음부터 3줄 이하면 버튼이 없다. */
@Composable
private fun MoreText(text: String, key: String) {
    var expanded by rememberSaveable(key) { mutableStateOf(false) }
    var overflows by remember(key, text) { mutableStateOf(false) }
    Text(text, style = serifStyle(28.sp, bold = false).copy(lineHeight = 1.6.em), color = InkSub,
        maxLines = if (expanded) Int.MAX_VALUE else 3, overflow = TextOverflow.Ellipsis,
        onTextLayout = { if (!expanded) overflows = it.hasVisualOverflow })
    if (overflows || expanded) PaperButton(if (expanded) "접기" else "더보기") { expanded = !expanded }
}
