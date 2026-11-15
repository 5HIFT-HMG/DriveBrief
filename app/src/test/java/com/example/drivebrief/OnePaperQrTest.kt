package com.example.drivebrief

import com.example.drivebrief.data.OnePaperShare
import com.example.drivebrief.data.SHARE_BASE_URL
import com.example.drivebrief.ui.qrMatrix
import com.example.drivebrief.ui.qrPixels
import com.google.zxing.BinaryBitmap
import com.google.zxing.RGBLuminanceSource
import com.google.zxing.common.HybridBinarizer
import com.google.zxing.qrcode.QRCodeReader
import org.junit.Assert.*
import org.junit.Test

class OnePaperQrTest {
    @Test fun qrDecodesBackToShareUrl() {
        val url = OnePaperShare("AbCdEfGhIjKlMnOpQr_-12", 0).url
        val matrix = qrMatrix(url, 720)
        val source = RGBLuminanceSource(matrix.width, matrix.height, qrPixels(matrix))
        assertEquals(url, QRCodeReader().decode(BinaryBitmap(HybridBinarizer(source))).text)
    }

    @Test fun shareUrlKeepsTokenInFragment() {
        val url = OnePaperShare("AbCdEfGhIjKlMnOpQr_-12", 0).url
        assertEquals("$SHARE_BASE_URL/#AbCdEfGhIjKlMnOpQr_-12", url)
        assertTrue(url.startsWith("https://"))
        assertTrue(url.length < 70)
    }

    @Test fun rejectsMalformedTokens() {
        listOf("", "short", "AbCdEfGhIjKlMnOpQr_-12x", "AbCdEfGhIjKlMnOpQr/+12", "AbCdEfGhIjKlMnOpQr#?12").forEach {
            try { OnePaperShare(it, 0); fail("Expected rejection: $it") } catch (_: IllegalArgumentException) { }
        }
    }
}
