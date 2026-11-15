package com.example.drivebrief.data

import android.content.Context
import android.util.AtomicFile
import java.util.UUID

class HistoryCloudBridge(context: Context, private val client: SupabaseNewsClient, private val owner: String) {
    private val device: String = synchronized(HistoryCloudBridge::class.java) {
        val file = AtomicFile(java.io.File(context.noBackupFilesDir, "history-device-id"))
        if (file.baseFile.exists()) file.openRead().use { UUID.fromString(it.readBytes().toString(Charsets.UTF_8)).toString() }
        else {
            val id = UUID.randomUUID().toString()
            val output = file.startWrite()
            try { output.write(id.toByteArray()); file.finishWrite(output) }
            catch (e: Exception) { file.failWrite(output); throw e }
            id
        }
    }
    suspend fun restore(): Pair<Long, String>? = client.readHistory(owner, device)
    suspend fun save(revision: Long, document: String): Long {
        require(document.toByteArray().size <= 450_000)
        return client.saveHistory(owner, device, revision, document)
    }
    suspend fun share(sessionId: String): OnePaperShare = client.createOnePaperShare(owner, device, sessionId)
}
