package com.example.drivebrief.ui

import androidx.activity.compose.BackHandler
import com.example.drivebrief.data.CloudBriefingLoader
import com.example.drivebrief.data.DemoApiException
import com.example.drivebrief.data.DemoBriefingLoader
import com.example.drivebrief.data.FileRefreshTokenStore
import com.example.drivebrief.data.GearState
import com.example.drivebrief.data.OnePaperGate
import com.example.drivebrief.data.PendingOnePaper
import com.example.drivebrief.data.HistoryCloudBridge
import com.example.drivebrief.data.NewsListLoader
import com.example.drivebrief.data.SessionHistory
import com.example.drivebrief.data.SupabaseNewsClient
import com.example.drivebrief.audio.SpeechOutput
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import com.example.drivebrief.ui.newspaper.*
import com.example.drivebrief.ui.theme.*
import androidx.compose.ui.unit.sp
import androidx.compose.ui.tooling.preview.Preview

@Composable
fun DriveBriefApp(speech: SpeechOutput? = null,
    newsLoader: NewsListLoader = LocalContext.current.applicationContext.let { context ->
        remember { SupabaseNewsClient(anonymousTokens = FileRefreshTokenStore(context)) }
    },
    briefingLoader: ((length: String, categories: List<String>) -> DemoBriefingLoader)? = null,
    gear: StateFlow<GearState> = remember { MutableStateFlow(GearState.UNKNOWN) },
    pendingOnePaper: PendingOnePaper = LocalContext.current.applicationContext.let { remember { PendingOnePaper.get(it) } },
    privateRssPreview: Boolean = false) {
    require(!privateRssPreview || com.example.drivebrief.BuildConfig.DEBUG)

    var screen by rememberSaveable { mutableStateOf("home") }
    // OnePaper에서 연 세션. null이면 세션 목록을 보여준다.
    var paperSession by rememberSaveable { mutableStateOf<String?>(null) }
    var categoryMask by rememberSaveable { mutableIntStateOf(31) }
    var length by rememberSaveable { mutableStateOf("중간") }
    var briefingRun by rememberSaveable { mutableIntStateOf(0) }
    var briefingCategories by rememberSaveable { mutableStateOf(listOf<String>()) }
    val historyContext = LocalContext.current.applicationContext
    val sharedClient = if (privateRssPreview) null else newsLoader as? SupabaseNewsClient
    val sharedUserId by (sharedClient?.userId ?: remember { kotlinx.coroutines.flow.MutableStateFlow<String?>(null) }).collectAsState()
    val sharedAnonymous by (sharedClient?.anonymous ?: remember { kotlinx.coroutines.flow.MutableStateFlow(false) }).collectAsState()
    // 익명 세션은 이 기기의 기본 기록을 그대로 쓴다. 연결 전에 쌓인 기록도 연결되면 함께 올라간다.
    val history = remember(historyContext, sharedUserId, sharedAnonymous, privateRssPreview) {
        if (privateRssPreview) SessionHistory.getPrivatePreview(historyContext)
        else sharedUserId?.takeIf { !sharedAnonymous }?.let { SessionHistory.get(historyContext, it) }
            ?: SessionHistory.get(historyContext)
    }
    // 로그인 화면을 거치지 않아도 청취 기록 동기화와 OnePaper 공유가 되도록 익명 세션을 자동으로 연다.
    LaunchedEffect(sharedClient, sharedUserId) {
        if (sharedClient == null || sharedUserId != null) return@LaunchedEffect
        while (true) {
            try { sharedClient.signInAnonymously(); break }
            catch (e: kotlinx.coroutines.CancellationException) { throw e }
            catch (_: Exception) { kotlinx.coroutines.delay(30_000) }
        }
    }
    DisposableEffect(history, sharedClient, sharedUserId) {
        if (sharedClient != null && sharedUserId != null) {
            history.connectCloud(HistoryCloudBridge(historyContext, sharedClient, sharedUserId!!))
        }
        onDispose { history.connectCloud(null) }
    }
    val savedHistory by history.state.collectAsState()
    val gearState by gear.collectAsState()
    // Preview completion must never consume or create a normal cloud session reminder.
    val activePending = remember(historyContext, privateRssPreview, pendingOnePaper) {
        if (privateRssPreview) PendingOnePaper(com.example.drivebrief.data.PrefsKeyValueStore(
            historyContext, "private_rss_pending_onepaper")) else pendingOnePaper
    }

    // P(또는 기어를 읽을 수 없는 차량)에서 앱에 들어오거나 P로 바뀌면 주행 중 끝난 세션의 OnePaper를 한 번 띄운다.
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    var resumed by remember { mutableIntStateOf(0) }
    DisposableEffect(lifecycle) {
        val observer = LifecycleEventObserver { _, event -> if (event == Lifecycle.Event.ON_RESUME) resumed++ }
        lifecycle.addObserver(observer)
        onDispose { lifecycle.removeObserver(observer) }
    }
    LaunchedEffect(gearState, resumed) {
        if (resumed > 0) OnePaperGate.takeAutoShow(gearState, activePending)?.let {
            speech?.stop()
            paperSession = it
            screen = "paper"
        }
    }
    // 브리핑이 끝났을 때 P가 아니면 OnePaper로 가지 않고 주행 후 보여줄 세션으로 남긴다.
    fun briefingFinished(sessionId: String?) {
        if (OnePaperGate.showOnFinish(gear.value)) { paperSession = sessionId; screen = "paper" }
        else {
            sessionId?.let(activePending::mark)
            screen = "home"
        }
    }

    BackHandler(screen != "home") { speech?.stop(); screen = "home" }
    BackHandler(screen == "paper" && paperSession != null) { paperSession = null }
    DriveBriefTheme {
        Scaffold(containerColor = Paper) { insets ->
            Column(Modifier.fillMaxSize().padding(insets)
                .padding(start = 72.dp, end = 72.dp, top = 36.dp, bottom = 48.dp)) {
                Masthead(compact = screen != "home", menu = {
                    MenuButton(if (screen == "home") "OnePaper 보기" else "홈으로") {
                        speech?.stop()
                        paperSession = null
                        screen = if (screen == "home") "paper" else "home"
                    }
                })
                when (screen) {
                    // 스크롤 영역은 두되 한 화면 높이를 최소로 잡아 보통은 스크롤 없이 들어가게 한다.
                    "home" -> BoxWithConstraints(Modifier.weight(1f).fillMaxWidth()) {
                        val pageHeight = maxHeight
                        val rightWidth = minOf(680.dp, maxWidth * 0.42f)
                        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
                            Row(Modifier.fillMaxWidth().heightIn(min = pageHeight)
                                .height(IntrinsicSize.Max).padding(top = 36.dp)) {
                                Column(Modifier.weight(1f).fillMaxHeight(),
                                    verticalArrangement = Arrangement.SpaceBetween) {
                                    Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
                                        Text("오늘의 브리핑", style = sansStyle(28.sp, bold = true), color = Accent)
                                        Text("오늘의 이동,\n나만의 브리핑",
                                            style = serifStyle(104.sp).copy(lineHeight = 1.15.em), color = Ink)
                                        HRule(modifier = Modifier.padding(vertical = 8.dp))
                                        Text("출발 전에 관심 분야와 기사 길이를 선택하세요.",
                                            style = serifStyle(36.sp, bold = false), color = Ink)
                                    }
                                    Column(Modifier.padding(vertical = 36.dp)) {
                                        PrimaryAction("브리핑 시작($length)", enabled = categoryMask != 0,
                                            modifier = Modifier.fillMaxWidth()) {
                                            speech?.stop()
                                            briefingRun++
                                            briefingCategories = MockNews.categories
                                                .filterIndexed { i, _ -> categoryMask and (1 shl i) != 0 }
                                            screen = "briefing"
                                        }
                                    }
                                }
                                Spacer(Modifier.width(56.dp))
                                VRule()
                                Spacer(Modifier.width(56.dp))
                                Column(Modifier.width(rightWidth),
                                    verticalArrangement = Arrangement.spacedBy(36.dp)) {
                                    Column(verticalArrangement = Arrangement.spacedBy(24.dp)) {
                                        SectionHead("01", "관심 분야")
                                        MockNews.categories.withIndex().chunked(2).forEach { row ->
                                            Row(horizontalArrangement = Arrangement.spacedBy(24.dp)) {
                                                row.forEach { (i, category) ->
                                                    val bit = 1 shl i
                                                    ChoiceButton(category, selected = categoryMask and bit != 0,
                                                        modifier = Modifier.weight(1f), multi = true) {
                                                        categoryMask = categoryMask xor bit
                                                    }
                                                }
                                                if (row.size == 1) Spacer(Modifier.weight(1f))
                                            }
                                        }
                                        if (categoryMask == 0) Text("시작하려면 한 분야 이상 선택해 주세요.",
                                            style = sansStyle(), color = InkSub)
                                    }
                                    Column(verticalArrangement = Arrangement.spacedBy(24.dp)) {
                                        SectionHead("02", "기사 길이")
                                        Row(horizontalArrangement = Arrangement.spacedBy(24.dp)) {
                                            listOf("짧게", "중간", "길게").forEach { option ->
                                                ChoiceButton(option, selected = length == option,
                                                    modifier = Modifier.weight(1f), fontSize = 38.sp) {
                                                    length = option
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    // Mac 파이프라인이 Supabase에 게시한 승인 브리핑을 익명 세션으로 읽어 재생한다.
                    "briefing" -> Box(Modifier.weight(1f).padding(top = 24.dp)) {
                        key(briefingRun) {
                            val loader = remember(briefingRun) {
                                briefingLoader?.invoke(length, briefingCategories)
                                    ?: sharedClient?.let { CloudBriefingLoader(it, length, briefingCategories) }
                                    ?: DemoBriefingLoader { throw DemoApiException(CloudBriefingLoader.NOT_READY) }
                            }
                            if (!savedHistory.ready) CircularProgressIndicator()
                            else if (savedHistory.error != null) Text(savedHistory.error!!, style = sansStyle())
                            else DemoBriefingScreen(speech, loader, approvedMode = true, history = history,
                                privateRssPreview = privateRssPreview, onFinished = ::briefingFinished)

                        }
                    }
                    "paper" -> Column(
                        Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(top = 36.dp),
                        verticalArrangement = Arrangement.spacedBy(24.dp)
                    ) {
                        Text("OnePaper", style = serifStyle(48.sp), color = Ink)
                        Text("정차 후 읽는 나의 브리핑", style = serifStyle(32.sp, bold = false), color = Ink)
                        if (privateRssPreview) Text("비공개 RSS 테스트 기록 · 외부 공유 불가", style = sansStyle())
                        SessionPaper(savedHistory, privateRssPreview = privateRssPreview,
                            onShare = if (privateRssPreview) null else { id -> history.share(id) },
                            qrAllowed = !privateRssPreview && OnePaperGate.qrAllowed(gearState),
                            selected = paperSession, onSelect = { paperSession = it })

                        Spacer(Modifier.height(16.dp))
                    }
                }
            }
        }
    }
}

@Preview(name = "Car landscape", widthDp = 1720, heightDp = 1232)
@Preview(name = "Compact", widthDp = 420, heightDp = 800)
@Composable
private fun DriveBriefPreview() {
    DriveBriefApp()
}
