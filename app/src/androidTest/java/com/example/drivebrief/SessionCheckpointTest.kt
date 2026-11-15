package com.example.drivebrief

import android.content.ContextWrapper
import androidx.test.platform.app.InstrumentationRegistry
import com.example.drivebrief.data.SessionCheckpointStore
import com.example.drivebrief.data.SessionClient
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.nio.file.Files
import java.net.InetAddress
import java.net.ServerSocket
import java.util.concurrent.LinkedBlockingQueue
import kotlin.concurrent.thread

class SessionCheckpointTest {
    @Test
    fun sessionHttpSendsBudgetAndReportsThenLoadsOnepaper() {
        val id = "a".repeat(32)
        val responses = listOf(
            JSONObject().put("schema_version", "session-briefing-v1")
                .put("playback_requires_user_action", true).put("session_id", id)
                .put("articles", JSONArray()).toString(),
            "{\"accepted\":true}",
            JSONObject().put("schema_version", "onepaper-v1").put("session_id", id)
                .put("articles", JSONArray()).toString()
        )
        val requests = LinkedBlockingQueue<Pair<String, String>>()
        val failures = LinkedBlockingQueue<Throwable>()
        ServerSocket(0, 1, InetAddress.getByName("127.0.0.1")).use { server ->
            server.soTimeout = 10000
            val worker = thread {
                try {
                    responses.forEach { response ->
                        server.accept().use { socket ->
                            socket.soTimeout = 5000
                            val reader = socket.getInputStream().bufferedReader()
                            val line = reader.readLine()
                            var length = 0
                            while (true) {
                                val header = reader.readLine() ?: break
                                if (header.isEmpty()) break
                                if (header.startsWith("Content-Length:", true)) length = header.substringAfter(':').trim().toInt()
                            }
                            val body = CharArray(length)
                            var count = 0
                            while (count < length) {
                                val read = reader.read(body, count, length - count)
                                check(read > 0)
                                count += read
                            }
                            requests.put(line to String(body))
                            val bytes = response.toByteArray(Charsets.UTF_8)
                            socket.getOutputStream().apply {
                                write("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: ${bytes.size}\r\nConnection: close\r\n\r\n".toByteArray())
                                write(bytes); flush()
                            }
                        }
                    }
                } catch (error: Throwable) { failures.put(error) }
            }
            runBlocking {
                val client = SessionClient("http://127.0.0.1:${server.localPort}")
                assertEquals(id, client.create(listOf("IT"), "medium", 1200).id)
                client.report(id, "{\"event_id\":\"event-1\"}")
                assertEquals(id, JSONObject(client.onepaper(id)).getString("session_id"))
            }
            worker.join(10000)
            assertFalse(worker.isAlive)
            if (failures.isNotEmpty()) throw failures.first()
            val create = requests.remove()
            assertTrue(create.first.startsWith("POST /v1/briefings "))
            assertEquals(1200, JSONObject(create.second).getInt("budget_seconds"))
            assertTrue(requests.remove().first.startsWith("POST /v1/sessions/$id/events "))
            assertTrue(requests.remove().first.startsWith("GET /v1/sessions/$id/onepaper "))
        }
    }

    @Test
    fun reopeningStorePreservesPendingEventsAndPosition() {
        val root = Files.createTempDirectory("session-checkpoint").toFile()
        val context = object : ContextWrapper(InstrumentationRegistry.getInstrumentation().targetContext) {
            override fun getNoBackupFilesDir(): File = root
        }
        try {
            val raw = JSONObject().put("schema_version", "session-briefing-v1")
                .put("playback_requires_user_action", true)
                .put("session_id", "a".repeat(32)).put("articles", JSONArray()).toString()
            val event = JSONObject().put("event_id", "pending-event").put("sequence", 7).toString()
            val checkpoint = JSONObject().put("version", 1).put("raw", raw)
                .put("position", 2).put("pending", JSONArray().put(event))
            SessionCheckpointStore(context).save(checkpoint)
            val reopened = SessionCheckpointStore(context)
            val restored = requireNotNull(reopened.load())
            assertEquals(2, restored.getInt("position"))
            assertEquals(event, restored.getJSONArray("pending").getString(0))
            assertEquals(raw, restored.getString("raw"))
            reopened.clear()
            assertNull(SessionCheckpointStore(context).load())
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun malformedCheckpointIsNotRestored() {
        val root = Files.createTempDirectory("session-checkpoint-invalid").toFile()
        val context = object : ContextWrapper(InstrumentationRegistry.getInstrumentation().targetContext) {
            override fun getNoBackupFilesDir(): File = root
        }
        try {
            File(root, "news-session.json").writeText("{invalid")
            assertNull(SessionCheckpointStore(context).load())
        } finally {
            root.deleteRecursively()
        }
    }
}
