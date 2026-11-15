package com.example.drivebrief

import android.os.Bundle
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File

/** Explicit local diagnostic export. Numeric timing/context only; no sentence text or credentials. */
class SpeechTimingExportTest {
    @Test fun exportObservedTimingMetadata() {
        assumeTrue("Local export is an opt-in diagnostic, not a playback test",
            InstrumentationRegistry.getArguments().getString("drivebriefExport") == "true")
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val directory = instrumentation.targetContext.getExternalFilesDir(null)
        assumeTrue("App external-files directory unavailable", directory != null)
        val file = File(directory, "speech-timing-v1.jsonl")
        assumeTrue("No observed timing file yet; this is not a playback success", file.exists())
        require(file.length() < 1_000_000) { "Export exceeds diagnostic size limit" }
        val records = JSONArray()
        file.forEachLine(Charsets.UTF_8) { line ->
            if (line.isNotBlank()) {
                val row = JSONObject(line)
                assertFalse(row.has("text")); assertFalse(row.has("api_key"))
                assertEquals("speech-timing-v1", row.getString("schema"))
                records.put(row)
            }
        }
        instrumentation.sendStatus(2, Bundle().apply { putString("drivebrief_timing_export", records.toString()) })
        assertTrue(records.length() > 0)
    }
}
