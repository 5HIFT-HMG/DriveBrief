package com.example.drivebrief.ui

import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import com.example.drivebrief.audio.SpeechOutput
import com.example.drivebrief.data.SessionClient
import com.example.drivebrief.data.SessionCheckpointStore
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import org.json.JSONObject
import org.json.JSONArray
import java.util.UUID

@Composable
fun SessionScreen(speech: SpeechOutput?, categories: List<String>, minutes: Int = 20, onExit: () -> Unit) {
    val context = LocalContext.current
    val checkpointStore = remember { SessionCheckpointStore(context.applicationContext) }
    val restored = remember { checkpointStore.load() }
    val client = remember { SessionClient() }
    val scope = rememberCoroutineScope()
    var raw by rememberSaveable { mutableStateOf(restored?.getString("raw")) }
    var length by rememberSaveable { mutableStateOf(restored?.optString("length", "medium") ?: "medium") }
    var index by rememberSaveable { mutableIntStateOf(restored?.optInt("index", 0) ?: 0) }
    var position by rememberSaveable { mutableIntStateOf(restored?.optInt("position", 0) ?: 0) }
    var started by rememberSaveable { mutableStateOf(restored?.optBoolean("started", false) ?: false) }
    var sequence by rememberSaveable { mutableIntStateOf(restored?.optInt("sequence", 0) ?: 0) }
    var bookmarked by rememberSaveable { mutableStateOf(restored?.optBoolean("bookmarked", false) ?: false) }
    var pending by rememberSaveable { mutableStateOf(ArrayList<String>().apply {
        restored?.optJSONArray("pending")?.let { values ->
            for (i in 0 until values.length()) add(values.getString(i))
        }
    }) }
    var paused by remember { mutableStateOf(true) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf("") }
    var syncError by remember { mutableStateOf(false) }
    var retry by remember { mutableIntStateOf(0) }
    var paperMode by rememberSaveable { mutableStateOf(restored?.optBoolean("paper_mode", false) ?: false) }
    var storageError by remember { mutableStateOf(false) }
    var paper by remember { mutableStateOf<String?>(null) }
    val session = remember(raw) { raw?.let { runCatching { SessionClient.parse(it) }.getOrNull() } }
    val article = session?.articles?.getOrNull(index)
    val lifecycle = (LocalContext.current as? ComponentActivity)?.lifecycle

    fun persist() {
        val currentRaw = raw ?: return
        storageError = runCatching {
            checkpointStore.save(JSONObject().put("version", 1).put("raw", currentRaw)
                .put("length", length).put("index", index).put("position", position)
                .put("started", started).put("sequence", sequence).put("bookmarked", bookmarked)
                .put("pending", JSONArray(pending)).put("paper_mode", paperMode))
        }.isFailure
    }
    fun report(state: String) {
        val current = article ?: return
        val event = JSONObject().put("event_id", UUID.randomUUID().toString())
            .put("article_id", current.articleId).put("sequence", sequence++)
            .put("state", state).put("completed_sentences", position)
            .put("bookmarked", bookmarked).toString()
        pending = ArrayList(pending + event)
    }
    fun pause() {
        speech?.stop()
        if (!paused) report("interrupted")
        paused = true
        persist()
    }
    BackHandler(enabled = raw != null && (!paperMode || pending.isNotEmpty())) {
        pause(); paperMode = true; persist()
    }
    val background by rememberUpdatedState({ pause() })
    DisposableEffect(lifecycle, speech) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_PAUSE) background()
        }
        lifecycle?.addObserver(observer)
        onDispose { lifecycle?.removeObserver(observer); speech?.stop() }
    }
    LaunchedEffect(session?.id, pending.firstOrNull(), retry) {
        val id = session?.id
        val event = pending.firstOrNull()
        if (id != null && event != null) {
            try {
                client.report(id, event)
                pending = ArrayList(pending.drop(1))
                persist()
                syncError = false
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                syncError = true
            }
        }
    }
    DisposableEffect(raw, index, position, paused, speech) {
        var valid = true
        val sentence = article?.ttsSentences?.getOrNull(position)
        if (!paused && sentence != null && speech != null) {
            speech.speak(sentence, onStarted = {
                if (valid && !started) { report("playing"); started = true; persist() }
            }, onDone = {
                if (valid) {
                    position++
                    if (position == article?.ttsSentences?.size) {
                        report("completed")
                        index++
                        position = 0
                        bookmarked = false
                        started = false
                        if (index >= (session?.articles?.size ?: 0)) {
                            paused = true
                            paperMode = true
                        }
                    }
                    persist()
                }
            }, onFailure = {
                if (valid) { pause(); error = it }
            })
        }
        onDispose { valid = false; speech?.stop() }
    }
    LaunchedEffect(paperMode, pending.isEmpty(), retry) {
        if (paperMode && pending.isEmpty() && session != null) {
            try {
                paper = client.onepaper(session.id)
                error = ""
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                error = "OnePaper를 불러오지 못했습니다. 다시 시도해 주세요."
            }
        }
    }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text("실제 뉴스 브리핑", fontSize = 30.sp)
        if (raw == null) {
            Text("관심 분야: ${categories.joinToString()}", fontSize = 20.sp)
            Text("선택 시간: ${minutes}분 · 예상 재생 시간 내에서 기사를 편성합니다.", fontSize = 20.sp)
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                listOf("short" to "짧게", "medium" to "중간", "long" to "길게").forEach { (value, label) ->
                    FilterChip(selected = length == value, onClick = { length = value }, enabled = !loading,
                        label = { Text(label, fontSize = 22.sp) }, modifier = Modifier.heightIn(min = 64.dp))
                }
            }
            Button(enabled = !loading && categories.isNotEmpty(), onClick = {
                scope.launch {
                    loading = true
                    error = ""
                    try {
                        raw = client.create(categories, length, minutes * 60).raw
                        persist()
                    } catch (e: CancellationException) {
                        throw e
                    } catch (e: Exception) {
                        error = "브리핑을 불러오지 못했습니다. 로컬 서버를 확인하세요."
                    } finally { loading = false }
                }
            }, modifier = Modifier.heightIn(min = 64.dp)) { Text("브리핑 불러오기", fontSize = 22.sp) }
        }
        if (loading) CircularProgressIndicator()
        session?.let {
            val seconds = JSONObject(it.raw).optInt("estimated_seconds", 0)
            Text("예상 재생 ${seconds / 60}분 ${seconds % 60}초 · 실제 음성 길이와 다를 수 있습니다.", fontSize = 18.sp)
        }
        if (storageError) Text("재생 기록을 기기에 저장하지 못했습니다. 앱을 종료하기 전에 다시 시도하세요.",
            color = MaterialTheme.colorScheme.error, fontSize = 20.sp)
        if (error.isNotBlank()) Text(error, color = MaterialTheme.colorScheme.error, fontSize = 20.sp)
        if (session?.articles?.isEmpty() == true) Text("선택한 분야·길이에 맞는 승인된 요약이 없습니다.", fontSize = 22.sp)
        if (!paperMode) article?.let { item ->
            Text("기사 ${index + 1} / ${session?.articles?.size}", fontSize = 22.sp)
            Text(item.title, fontSize = 28.sp)
            Text("출처: ${item.source}", fontSize = 18.sp)
            Text(if (item.mock == true) "Mock 요약 · 실제 AI 생성 결과 아님" else "LLM 요약 · 검토 승인", fontSize = 18.sp)
            Text(item.oneLine, fontSize = 22.sp)
            Text("완료한 문장 $position / ${item.ttsSentences.size}", fontSize = 20.sp)
            Button(enabled = speech != null, onClick = {
                if (paused) { report("playing"); started = true; paused = false } else pause()
                persist()
            }, modifier = Modifier.heightIn(min = 64.dp)) { Text(if (paused) "재생 / 재개" else "일시정지", fontSize = 22.sp) }
            Button(onClick = {
                speech?.stop()
                report(if (started) "interrupted" else "unplayed")
                index++; position = 0; bookmarked = false; started = false
                if (index >= (session?.articles?.size ?: 0)) { paused = true; paperMode = true }
                persist()
            }, modifier = Modifier.heightIn(min = 64.dp)) { Text("다음 기사", fontSize = 22.sp) }
            Button(onClick = { bookmarked = !bookmarked; report(if (!started) "unplayed" else if (paused) "interrupted" else "playing"); persist() },
                modifier = Modifier.heightIn(min = 64.dp)) { Text(if (bookmarked) "저장 취소" else "기사 저장", fontSize = 22.sp) }
            Button(onClick = { pause(); paperMode = true; persist() }, modifier = Modifier.heightIn(min = 64.dp)) {
                Text("이제 그만 듣기", fontSize = 22.sp)
            }
        }
        if (pending.isNotEmpty()) Text("청취 기록 ${pending.size}건 동기화 대기", fontSize = 18.sp)
        if (syncError || storageError || (paperMode && error.isNotBlank())) {
            Button(onClick = { persist(); retry++ }, modifier = Modifier.heightIn(min = 64.dp)) { Text("연결 재시도", fontSize = 22.sp) }
        }
        if (paperMode) {
            Text("OnePaper", fontSize = 28.sp)
            Button(enabled = pending.isEmpty() && !storageError, onClick = { checkpointStore.clear(); onExit() }, modifier = Modifier.heightIn(min = 64.dp)) {
                Text("홈으로", fontSize = 22.sp)
            }
            Text("기사 전체 내용의 요약이며 청취한 부분만의 요약이 아닙니다.", fontSize = 18.sp)
            paper?.let { value ->
                val items = JSONObject(value).getJSONArray("articles")
                for (i in 0 until items.length()) {
                    val item = items.getJSONObject(i)
                    val state = when (item.getString("state")) { "completed" -> "재생 완료"; "interrupted" -> "중단"; else -> "미재생" }
                    Text("${item.getString("title")} · $state", fontSize = 24.sp)
                    Text(item.getString("one_line"), fontSize = 20.sp)
                    Text(item.getString("detail"), fontSize = 20.sp)
                    Text("출처: ${item.getString("source")}\n${item.optString("source_url")}", fontSize = 16.sp)
                }
            }
        }
    }
}
