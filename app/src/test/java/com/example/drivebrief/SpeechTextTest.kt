package com.example.drivebrief

import com.example.drivebrief.audio.SpeechText
import org.junit.Assert.*
import org.junit.Test

class SpeechTextTest {
    @Test fun koreanSentencesRetainFactsAndOrder() {
        val sentences = SpeechText.sentences("오늘의 뉴스", "11월 11일 발표했습니다. 참석자는 20명입니다. 다음은 IT 소식입니다.")
        assertEquals(listOf("오늘의 뉴스.", "11월 11일 발표했습니다.", "참석자는 20명입니다.", "다음은 IT 소식입니다."), sentences)
    }
}
