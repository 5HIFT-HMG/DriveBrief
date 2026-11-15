package com.example.drivebrief

import com.example.drivebrief.data.*
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

private class CloudConnection(url: URL, private val code: Int, private val body: String, private val reply: (() -> String)? = null) : HttpURLConnection(url) {
    val sent = ByteArrayOutputStream()
    var closed = false
    override fun connect() { }
    override fun disconnect() { closed = true }
    override fun usingProxy() = false
    override fun getOutputStream() = sent
    override fun getInputStream() = ByteArrayInputStream((reply?.invoke() ?: body).toByteArray())
    override fun getResponseCode() = code
}

class SupabaseNewsTest {
    private val session = """{"access_token":"user-token","refresh_token":"refresh-token","expires_in":3600}"""
    private val empty = """{"schema_version":"news-candidates-v1","total_candidates":0,"available_count":0,"offset":0,"has_more":false,"articles":[]}"""

    @Test fun authenticatesThenReadsCloudWithUserTokenAndFilters() = runBlocking {
        val calls = mutableListOf<CloudConnection>()
        val client = SupabaseNewsClient(openConnection = { url ->
            CloudConnection(url, 200, if (calls.isEmpty()) session else empty).also { calls.add(it) }
        })
        client.signIn("demo@example.com", "private-password")
        assertTrue(client.load(listOf("사회"), 0).articles.isEmpty())
        assertEquals("/auth/v1/token", calls[0].url.path)
        assertEquals("/rest/v1/rpc/read_news", calls[1].url.path)
        assertNull(calls[0].getRequestProperty("Authorization"))
        assertEquals("Bearer user-token", calls[1].getRequestProperty("Authorization"))
        assertTrue(calls[1].getRequestProperty("apikey").startsWith("sb_publishable_"))
        assertEquals("사회", JSONObject(calls[1].sent.toString("UTF-8")).getJSONArray("p_categories").getString(0))
        assertFalse(calls[1].sent.toString("UTF-8").contains("private-password"))
        assertTrue(calls.all { it.closed })
    }

    @Test fun expiredAccessTokenRefreshesAndRetriesRead() = runBlocking {
        val calls = mutableListOf<CloudConnection>()
        val client = SupabaseNewsClient(openConnection = { url ->
            val n = calls.size
            CloudConnection(url, if (n == 1) 401 else 200, when (n) { 0, 2 -> session; else -> empty })
                .also { calls.add(it) }
        })
        client.signIn("demo@example.com", "password")
        client.load(null, 0)
        assertEquals(4, calls.size)
        assertEquals("grant_type=refresh_token", calls[2].url.query)
        assertEquals("refresh-token", JSONObject(calls[2].sent.toString("UTF-8")).getString("refresh_token"))
    }

    @Test fun forbiddenMembersDoNotReceiveNews() = runBlocking {
        var calls = 0
        val client = SupabaseNewsClient(openConnection = { url ->
            CloudConnection(url, if (calls++ == 0) 200 else 403, session)
        })
        client.signIn("demo@example.com", "password")
        try { client.load(null, 0); fail("Expected membership rejection") }
        catch (e: NewsListException) { assertTrue(e.message!!.contains("권한")) }
    }

    @Test fun rejectsSecretKeyBeforeAnyNetworkRequest() = runBlocking {
        val client = SupabaseNewsClient(publicKey = "sb_secret_invalid", openConnection = { error("Must not connect") })
        try { client.signIn("demo@example.com", "password"); fail("Expected configuration rejection") }
        catch (e: NewsListException) { assertTrue(e.message!!.contains("설정")) }
    }

    @Test fun logoutClearsSessionEvenWhenServerFails() = runBlocking {
        var calls = 0
        val client = SupabaseNewsClient(openConnection = { url ->
            CloudConnection(url, if (calls++ == 0) 200 else 500, session)
        })
        client.signIn("demo@example.com", "password")
        try { client.signOut() } catch (_: NewsListException) { }
        try { client.load(null, 0); fail("Expected login required") }
        catch (e: NewsListException) { assertTrue(e.message!!.contains("로그인")) }
        assertEquals(2, calls)
    }

    @Test fun historyUsesAuthenticatedOwnerAndNeverSendsServerKey() = runBlocking {
        val owner = "12345678-1234-1234-1234-123456789012"
        val calls = mutableListOf<CloudConnection>()
        val token = JSONObject(session).put("user", JSONObject().put("id", owner)).toString()
        val client = SupabaseNewsClient(openConnection = { url ->
            CloudConnection(url, 200, if (calls.isEmpty()) token else "7").also { calls.add(it) }
        })
        client.signIn("demo@example.com", "password")
        assertEquals(owner, client.userId.value)
        assertEquals(7L, client.saveHistory(owner, "12345678-1234-1234-1234-123456789013", 7, "{\"schema\":1,\"sessions\":[]}"))
        val request = calls.last()
        assertEquals("/rest/v1/rpc/save_listening_history", request.url.path)
        assertEquals("Bearer user-token", request.getRequestProperty("Authorization"))
        assertEquals(7L, JSONObject(request.sent.toString("UTF-8")).getLong("p_revision"))
        try { client.readHistory("different-owner", "12345678-1234-1234-1234-123456789013"); fail("Expected owner isolation") }
        catch (_: NewsListException) { }
        assertEquals(2, calls.size)
    }

    @Test fun onePaperShareSendsOnlyDeviceAndSessionAndBuildsFragmentLink() = runBlocking {
        val owner = "12345678-1234-1234-1234-123456789012"
        val calls = mutableListOf<CloudConnection>()
        val token = JSONObject(session).put("user", JSONObject().put("id", owner)).toString()
        val reply = """{"token":"AbCdEfGhIjKlMnOpQr_-12","expires_at":"2026-11-14T06:00:00.123456+00:00"}"""
        val client = SupabaseNewsClient(openConnection = { url ->
            CloudConnection(url, 200, if (calls.isEmpty()) token else reply).also { calls.add(it) }
        })
        client.signIn("demo@example.com", "password")
        val share = client.createOnePaperShare(owner, "12345678-1234-1234-1234-123456789013", "session-1234")
        assertEquals("$SHARE_BASE_URL/#AbCdEfGhIjKlMnOpQr_-12", share.url)
        assertEquals(java.time.Instant.parse("2026-11-14T06:00:00.123Z").toEpochMilli(), share.expiresAt)
        val body = JSONObject(calls.last().sent.toString("UTF-8"))
        assertEquals("/rest/v1/rpc/create_onepaper_share", calls.last().url.path)
        assertEquals(setOf("p_device_id", "p_session_id"), body.keys().asSequence().toSet())
        assertEquals("Bearer user-token", calls.last().getRequestProperty("Authorization"))
    }

    private class MemoryTokens(var token: String? = null) : RefreshTokenStore {
        override fun load() = token
        override fun save(token: String) { this.token = token }
    }
    private val anonymousUser = "12345678-1234-1234-1234-1234567890aa"
    private fun anonymousSession(refresh: String) = """{"access_token":"anon-access","refresh_token":"$refresh","expires_in":3600,"user":{"id":"$anonymousUser","is_anonymous":true}}"""

    @Test fun anonymousSignInCreatesSessionWithoutCredentialsAndStoresRefreshToken() = runBlocking {
        val calls = mutableListOf<CloudConnection>()
        val tokens = MemoryTokens()
        val client = SupabaseNewsClient(anonymousTokens = tokens, openConnection = { url ->
            CloudConnection(url, 200, anonymousSession("anon-refresh-1")).also { calls.add(it) }
        })
        client.signInAnonymously()
        assertEquals("/auth/v1/signup", calls.single().url.path)
        assertEquals("{}", calls.single().sent.toString("UTF-8"))
        assertTrue(calls.single().getRequestProperty("apikey").startsWith("sb_publishable_"))
        assertEquals(anonymousUser, client.userId.value)
        assertTrue(client.anonymous.value)
        assertEquals("anon-refresh-1", tokens.token)
        client.signInAnonymously()
        assertEquals(1, calls.size)
    }

    @Test fun anonymousSignInReusesSavedIdentityAndFallsBackWhenRejected() = runBlocking {
        val calls = mutableListOf<CloudConnection>()
        val tokens = MemoryTokens("saved-refresh")
        val client = SupabaseNewsClient(anonymousTokens = tokens, openConnection = { url ->
            CloudConnection(url, 200, anonymousSession("rotated-refresh")).also { calls.add(it) }
        })
        client.signInAnonymously()
        assertEquals("grant_type=refresh_token", calls.single().url.query)
        assertEquals("saved-refresh", JSONObject(calls.single().sent.toString("UTF-8")).getString("refresh_token"))
        assertEquals("rotated-refresh", tokens.token)

        val rejected = mutableListOf<CloudConnection>()
        val fresh = SupabaseNewsClient(anonymousTokens = MemoryTokens("revoked-refresh"), openConnection = { url ->
            CloudConnection(url, if (rejected.isEmpty()) 400 else 200, anonymousSession("new-refresh")).also { rejected.add(it) }
        })
        fresh.signInAnonymously()
        assertEquals(listOf("/auth/v1/token", "/auth/v1/signup"), rejected.map { it.url.path })
        assertTrue(fresh.anonymous.value)
    }

    @Test fun anonymousSignInKeepsSavedIdentityWhenOffline() = runBlocking {
        val tokens = MemoryTokens("saved-refresh")
        val client = SupabaseNewsClient(anonymousTokens = tokens, openConnection = { url ->
            object : HttpURLConnection(url) {
                override fun connect() = throw java.io.IOException("offline")
                override fun disconnect() { }
                override fun usingProxy() = false
                override fun getOutputStream(): java.io.OutputStream = throw java.io.IOException("offline")
            }
        })
        try { client.signInAnonymously(); fail("Expected connection failure") }
        catch (e: NewsListException) { assertTrue(e.message!!.contains("연결")) }
        assertEquals("saved-refresh", tokens.token)
        assertNull(client.userId.value)
    }

    @Test fun demoLoginReplacesAnonymousSessionAndAnonymousNeverOverridesIt() = runBlocking {
        val owner = "12345678-1234-1234-1234-123456789012"
        val tokens = MemoryTokens()
        val demo = JSONObject(session).put("user", JSONObject().put("id", owner)).toString()
        val client = SupabaseNewsClient(anonymousTokens = tokens, openConnection = { url ->
            CloudConnection(url, 200, if (url.path == "/auth/v1/signup") anonymousSession("anon-refresh") else demo)
        })
        client.signInAnonymously()
        client.signIn("demo@example.com", "password")
        assertEquals(owner, client.userId.value)
        assertFalse(client.anonymous.value)
        client.signInAnonymously()
        assertEquals(owner, client.userId.value)
        assertEquals("anon-refresh", tokens.token)
    }

    @Test fun onePaperShareReportsRateLimitAndUnsyncedSession() = runBlocking {
        val owner = "12345678-1234-1234-1234-123456789012"
        val token = JSONObject(session).put("user", JSONObject().put("id", owner)).toString()
        for ((code, word) in listOf(429 to "잠시 후", 409 to "저장하는 중")) {
            var calls = 0
            val client = SupabaseNewsClient(openConnection = { url ->
                CloudConnection(url, if (calls++ == 0) 200 else code, token)
            })
            client.signIn("demo@example.com", "password")
            try { client.createOnePaperShare(owner, "12345678-1234-1234-1234-123456789013", "session-1234"); fail() }
            catch (e: NewsListException) { assertTrue(e.message!!.contains(word)) }
        }
    }
}

class HistoryCloudStorageTest {
    @Test fun shareRequiresCloudSessionAndUploadsLatestHistoryFirst() = runBlocking {
        val context = androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().targetContext
        val offline = SessionHistory(context, "test_share_offline_" + java.util.UUID.randomUUID())
        offline.awaitReady()
        try { offline.share(offline.start(DemoBriefingClient.parse(plannedFixture(), true))); fail("Expected cloud session required") }
        catch (e: NewsListException) { assertTrue(e.message!!.contains("서버에 연결")) }
        offline.flush(); offline.close()

        val owner = "12345678-1234-1234-1234-123456789012"
        val token = """{"access_token":"test-user","refresh_token":"test-refresh","expires_in":3600,"user":{"id":"$owner"}}"""
        val paths = java.util.concurrent.ConcurrentLinkedQueue<String>()
        val client = SupabaseNewsClient(openConnection = { url ->
            paths.add(url.path)
            when {
                url.path == "/auth/v1/token" -> CloudConnection(url, 200, token)
                url.path.endsWith("read_listening_history") -> CloudConnection(url, 200, "null")
                url.path.endsWith("create_onepaper_share") ->
                    CloudConnection(url, 200, """{"token":"AbCdEfGhIjKlMnOpQr_-12","expires_at":"2099-01-01T00:00:00+00:00"}""")
                else -> {
                    lateinit var connection: CloudConnection
                    connection = CloudConnection(url, 200, "", reply = {
                        JSONObject(connection.sent.toString("UTF-8")).getLong("p_revision").toString()
                    })
                    connection
                }
            }
        })
        client.signIn("demo@example.com", "test-password")
        val history = SessionHistory(context, "test_share_online_" + java.util.UUID.randomUUID())
        history.awaitReady()
        history.connectCloud(HistoryCloudBridge(context, client, owner))
        val id = history.start(DemoBriefingClient.parse(plannedFixture(), true))
        val first = history.share(id)
        val createIndex = paths.indexOf("/rest/v1/rpc/create_onepaper_share")
        assertTrue(paths.take(createIndex).any { it.endsWith("save_listening_history") })
        assertEquals(first, history.share(id))
        assertEquals(1, paths.count { it.endsWith("create_onepaper_share") })
        history.flush(); history.close()
    }


    @Test fun completedCallbacksAreSavedWithAccountAndDeviceIsolation() = runBlocking {
        val owner = "12345678-1234-1234-1234-123456789012"
        val token = """{"access_token":"test-user","refresh_token":"test-refresh","expires_in":3600,"user":{"id":"$owner"}}"""
        val documents = java.util.concurrent.ConcurrentLinkedQueue<String>()
        val client = SupabaseNewsClient(openConnection = { url ->
            when {
                url.path == "/auth/v1/token" -> CloudConnection(url, 200, token)
                url.path.endsWith("read_listening_history") -> CloudConnection(url, 200, "null")
                else -> {
                    lateinit var connection: CloudConnection
                    connection = CloudConnection(url, 200, "", reply = {
                        val body = JSONObject(connection.sent.toString("UTF-8"))
                        documents.add(body.getString("p_document"))
                        body.getLong("p_revision").toString()
                    })
                    connection
                }
            }
        })
        client.signIn("demo@example.com", "test-password")
        val context = androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().targetContext
        val name = "test_cloud_history_" + java.util.UUID.randomUUID()
        val history = SessionHistory(context, name)
        history.awaitReady()
        val id = history.start(DemoBriefingClient.parse(plannedFixture(), true))
        history.event(id, 0, 0, "start")
        history.event(id, 0, 0, "done")
        history.connectCloud(HistoryCloudBridge(context, client, owner))
        kotlinx.coroutines.withTimeout(10000) {
            while (history.state.value.cloudStatus != "DB 동기화 완료") kotlinx.coroutines.delay(50)
        }
        val document = JSONObject(documents.last())
        val session = document.getJSONArray("sessions").getJSONObject(0)
        assertEquals(id, session.getString("session_id"))
        assertEquals(0, session.getJSONArray("progress").getJSONObject(0).getJSONArray("completed").getInt(0))
        assertFalse(documents.last().contains("test-password"))
        assertTrue(SessionHistory.get(context, owner) !== SessionHistory.get(context, "different-user"))
        history.flush()
        history.close()
    }

    @Test fun newerCloudSnapshotRestoresWithoutDiscardingUniqueLocalSessions() = runBlocking {
        val owner = "12345678-1234-1234-1234-123456789012"
        val context = androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().targetContext
        val remoteName = "test_remote_history_" + java.util.UUID.randomUUID()
        val remoteHistory = SessionHistory(context, remoteName)
        remoteHistory.awaitReady()
        val remoteId = remoteHistory.start(DemoBriefingClient.parse(plannedFixture(), true))
        remoteHistory.event(remoteId, 0, 0, "start")
        remoteHistory.event(remoteId, 0, 0, "done")
        remoteHistory.flush(); remoteHistory.close()
        val raw = context.getSharedPreferences(remoteName, android.content.Context.MODE_PRIVATE).getString("sessions", null)!!
        val reply = JSONObject().put("revision", System.currentTimeMillis() + 10000).put("document", raw).toString()
        val token = """{"access_token":"test-user","refresh_token":"test-refresh","expires_in":3600,"user":{"id":"$owner"}}"""
        val client = SupabaseNewsClient(openConnection = { url ->
            when {
                url.path == "/auth/v1/token" -> CloudConnection(url, 200, token)
                url.path.endsWith("read_listening_history") -> CloudConnection(url, 200, reply)
                else -> {
                    lateinit var connection: CloudConnection
                    connection = CloudConnection(url, 200, "", reply = {
                        JSONObject(connection.sent.toString("UTF-8")).getLong("p_revision").toString()
                    })
                    connection
                }
            }
        })
        client.signIn("demo@example.com", "test-password")
        val local = SessionHistory(context, "test_local_history_" + java.util.UUID.randomUUID())
        local.awaitReady()
        val localId = local.start(DemoBriefingClient.parse(plannedFixture(), true))
        local.flush()
        local.connectCloud(HistoryCloudBridge(context, client, owner))
        kotlinx.coroutines.withTimeout(10000) {
            while (local.state.value.cloudStatus != "DB 동기화 완료") kotlinx.coroutines.delay(50)
        }
        assertEquals(setOf(localId, remoteId), local.state.value.sessions.map { it.sessionId }.toSet())
        assertEquals(setOf(0), local.state.value.sessions.single { it.sessionId == remoteId }.progress[0].completed)
        local.flush(); local.close()
    }
}
