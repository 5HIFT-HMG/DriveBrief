package com.example.drivebrief.data

import android.content.Context
import android.util.AtomicFile
import org.json.JSONObject
import java.io.File
import java.io.ByteArrayOutputStream

class SessionCheckpointStore(context: Context) {
    private val file = AtomicFile(File(context.noBackupFilesDir, "news-session.json"))

    fun load(): JSONObject? = runCatching {
        val bytes = file.openRead().use { input ->
            val output = ByteArrayOutputStream()
            val buffer = ByteArray(4096)
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                require(output.size() + count <= 512000)
                output.write(buffer, 0, count)
            }
            output.toByteArray()
        }
        JSONObject(String(bytes, Charsets.UTF_8)).also {
            require(it.getInt("version") == 1)
            SessionClient.parse(it.getString("raw"))
        }
    }.getOrNull()

    fun save(value: JSONObject) {
        val bytes = value.toString().toByteArray(Charsets.UTF_8)
        require(bytes.size <= 512000)
        val output = file.startWrite()
        try {
            output.write(bytes)
            file.finishWrite(output)
        } catch (error: Exception) {
            file.failWrite(output)
            throw error
        }
    }

    fun clear() = file.delete()
}
