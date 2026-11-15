package com.example.drivebrief.ui

import androidx.activity.ComponentActivity
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import com.example.drivebrief.audio.SpeechOutput
import com.example.drivebrief.audio.PleosSpeechOutput
import com.example.drivebrief.audio.MeasuredSpeechOutput
import com.example.drivebrief.audio.SpeechTimingFile
import com.example.drivebrief.audio.TimingContext
import com.example.drivebrief.data.*
import android.util.Log
import com.example.drivebrief.audio.AndroidFocusPort
import com.example.drivebrief.audio.BriefingFocus
import com.example.drivebrief.ui.newspaper.*
import com.example.drivebrief.ui.theme.*
import kotlinx.coroutines.launch

@Composable
fun DemoBriefingScreen(
    speech: SpeechOutput?,
    loader: DemoBriefingLoader,
    approvedMode: Boolean = false,
    history: SessionHistory? = null,
    privateRssPreview: Boolean = false,
    autoPlay: Boolean = approvedMode && !privateRssPreview,
    onFinished: ((sessionId: String?) -> Unit)? = null,
    audioFocus: BriefingFocus? = null,

) {
    val timingContext = LocalContext.current.applicationContext
    val output = remember(speech, approvedMode) {
        if (approvedMode && speech is PleosSpeechOutput)
            MeasuredSpeechOutput(speech, { SpeechTimingFile.get(timingContext).append(it) }, "pleos-on-device")
        else speech
    }
    // 실제 TTS일 때만 브리핑 단위 오디오 포커스를 잡는다. 테스트는 가짜 포커스를 넘긴다.
    val focus = audioFocus ?: remember(speech) {
        if (speech is PleosSpeechOutput) BriefingFocus(AndroidFocusPort(timingContext)) else null
    }
    // 안내음·통화 등으로 시스템이 멈춘 경우만 true. 사용자가 멈춘 상태는 포커스를 다시 받아도 재개하지 않는다.
    var systemPaused by remember { mutableStateOf(false) }
    var historySessionId by rememberSaveable { mutableStateOf<String?>(null) }
    var payload by rememberSaveable { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var articleIndex by rememberSaveable { mutableIntStateOf(0) }
    var sentenceIndex by rememberSaveable { mutableIntStateOf(0) }
    // A recreated Activity always requires an explicit play/resume action.
    var paused by remember { mutableStateOf(true) }
    var started by rememberSaveable { mutableStateOf(false) }
    var ended by rememberSaveable { mutableStateOf(false) }
    var doneMask by rememberSaveable { mutableIntStateOf(0) }
    var skipped by rememberSaveable { mutableStateOf(false) }
    var message by rememberSaveable { mutableStateOf(PLAY_PROMPT) }
    val scope = rememberCoroutineScope()
    val lifecycle = (LocalContext.current as? ComponentActivity)?.lifecycle
    val briefing = remember(payload) { payload?.let { runCatching { DemoBriefingClient.parse(it, approvedMode, privateRssPreview) }.getOrNull() } }
    val article = briefing?.articles?.getOrNull(articleIndex)
    val sentences = article?.ttsSentences.orEmpty()
    val shortRss = briefing?.lengthOption == "짧게" && article?.contentKind == "rss_metadata"
    var titleFinished by rememberSaveable(payload, articleIndex) { mutableStateOf(false) }
    val readingTitle = shortRss && !titleFinished && sentenceIndex == 0 &&
        article != null && sentences.firstOrNull()?.let { !sameText(article.title, it) } == true

    fun play() {
        if (ended) {
            if (briefing != null && approvedMode) historySessionId = history?.start(briefing)
            articleIndex = 0; sentenceIndex = 0; doneMask = 0; skipped = false; started = false; ended = false
            titleFinished = false
        }
        when (focus?.start() ?: BriefingFocus.Start.GRANTED) {
            BriefingFocus.Start.GRANTED -> { systemPaused = false; paused = false }
            BriefingFocus.Start.DELAYED -> { systemPaused = true; message = "다른 소리가 끝나면 이어서 재생합니다." }
            BriefingFocus.Start.FAILED -> { systemPaused = false; message = "통화나 안내가 끝나면 재생할 수 있어요." }
        }
    }
    fun moveTo(index: Int) {
        history?.event(historySessionId, articleIndex, sentenceIndex, "skip_article")
        skipped = true
        if (!approvedMode) paused = true
        output?.stop(); articleIndex = index; sentenceIndex = 0; doneMask = 0
        started = false; ended = false; if (paused) message = if (approvedMode) PAUSED else PLAY_PROMPT
    }

    suspend fun reload() {
        history?.event(historySessionId, articleIndex, sentenceIndex, "interrupt:reload")
        history?.event(historySessionId, articleIndex, sentenceIndex, "end")
        output?.stop()
        paused = true
        payload = null
        loading = true
        error = null
        try {
            val result = loader.load()
            // Parse again at the UI boundary; no unguarded caller-supplied approval.
            val parsed = DemoBriefingClient.parse(result.rawJson, approvedMode, privateRssPreview)
            payload = parsed.rawJson
            historySessionId = if (approvedMode && parsed.articles.isNotEmpty()) history?.start(parsed) else null
            skipped = false
            articleIndex = 0
            sentenceIndex = 0
            started = false
            ended = false
            doneMask = 0
            message = PLAY_PROMPT
            // 홈에서 "브리핑 시작"을 누른 것이 재생 요청이다. 화면 재생성 후에는 다시 누를 때까지 멈춰 둔다.
            if (autoPlay && output != null) play()
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: DemoApiException) {
            error = e.message
        } catch (e: Exception) {
            error = "서버에 연결할 수 없습니다. 다시 시도해 주세요."
        } finally {
            loading = false
        }
    }
    fun advanceArticle() {
        output?.stop()
        if (articleIndex + 1 < (briefing?.articles?.size ?: 0)) {
            articleIndex++; sentenceIndex = 0; doneMask = 0
        } else {
            history?.event(historySessionId, articleIndex, sentenceIndex, "end")
            paused = true; ended = true
            message = if (skipped) "브리핑 종료(중단 또는 건너뛴 내용 있음)" else "브리핑 전체 재생 완료"
        }
    }
    // 끝까지 듣거나 재생 중단을 누르면 한 번만 알린다. 화면 재생성으로 다시 알리지 않는다.
    var finishReported by rememberSaveable { mutableStateOf(false) }
    LaunchedEffect(ended) {
        if (ended) { focus?.release(); systemPaused = false }
        if (!ended) finishReported = false
        else if (!finishReported) { finishReported = true; onFinished?.invoke(historySessionId) }
    }
    LaunchedEffect(Unit) {
        if (payload == null) reload()
        else if (history != null && briefing != null && briefing.articles.isNotEmpty() &&
            history.state.value.sessions.none { it.sessionId == historySessionId }) {
            historySessionId = history.start(briefing)
            articleIndex = 0; sentenceIndex = 0; doneMask = 0; paused = true
            started = false; ended = false; skipped = false
            message = "저장되지 않은 세션입니다. 처음부터 재생 버튼을 눌러 주세요."
        }
    }
    DisposableEffect(output, lifecycle) {
        val observer = LifecycleEventObserver { _, event ->
            // 통화 화면 등이 앱을 가려도, 이미 포커스 손실로 멈춘 상태면 포커스를 유지해 끝난 뒤 이어 읽는다.
            if (event == Lifecycle.Event.ON_PAUSE && !systemPaused) {
                history?.event(historySessionId, articleIndex, sentenceIndex, "interrupt:background")
                output?.stop()
                focus?.release(); systemPaused = false
                paused = true
                if (!ended) message = PAUSED
            }
        }
        lifecycle?.addObserver(observer)
        onDispose {
            history?.event(historySessionId, articleIndex, sentenceIndex, "interrupt:screen_exit")
            lifecycle?.removeObserver(observer); output?.stop(); focus?.release()
        }
    }
    SideEffect {
        focus?.listener = object : BriefingFocus.Listener {
            override fun onSystemPause(change: Int) {
                Log.i(BriefingFocus.TAG, "paused at article=$articleIndex sentence=$sentenceIndex")
                history?.event(historySessionId, articleIndex, sentenceIndex, "interrupt:audio_focus")
                output?.stop(); paused = true; systemPaused = true
                message = "안내음이나 통화로 잠시 멈췄습니다. 끝나면 이어서 읽습니다."
            }
            override fun onSystemResume() {
                if (!systemPaused) return
                Log.i(BriefingFocus.TAG, "resume at article=$articleIndex sentence=$sentenceIndex")
                systemPaused = false; paused = false
            }
            override fun onPermanentLoss() {
                Log.i(BriefingFocus.TAG, "stopped at article=$articleIndex sentence=$sentenceIndex")
                history?.event(historySessionId, articleIndex, sentenceIndex, "interrupt:audio_focus_loss")
                output?.stop(); paused = true; systemPaused = false
                message = "다른 앱이 소리를 재생해 브리핑을 멈췄습니다. 이어 들으려면 재개를 눌러 주세요."
            }
        }
    }
    DisposableEffect(output, articleIndex, sentenceIndex, paused, payload, readingTitle) {
        var valid = true
        val text = if (readingTitle) article?.title else sentences.getOrNull(sentenceIndex)
        if (!paused && text != null && output != null) {
            message = PLAYING
            (output as? MeasuredSpeechOutput)?.context = TimingContext(
                historySessionId ?: "untracked", briefing?.briefingId ?: "legacy",
                article!!.articleId, sentenceIndex, briefing?.lengthOption ?: "legacy",
                briefing?.articles?.sumOf { it.ttsSentences.size } ?: 0)
            output.speak(text,
                onStarted = { if (valid) { history?.event(historySessionId, articleIndex, sentenceIndex, "start"); started = true; message = PLAYING } },
                onDone = {
                    if (valid) {
                        valid = false
                        if (readingTitle) {
                            // 제목만 끝났을 때는 기사를 완료 처리하지 않는다.
                            titleFinished = true
                            started = false
                        } else {
                            history?.event(historySessionId, articleIndex, sentenceIndex, "done")
                            doneMask = doneMask or (1 shl sentenceIndex)
                            if (sentenceIndex + 1 < sentences.size) sentenceIndex++
                            else {
                                if (doneMask != (1 shl sentences.size) - 1) skipped = true
                                if (approvedMode) advanceArticle()
                                else {
                                    paused = true; ended = true
                                    message = if (!skipped) "데모 기사 재생 완료" else "데모 재생 종료(건너뛴 문장 있음)"
                                }
                            }
                        }
                    }
                },
                onFailure = { if (valid) { valid = false; history?.event(historySessionId, articleIndex, sentenceIndex, "interrupt:audio_failure"); focus?.release(); systemPaused = false; paused = true; message = it } })
        }
        onDispose { valid = false; output?.stop() }
    }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(24.dp)) {
        Text(if (approvedMode) "오늘의 브리핑" else "개발용 AI 브리핑", style = serifStyle(48.sp), color = Ink)
        briefing?.lengthOption?.let {
            if (briefing.optionSemantics == "article_detail") {
                BriefingTime.line(briefing.latestSourceAt)?.let { line -> Text(line, style = sansStyle(), color = InkSub) }
                val stale = runCatching { java.time.OffsetDateTime.parse(briefing.latestSourceAt).toInstant()
                    .isBefore(java.time.Instant.now().minusSeconds(86_400)) }.getOrDefault(false)
                if (stale) Text("수집된 뉴스의 발행일이 하루 이상 지났습니다.", style = sansStyle(bold = true), color = Accent)
            } else Text("$it(목표 ${briefing.targetSeconds?.toInt()}초 / 예상 ${briefing.estimatedSeconds?.toInt()}초)", style = sansStyle(), color = InkSub)
        }
        if (loading) {
            CircularProgressIndicator(color = Ink)
            Text(if (approvedMode) "브리핑을 불러오는 중" else "로컬 데모 서버에 연결 중", style = sansStyle(), color = InkSub)
        }
        error?.let {
            Text(it, style = sansStyle(bold = true), color = Accent)
            PaperButton("재시도") { scope.launch { reload() } }
        }
        if (!loading && error == null && briefing?.articles?.isEmpty() == true) {
            Text("불러온 뉴스가 없습니다.", style = sansStyle(), color = InkSub)
        }
        article?.let { item ->
            val total = briefing?.articles?.size ?: 0
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("기사 ${articleIndex + 1} / $total", style = serifStyle(32.sp), color = Accent)
                ProgressRule(if (total == 0) 0f else (articleIndex + 1f) / total)
            }
            Text(item.title, style = serifStyle(44.sp, bold = true), color = Ink)
            if (privateRssPreview) Text("비공개 RSS 테스트 · 미승인 · 게시 불가", style = sansStyle(bold = true), color = Accent)
            if (approvedMode && item.contentKind != "rss_metadata")
                Text(if (item.mock == true) "Mock 요약" else "Groq 요약", style = sansStyle(), color = InkSub)
            if (!sameText(item.oneLine, item.title)) Text(item.oneLine, style = serifStyle(32.sp, bold = false), color = InkSub)
            HRule()
            // 제목은 위에 표시하고, 본문에서는 제목과 같은 문장을 반복하지 않는다.
            val shown = visibleSentences(item.title, item.ttsSentences)
            shown.forEach { (i, sentence) ->
                val current = started && !paused && !readingTitle && i == sentenceIndex
                Text(sentence, style = serifStyle(32.sp, bold = current).copy(lineHeight = 1.6.em),
                    color = if (current) Ink else InkSub)
            }
            // 짧게처럼 제목만 읽는 기사는 RSS 설명을 본문으로 보여준다.
            if (shown.isEmpty() && !sameText(item.detail, item.title))
                ClampText(item.detail, serifStyle(32.sp, bold = false).copy(lineHeight = 1.6.em), InkSub, maxLines = 6)
            HRule(2.dp)
            SpeakingWave(speaking = !paused && message == PLAYING)
            if (message != PLAY_PROMPT) Text(message, style = sansStyle(bold = true),
                color = if (message == PLAYING || message == PAUSED) AccentSoft else Accent)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(16.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                PaperButton(if (!paused) "일시정지" else if (ended) "다시 재생" else if (started) "재개" else if (approvedMode) "재생" else "데모 재생",
                    filled = true, enabled = output != null) {
                    if (!paused) {
                        history?.event(historySessionId, articleIndex, sentenceIndex, "interrupt:pause")
                        output?.stop(); paused = true; message = PAUSED
                        // 사용자가 멈추면 포커스를 반납하고, 다시 재생할 때 새로 요청한다.
                        focus?.release(); systemPaused = false
                    } else play()
                }
                // 실제 브리핑은 다음 문장이 곧 다음 기사인 경우가 많아 이전 기사로 대신한다. 개발용 데모는 그대로 둔다.
                if (approvedMode) PaperButton("이전 기사", enabled = articleIndex > 0) { moveTo(articleIndex - 1) }
                else PaperButton("다음 문장") {
                    output?.stop()
                    history?.event(historySessionId, articleIndex, sentenceIndex, "skip_sentence")
                    skipped = true
                    if (sentenceIndex + 1 < sentences.size) sentenceIndex++
                    else if (approvedMode) advanceArticle()
                    else { paused = true; ended = true; message = "데모 재생 종료(건너뛴 문장 있음)" }
                }
                PaperButton("다음 기사", enabled = articleIndex + 1 < total) { moveTo(articleIndex + 1) }
                PaperButton("재생 중단(OnePaper)") {
                    history?.event(historySessionId, articleIndex, sentenceIndex, "interrupt:stop")
                    history?.event(historySessionId, articleIndex, sentenceIndex, "end")
                    output?.stop(); paused = true; ended = true; skipped = true
                    message = "브리핑 중단(완료되지 않음)"
                }
            }
        }
        Spacer(Modifier.height(16.dp))
    }
}

private const val PLAY_PROMPT = "재생 버튼을 눌러 주세요."
private const val PLAYING = "기사 재생 중"
private const val PAUSED = "기사 일시정지됨"

internal fun sameText(a: String, b: String) =
    a.filterNot { it.isWhitespace() }.trimEnd('.', '!', '?') == b.filterNot { it.isWhitespace() }.trimEnd('.', '!', '?')

/** 화면에 보일 문장과 원래 순번. RSS는 첫 문장이 제목이라 제목 아래에 같은 줄이 반복되지 않게 뺀다. */
internal fun visibleSentences(title: String, sentences: List<String>): List<IndexedValue<String>> =
    sentences.withIndex().filterNot { sameText(it.value, title) }
