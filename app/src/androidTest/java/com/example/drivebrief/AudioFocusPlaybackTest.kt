package com.example.drivebrief

import android.media.AudioManager
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import com.example.drivebrief.audio.BriefingFocus
import com.example.drivebrief.audio.FocusPort
import com.example.drivebrief.audio.SpeechOutput
import com.example.drivebrief.data.*
import com.example.drivebrief.ui.DemoBriefingScreen
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

/** 재생 화면이 포커스 변화에 따라 멈추고, 시스템이 멈춘 경우만 중단 문장 처음부터 다시 읽는지 확인한다. */
class AudioFocusPlaybackTest {
    @get:Rule val compose = createComposeRule()

    private class Port(var result: Int = AudioManager.AUDIOFOCUS_REQUEST_GRANTED) : FocusPort {
        var onChange: ((Int) -> Unit)? = null
        var abandons = 0
        override fun request(onChange: (Int) -> Unit): Int { this.onChange = onChange; return result }
        override fun abandon() { abandons++ }
    }
    private class Speech : SpeechOutput {
        val texts = mutableListOf<String>()
        var stops = 0
        var done: () -> Unit = {}
        override fun speak(text: String, onStarted: () -> Unit, onDone: () -> Unit, onFailure: (String) -> Unit) {
            texts.add(text); done = onDone; onStarted()
        }
        override fun stop() { stops++ }
    }

    private fun open(speech: Speech, port: Port): BriefingFocus {
        val focus = BriefingFocus(port, log = {})
        compose.setContent {
            DemoBriefingScreen(speech, DemoBriefingLoader { DemoBriefingClient.parse(plannedFixture(), true) },
                approvedMode = true, audioFocus = focus, autoPlay = false)
        }
        compose.onNodeWithText("재생", substring = false).performScrollTo().performClick()
        compose.waitForIdle()
        return focus
    }
    private fun change(port: Port, value: Int) { compose.runOnIdle { port.onChange!!(value) }; compose.waitForIdle() }

    @Test fun transientLossPausesAndGainRereadsInterruptedSentence() {
        val speech = Speech(); val port = Port()
        open(speech, port)
        compose.runOnIdle { speech.done() }
        compose.waitForIdle()
        compose.runOnIdle { assertEquals(listOf("첫 문장 1", "둘째 문장 1"), speech.texts) }
        Thread.sleep(1_100)
        change(port, AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK)
        compose.onNodeWithText("안내음이나 통화로 잠시 멈췄습니다. 끝나면 이어서 읽습니다.").assertExists()
        compose.onNodeWithText("재개", substring = false).assertExists()
        change(port, AudioManager.AUDIOFOCUS_GAIN)
        compose.runOnIdle { assertEquals(listOf("첫 문장 1", "둘째 문장 1", "둘째 문장 1"), speech.texts) }
    }

    @Test fun userPauseReleasesFocusAndGainDoesNotResume() {
        val speech = Speech(); val port = Port()
        open(speech, port)
        compose.onNodeWithText("일시정지", substring = false).performScrollTo().performClick()
        compose.runOnIdle { assertEquals(1, port.abandons) }
        change(port, AudioManager.AUDIOFOCUS_GAIN)
        compose.runOnIdle { assertEquals(listOf("첫 문장 1"), speech.texts) }
        compose.onNodeWithText("재개", substring = false).assertExists()
    }

    @Test fun permanentLossStopsWithoutAutoResume() {
        val speech = Speech(); val port = Port()
        open(speech, port)
        change(port, AudioManager.AUDIOFOCUS_LOSS)
        compose.onNodeWithText("다른 앱이 소리를 재생해 브리핑을 멈췄습니다", substring = true).assertExists()
        change(port, AudioManager.AUDIOFOCUS_GAIN)
        compose.runOnIdle { assertEquals(listOf("첫 문장 1"), speech.texts) }
    }

    @Test fun failedAndDelayedRequestsDoNotStartImmediately() {
        val failed = Speech()
        open(failed, Port(AudioManager.AUDIOFOCUS_REQUEST_FAILED))
        compose.onNodeWithText("통화나 안내가 끝나면 재생할 수 있어요.").assertExists()
        compose.runOnIdle { assertTrue(failed.texts.isEmpty()) }
    }

    @Test fun delayedRequestPlaysWhenFocusArrives() {
        val speech = Speech(); val port = Port(AudioManager.AUDIOFOCUS_REQUEST_DELAYED)
        open(speech, port)
        compose.onNodeWithText("다른 소리가 끝나면 이어서 재생합니다.").assertExists()
        compose.runOnIdle { assertTrue(speech.texts.isEmpty()) }
        change(port, AudioManager.AUDIOFOCUS_GAIN)
        compose.runOnIdle { assertEquals(listOf("첫 문장 1"), speech.texts) }
    }

    @Test fun stoppingTheBriefingReleasesFocus() {
        val speech = Speech(); val port = Port()
        val focus = open(speech, port)
        compose.onNodeWithText("재생 중단(OnePaper)", substring = false).performScrollTo().performClick()
        compose.waitForIdle()
        compose.runOnIdle { assertEquals(BriefingFocus.State.IDLE, focus.state); assertEquals(1, port.abandons) }
    }
}
