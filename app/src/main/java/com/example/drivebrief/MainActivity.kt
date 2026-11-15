package com.example.drivebrief

import android.os.Bundle
import android.util.Log
import ai.pleos.playground.vehicle.Vehicle
import ai.pleos.playground.vehicle.api.model.area.DoorArea
import ai.pleos.playground.vehicle.constant.area.DoorValue
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.SystemBarStyle
import androidx.activity.enableEdgeToEdge
import androidx.compose.ui.graphics.toArgb
import com.example.drivebrief.data.FixedGearSource
import com.example.drivebrief.data.GearSource
import com.example.drivebrief.data.PleosGearSource
import com.example.drivebrief.ui.DriveBriefApp
import com.example.drivebrief.audio.PleosSpeechOutput
import com.example.drivebrief.ui.theme.Ink
import com.example.drivebrief.ui.theme.Paper

class MainActivity : ComponentActivity() {
    private lateinit var vehicle: Vehicle
    private lateinit var speechOutput: PleosSpeechOutput
    private var gear: GearSource = FixedGearSource()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        vehicle = Vehicle(this)
        try {
            vehicle.initialize()
            vehicle.getDoor().getCurrentDoorPosition(
                area = DoorArea(DoorValue.ROW_1_LEFT),
                onComplete = { pos -> Log.d("Pleos", "door pos = $pos") },
                onFailed = { e -> Log.e("Pleos", "error", e) }
            )
            gear = PleosGearSource(vehicle).also { it.start() }
        } catch (e: Exception) {
            Log.e("Pleos", "Vehicle initialization or door query failed", e)
        }

        speechOutput = PleosSpeechOutput(this)
        // 밝은 신문지 바탕이므로 시스템 다크 모드와 관계없이 막대 아이콘을 어둡게 둔다.
        val bars = SystemBarStyle.light(Paper.toArgb(), Ink.toArgb())
        enableEdgeToEdge(statusBarStyle = bars, navigationBarStyle = bars)
        setContent {
            if (BuildConfig.DEBUG && intent.getBooleanExtra("private_rss_preview", false)) {
                DriveBriefApp(speechOutput,
                    newsLoader = com.example.drivebrief.data.NewsListLoader { _, _ ->
                        throw com.example.drivebrief.data.NewsListException("비공개 RSS 테스트에서는 클라우드 연결을 사용하지 않습니다.")
                    },
                    briefingLoader = { length, categories -> com.example.drivebrief.data.PrivateRssPreviewLoader(this, length, categories) },
                    privateRssPreview = true, gear = gear.state)
            } else DriveBriefApp(speechOutput, gear = gear.state)

        }
    }

    override fun onDestroy() {
        speechOutput.close()
        gear.close()
        try {
            if (::vehicle.isInitialized) {
                vehicle.release()
            }
        } finally {
            super.onDestroy()
        }
    }
}
