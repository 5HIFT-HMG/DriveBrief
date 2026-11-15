package com.example.drivebrief

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.os.Handler
import android.os.Looper
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.test.platform.app.InstrumentationRegistry
import com.example.drivebrief.audio.PleosSpeechOutput
import com.example.drivebrief.data.DemoBriefingClient
import com.example.drivebrief.data.DemoBriefingLoader
import com.example.drivebrief.ui.DemoBriefingScreen
import org.junit.Rule
import org.junit.Test

/** 실제 Pleos TTS 재생 중 내비 안내 포커스가 들어오면 멈췄다가, 안내가 끝나면 이어 읽는지 확인한다. */
class RealTtsFocusTest {
    @get:Rule val compose = createComposeRule()

    @Test fun navigationPromptPausesRealTtsAndResumesAfterwards() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        lateinit var speech: PleosSpeechOutput
        InstrumentationRegistry.getInstrumentation().runOnMainSync { speech = PleosSpeechOutput(context) }
        compose.setContent {
            DemoBriefingScreen(speech, DemoBriefingLoader { DemoBriefingClient.parse(plannedFixture(), true) }, approvedMode = true, autoPlay = false)
        }
        compose.onNodeWithText("재생", substring = false).performScrollTo().performClick()
        compose.waitUntil(30_000) { compose.onAllNodes(hasText("기사 재생 중")).fetchSemanticsNodes().isNotEmpty() }
        Thread.sleep(1_500)

        val audio = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        val navigation = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
            .setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ASSISTANCE_NAVIGATION_GUIDANCE).build())
            .setOnAudioFocusChangeListener({ }, Handler(Looper.getMainLooper())).build()
        audio.requestAudioFocus(navigation)
        try {
            compose.waitUntil(10_000) {
                compose.onAllNodesWithText("안내음이나 통화로 잠시 멈췄습니다. 끝나면 이어서 읽습니다.").fetchSemanticsNodes().isNotEmpty()
            }
        } finally { audio.abandonAudioFocusRequest(navigation) }
        compose.waitUntil(30_000) { compose.onAllNodes(hasText("기사 재생 중")).fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("재생 중단(OnePaper)", substring = false).performScrollTo().performClick()
        InstrumentationRegistry.getInstrumentation().runOnMainSync { speech.close() }
    }
}
