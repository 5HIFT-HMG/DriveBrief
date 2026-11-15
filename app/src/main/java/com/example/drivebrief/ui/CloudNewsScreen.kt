package com.example.drivebrief.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.drivebrief.data.SupabaseNewsClient
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch

@Composable
fun CloudNewsScreen(interestMask: Int, client: SupabaseNewsClient) {
    var signedIn by remember(client) { mutableStateOf(false) }
    var email by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    if (signedIn) {
        Column(Modifier.fillMaxSize()) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("공유 DB 뉴스", fontSize = 22.sp)
                TextButton(enabled = !busy, onClick = {
                    busy = true
                    scope.launch {
                        try { client.signOut() }
                        catch (e: CancellationException) { throw e }
                        catch (_: Exception) { }
                        finally { signedIn = false; busy = false; password = ""; error = null }
                    }
                }) { Text("로그아웃", fontSize = 20.sp) }
            }
            Box(Modifier.weight(1f)) { NewsListContent(interestMask, client) }
        }
        return
    }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text("공유 뉴스 로그인", fontSize = 30.sp)
        Text("등록된 데모 계정으로 로그인하면 같은 최신 뉴스 목록을 볼 수 있습니다.", fontSize = 20.sp)
        Text("주차 후 로그인해 주세요.", fontSize = 18.sp)
        OutlinedTextField(value = email, onValueChange = { email = it }, label = { Text("이메일") },
            singleLine = true, enabled = !busy, modifier = Modifier.fillMaxWidth(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email))
        OutlinedTextField(value = password, onValueChange = { password = it }, label = { Text("비밀번호") },
            singleLine = true, enabled = !busy, modifier = Modifier.fillMaxWidth(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
            visualTransformation = PasswordVisualTransformation())
        error?.let { Text(it, fontSize = 20.sp, color = MaterialTheme.colorScheme.error) }
        Button(enabled = !busy && email.isNotBlank() && password.isNotEmpty(),
            modifier = Modifier.heightIn(min = 64.dp), onClick = {
                busy = true
                error = null
                scope.launch {
                    try { client.signIn(email, password); password = ""; signedIn = true }
                    catch (e: CancellationException) { throw e }
                    catch (e: Exception) { error = e.message ?: "로그인할 수 없습니다." }
                    finally { busy = false }
                }
            }) { Text(if (busy) "로그인 중" else "로그인", fontSize = 22.sp) }
    }
}
