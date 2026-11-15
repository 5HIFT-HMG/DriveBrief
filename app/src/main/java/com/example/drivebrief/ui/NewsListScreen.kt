package com.example.drivebrief.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.activity.ComponentActivity
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import kotlinx.coroutines.delay
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.drivebrief.data.*
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

@Composable
fun NewsListScreen(interestMask: Int, loader: NewsListLoader) {
    if (loader is SupabaseNewsClient) CloudNewsScreen(interestMask, loader)
    else NewsListContent(interestMask, loader)
}

@Composable
internal fun NewsListContent(interestMask: Int, loader: NewsListLoader) {
    var filter by rememberSaveable { mutableStateOf("interest") }
    var pageIndex by rememberSaveable { mutableIntStateOf(0) }
    var retry by remember { mutableIntStateOf(0) }
    var data by remember { mutableStateOf<CollectedNewsPage?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(false) }
    val scroll = rememberLazyListState()
    val lifecycle = (LocalContext.current as? ComponentActivity)?.lifecycle
    var active by remember(lifecycle) {
        mutableStateOf(lifecycle?.currentState?.isAtLeast(Lifecycle.State.STARTED) ?: true)
    }
    DisposableEffect(lifecycle) {
        val observer = LifecycleEventObserver { _, _ ->
            active = lifecycle?.currentState?.isAtLeast(Lifecycle.State.STARTED) ?: true
        }
        lifecycle?.addObserver(observer)
        onDispose { lifecycle?.removeObserver(observer) }
    }
    val categories = when (filter) {
        "all" -> null
        "interest" -> MockNews.categories.filterIndexed { i, _ -> interestMask and (1 shl i) != 0 }
        else -> listOf(filter)
    }
    LaunchedEffect(filter, pageIndex, retry, interestMask, active) {
        if (!active) return@LaunchedEffect
        data = null
        var first = true
        while (true) {
            loading = true
            error = null
            try {
                if (categories?.isEmpty() == true) {
                    data = CollectedNewsPage(emptyList(), 0, 0, 0, false)
                } else data = loader.load(categories, pageIndex * 20)
                if (first) scroll.scrollToItem(0)
            } catch (e: kotlinx.coroutines.CancellationException) { throw e }
            catch (e: NewsListException) { error = e.message }
            catch (e: Exception) { error = "뉴스 서버에 연결할 수 없습니다." }
            finally { loading = false }
            first = false
            delay(300_000)
        }
    }
    LazyColumn(Modifier.fillMaxSize(), state = scroll, verticalArrangement = Arrangement.spacedBy(16.dp)) {
        item {
            Text("수집된 뉴스 후보", fontSize = 30.sp)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                (listOf("all" to "전체", "interest" to "관심 분야") + MockNews.categories.map { it to it })
                    .forEach { (value, label) ->
                        FilterChip(selected = filter == value,
                            onClick = { filter = value; pageIndex = 0 },
                            label = { Text(label, fontSize = 20.sp) },
                            modifier = Modifier.heightIn(min = 64.dp))
                    }
            }
        }
        if (loading) item {
            CircularProgressIndicator()
            Text("뉴스 목록 불러오는 중", fontSize = 20.sp)
        }
        error?.let { message ->
            item {
                Text(message, fontSize = 22.sp, color = MaterialTheme.colorScheme.error)
                Button(onClick = { retry++ }, modifier = Modifier.heightIn(min = 64.dp)) {
                    Text("재시도", fontSize = 22.sp)
                }
            }
        }
        data?.let { page ->
            item {
                Text("전체 후보 ${page.total}건(설정상 조회 가능 ${page.available}건)", fontSize = 20.sp)
                if (categories?.isEmpty() == true) Text("선택한 관심 분야가 없습니다. 홈에서 선택하거나 전체를 누르세요.", fontSize = 20.sp)
                else if (page.articles.isEmpty()) Text("해당 조건의 뉴스가 없습니다.", fontSize = 22.sp)
            }
            items(page.articles, key = { it.articleId }) { article ->
                Surface(shape = MaterialTheme.shapes.large) {
                    Column(Modifier.fillMaxWidth().padding(20.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(article.title, fontSize = 26.sp)
                        Text("${article.category}(${article.source})", fontSize = 20.sp,
                            color = MaterialTheme.colorScheme.primary)
                        val time = OffsetDateTime.parse(article.publishedAt)
                            .atZoneSameInstant(ZoneId.of("Asia/Seoul"))
                            .format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm"))
                        Text("발행 $time KST", fontSize = 18.sp)
                    }
                }
            }
            item {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    if (pageIndex > 0) Button(onClick = { pageIndex-- }, modifier = Modifier.heightIn(min = 64.dp)) {
                        Text("이전 20개", fontSize = 20.sp)
                    }
                    if (page.hasMore) Button(onClick = { pageIndex++ }, modifier = Modifier.heightIn(min = 64.dp)) {
                        Text("다음 20개", fontSize = 20.sp)
                    }
                    TextButton(onClick = { retry++ }, modifier = Modifier.heightIn(min = 64.dp)) {
                        Text("새로 불러오기", fontSize = 20.sp)
                    }
                }
            }
        }
        item { Spacer(Modifier.height(16.dp)) }
    }
}
