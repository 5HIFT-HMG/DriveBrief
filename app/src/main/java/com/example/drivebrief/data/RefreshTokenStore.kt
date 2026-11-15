package com.example.drivebrief.data

import android.content.Context
import android.util.AtomicFile
import java.io.File

/** 익명 세션의 갱신 토큰만 보관한다. 데모 계정 토큰과 비밀번호는 저장하지 않는다. */
interface RefreshTokenStore {
    fun load(): String?
    fun save(token: String)
}

/** 백업에서 빠지는 앱 전용 폴더에 둔다. 앱을 다시 켜도 같은 익명 사용자로 청취 기록을 이어 쓴다. */
class FileRefreshTokenStore(context: Context) : RefreshTokenStore {
    private val file = AtomicFile(File(context.noBackupFilesDir, "anonymous-refresh-token"))

    @Synchronized override fun load(): String? = try {
        if (file.baseFile.exists()) file.readFully().toString(Charsets.UTF_8).takeIf { it.isNotBlank() } else null
    } catch (_: Exception) { null }

    @Synchronized override fun save(token: String) {
        val output = file.startWrite()
        try { output.write(token.toByteArray()); file.finishWrite(output) }
        catch (e: Exception) { file.failWrite(output); throw e }
    }
}
