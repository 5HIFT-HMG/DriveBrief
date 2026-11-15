package com.example.drivebrief.audio

interface SpeechOutput {
    fun speak(text: String, onStarted: () -> Unit, onDone: () -> Unit, onFailure: (String) -> Unit)
    fun stop()
    fun close() = stop()
}

/** 완성된 문장만 커서를 진행한다. 중간에 멈춘 문장은 재개 시 처음부터 다시 읽는다. */
object SpeechText {
    fun sentences(title: String, detail: String): List<String> {
        val text = detail
        val iterator = java.text.BreakIterator.getSentenceInstance(java.util.Locale.KOREA)
        iterator.setText(text)
        val result = mutableListOf(title.trim().trimEnd('.', '!', '?') + ".")
        var start = iterator.first()
        var end = iterator.next()
        while (end != java.text.BreakIterator.DONE) {
            text.substring(start, end).trim().takeIf { it.isNotEmpty() }?.let(result::add)
            start = end
            end = iterator.next()
        }
        return result
    }
}
