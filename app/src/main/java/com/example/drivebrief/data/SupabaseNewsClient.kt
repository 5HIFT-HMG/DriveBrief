package com.example.drivebrief.data

import java.net.HttpURLConnection
import java.net.URL
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

class SupabaseNewsClient(
    private val baseUrl: String = "https://tbffvwmvamwysgvnsfns.supabase.co",
    private val publicKey: String = "sb_publishable_RzA5y02Z391rgHgM38BGbA_1xDz0WLb",
    private val openConnection: (URL) -> HttpURLConnection = { it.openConnection() as HttpURLConnection },
    private val anonymousTokens: RefreshTokenStore? = null
) : NewsListLoader {
    private val mutableUserId = MutableStateFlow<String?>(null)
    val userId: StateFlow<String?> = mutableUserId
    private val mutableAnonymous = MutableStateFlow(false)
    /** 로그인 화면 없이 만든 Supabase 익명 세션이면 true. 청취 기록과 OnePaper 공유만 쓸 수 있다. */
    val anonymous: StateFlow<Boolean> = mutableAnonymous
    private val mutex = Mutex()
    private var accessToken: String? = null
    private var refreshToken: String? = null
    private var expiresAt = 0L

    suspend fun signIn(email: String, password: String) = withContext(Dispatchers.IO) {
        mutex.withLock {
            clearSession()
            if (email.isBlank() || password.isEmpty()) throw NewsListException("이메일과 비밀번호를 입력하세요.")
            setSession(request("/auth/v1/token?grant_type=password",
                JSONObject().put("email", email.trim()).put("password", password)))
        }
    }

    /** 세션이 없을 때만 익명 세션을 만든다. 저장된 익명 갱신 토큰이 있으면 같은 익명 사용자를 이어 쓴다. */
    suspend fun signInAnonymously() = withContext(Dispatchers.IO) {
        mutex.withLock {
            if (accessToken != null) return@withLock
            anonymousTokens?.load()?.let { saved ->
                try {
                    setSession(request("/auth/v1/token?grant_type=refresh_token", JSONObject().put("refresh_token", saved)))
                    if (mutableAnonymous.value) return@withLock
                    clearSession()
                } catch (e: ExpiredSession) { clearSession() }
            }
            setSession(request("/auth/v1/signup", JSONObject()))
            if (!mutableAnonymous.value) { clearSession(); throw NewsListException("익명 세션 응답 형식을 확인할 수 없습니다.") }
        }
    }

    /** 게시된 기사별 설명량 브리핑(RSS 자동/기존 승인). 익명 세션을 먼저 열고, 없으면 null. */
    suspend fun readPublishedBriefing(length: String): String? = withContext(Dispatchers.IO) {
        if (length !in setOf("짧게", "중간", "길게")) throw NewsListException("브리핑 길이를 확인하세요.")
        signInAnonymously()
        mutex.withLock {
            if (accessToken == null) throw NewsListException("서버에 연결할 수 없습니다.")
            if (System.currentTimeMillis() >= expiresAt - 60_000) refresh()
            val body = JSONObject().put("p_length", length)
            val raw = try { request("/rest/v1/rpc/read_published_briefing", body, accessToken) }
                catch (e: ExpiredSession) { refresh(); request("/rest/v1/rpc/read_published_briefing", body, accessToken) }
            raw.trim().takeIf { it != "null" }
        }
    }

    suspend fun signOut() = withContext(Dispatchers.IO) {
        mutex.withLock {
            try {
                accessToken?.let { request("/auth/v1/logout", JSONObject(), it, allowEmpty = true) }
            } finally { clearSession() }
        }
    }

    override suspend fun load(categories: List<String>?, offset: Int): CollectedNewsPage = withContext(Dispatchers.IO) {
        mutex.withLock {
            if (offset < 0 || categories?.any { it !in setOf("경제", "사회", "정치", "IT", "스포츠") } == true) {
                throw NewsListException("조회 조건을 확인하세요.")
            }
            if (accessToken == null) throw NewsListException("공유 뉴스에 로그인하세요.")
            if (System.currentTimeMillis() >= expiresAt - 60_000) refresh()
            val body = JSONObject().put("p_categories", categories?.let { JSONArray(it) } ?: JSONObject.NULL)
                .put("p_offset", offset).put("p_limit", 20)
            val raw = try {
                request("/rest/v1/rpc/read_news", body, accessToken)
            } catch (e: ExpiredSession) {
                refresh()
                try { request("/rest/v1/rpc/read_news", body, accessToken) }
                catch (again: ExpiredSession) { clearSession(); throw NewsListException("로그인이 만료됐습니다. 다시 로그인하세요.") }
            }
            NewsListClient.parse(raw)
        }
    }

    private fun refresh() {
        val token = refreshToken ?: throw NewsListException("다시 로그인하세요.")
        try {
            setSession(request("/auth/v1/token?grant_type=refresh_token", JSONObject().put("refresh_token", token)))
        } catch (e: ExpiredSession) {
            clearSession()
            throw NewsListException("로그인이 만료됐습니다. 다시 로그인하세요.")
        }
    }

    private fun setSession(raw: String) {
        try {
            val data = JSONObject(raw)
            val access = data.getString("access_token")
            val refresh = data.getString("refresh_token")
            val expires = data.getLong("expires_in")
            require(access.isNotBlank() && refresh.isNotBlank() && expires in 1..604800)
            val user = data.optJSONObject("user")?.getString("id")
            user?.let { java.util.UUID.fromString(it) }
            val anonymous = data.optJSONObject("user")?.optBoolean("is_anonymous", false) == true
            accessToken = access
            refreshToken = refresh
            expiresAt = System.currentTimeMillis() + expires * 1000
            mutableAnonymous.value = anonymous
            mutableUserId.value = user
            // 갱신 토큰은 매번 바뀌므로 익명 세션일 때마다 새 값으로 덮어쓴다.
            if (anonymous) anonymousTokens?.save(refresh)
        } catch (e: Exception) {
            clearSession()
            throw NewsListException("로그인 응답 형식을 확인할 수 없습니다.")
        }
    }

    private fun clearSession() {
        accessToken = null; refreshToken = null; expiresAt = 0
        mutableAnonymous.value = false; mutableUserId.value = null
    }

    suspend fun saveHistory(owner: String, device: String, revision: Long, document: String): Long =
        authenticatedHistory(owner, "/rest/v1/rpc/save_listening_history", JSONObject()
            .put("p_device_id", device).put("p_revision", revision).put("p_document", document)).toLong()

    suspend fun readHistory(owner: String, device: String): Pair<Long, String>? {
        val raw = authenticatedHistory(owner, "/rest/v1/rpc/read_listening_history", JSONObject().put("p_device_id", device))
        if (raw.trim() == "null") return null
        val result = JSONObject(raw)
        return result.getLong("revision") to result.getString("document")
    }

    suspend fun createOnePaperShare(owner: String, device: String, sessionId: String): OnePaperShare =
        OnePaperShare.parse(authenticatedHistory(owner, "/rest/v1/rpc/create_onepaper_share", JSONObject()
            .put("p_device_id", device).put("p_session_id", sessionId)))

    private suspend fun authenticatedHistory(owner: String, path: String, body: JSONObject): String = withContext(Dispatchers.IO) {
        mutex.withLock {
            if (mutableUserId.value != owner || accessToken == null) throw NewsListException("해당 계정으로 다시 로그인하세요.")
            if (System.currentTimeMillis() >= expiresAt - 60_000) refresh()
            try { request(path, body, accessToken) }
            catch (e: ExpiredSession) { refresh(); request(path, body, accessToken) }
        }
    }
    private class ExpiredSession : Exception()

    private fun request(path: String, body: JSONObject, token: String? = null, allowEmpty: Boolean = false): String {
        val base = URL(baseUrl)
        if (base.protocol != "https" || !base.host.endsWith(".supabase.co") || base.userInfo != null ||
            base.port != -1 || base.path !in setOf("", "/") || base.query != null || base.ref != null ||
            !publicKey.startsWith("sb_publishable_")) throw NewsListException("공유 뉴스 연결 설정이 올바르지 않습니다.")
        val connection = openConnection(URL(baseUrl.trimEnd('/') + path))
        try {
            connection.requestMethod = "POST"
            connection.connectTimeout = 5000
            connection.readTimeout = 15000
            connection.instanceFollowRedirects = false
            connection.doOutput = true
            connection.setRequestProperty("apikey", publicKey)
            connection.setRequestProperty("Content-Type", "application/json")
            connection.setRequestProperty("Accept", "application/json")
            token?.let { connection.setRequestProperty("Authorization", "Bearer $it") }
            connection.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            val status = connection.responseCode
            if (status == 401) {
                if (path.startsWith("/auth/v1/token?grant_type=password")) throw NewsListException("이메일 또는 비밀번호를 확인하세요.")
                throw ExpiredSession()
            }
            if (status == 400 && path.startsWith("/auth/v1/token?grant_type=refresh_token")) throw ExpiredSession()
            if (status == 400 && path.startsWith("/auth/")) throw NewsListException("로그인 정보를 확인하세요. 문제가 계속되면 다시 로그인하세요.")
            if (status == 403) throw NewsListException("공유 뉴스 이용 권한이 없습니다. 데모 계정 등록을 확인하세요.")
            if (status == 404) throw NewsListException("공유 뉴스 조회 API가 아직 설정되지 않았습니다.")
            if (status == 409) throw NewsListException("청취 기록을 서버에 저장하는 중입니다. 잠시 후 다시 시도하세요.")
            if (status == 429) throw NewsListException("요청이 많습니다. 잠시 후 다시 시도하세요.")
            if (status !in 200..299) throw NewsListException("공유 뉴스 서버 오류입니다. 잠시 후 다시 시도하세요.")
            if (allowEmpty && status == 204) return ""
            return connection.inputStream.use { input ->
                val output = java.io.ByteArrayOutputStream()
                val buffer = ByteArray(4096)
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    if (output.size() + count > 1_000_000) throw NewsListException("뉴스 응답이 너무 큽니다.")
                    output.write(buffer, 0, count)
                }
                output.toString("UTF-8")
            }
        } catch (e: CancellationException) { throw e }
        catch (e: ExpiredSession) { throw e }
        catch (e: NewsListException) { throw e }
        catch (e: Exception) { throw NewsListException("공유 뉴스 서버에 연결할 수 없습니다.") }
        finally { connection.disconnect() }
    }
}
