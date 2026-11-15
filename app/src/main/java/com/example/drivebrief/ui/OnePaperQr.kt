package com.example.drivebrief.ui

import android.graphics.Bitmap
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.example.drivebrief.data.OnePaperShare
import com.example.drivebrief.ui.newspaper.HRule
import com.example.drivebrief.ui.newspaper.PaperButton
import com.example.drivebrief.ui.theme.*
import com.google.zxing.BarcodeFormat
import com.google.zxing.EncodeHintType
import com.google.zxing.common.BitMatrix
import com.google.zxing.qrcode.QRCodeWriter
import com.google.zxing.qrcode.decoder.ErrorCorrectionLevel
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

fun qrMatrix(text: String, sizePx: Int): BitMatrix = QRCodeWriter().encode(text, BarcodeFormat.QR_CODE, sizePx, sizePx,
    mapOf(EncodeHintType.ERROR_CORRECTION to ErrorCorrectionLevel.M, EncodeHintType.MARGIN to 4))

fun qrPixels(matrix: BitMatrix): IntArray = IntArray(matrix.width * matrix.height) { i ->
    if (matrix[i % matrix.width, i / matrix.width]) android.graphics.Color.BLACK else android.graphics.Color.WHITE
}

fun qrBitmap(text: String, sizePx: Int): Bitmap =
    Bitmap.createBitmap(qrPixels(qrMatrix(text, sizePx)), sizePx, sizePx, Bitmap.Config.ARGB_8888)

/** 차량 화면에서 폰 카메라로 찍기 쉽도록 흰 바탕에 크게 띄운다. 테마와 관계없이 QR은 흰 바탕·검은 모듈이다. */
@Composable
fun OnePaperQrDialog(share: OnePaperShare, onClose: () -> Unit) {
    val bitmap = remember(share.url) { qrBitmap(share.url, 720).asImageBitmap() }
    val expires = remember(share.expiresAt) {
        SimpleDateFormat("M월 d일 a h:mm", Locale.KOREA).format(Date(share.expiresAt))
    }
    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Column(Modifier.background(Paper).padding(48.dp).widthIn(max = 720.dp),
            horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(24.dp)) {
            Text("폰으로 이어보기", style = serifStyle(44.sp), color = Ink)
            HRule(2.dp)
            Box(Modifier.background(Color.White).padding(8.dp)) {
                Image(bitmap, contentDescription = "OnePaper 링크 QR", filterQuality = FilterQuality.None,
                    modifier = Modifier.size(360.dp))
            }
            Text("폰 카메라로 QR을 비추면 브라우저에서 이 OnePaper가 열립니다.",
                style = sansStyle(), color = Ink, textAlign = TextAlign.Center)
            Text("${expires}까지 열 수 있습니다.", style = sansStyle(), color = InkSub)
            PaperButton("닫기", filled = true, onClick = onClose)
        }
    }
}
