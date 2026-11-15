package com.example.drivebrief.data

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/**
 * 기어 상태. CHECKING은 SDK 첫 응답 전이라 아무것도 자동으로 띄우지 않는다.
 * UNKNOWN은 읽기 실패·미지원이며 정차와 같이 취급한다(주행 중 판정은 실제 D/R/N 신호가 있을 때만).
 */
enum class GearState { CHECKING, PARK, DRIVING, UNKNOWN;
    val parkedOrUnknown: Boolean get() = this == PARK || this == UNKNOWN
}

/** OnePaper·QR 표시 시점 규칙. 화면 코드와 분리해 단위 테스트한다. */
object OnePaperGate {
    /** 브리핑이 끝났을 때 바로 OnePaper로 갈지. false면 주행 후 보여줄 세션으로 남긴다. */
    fun showOnFinish(gear: GearState): Boolean = gear.parkedOrUnknown
    fun qrAllowed(gear: GearState): Boolean = gear.parkedOrUnknown

    /** 앱 진입·복귀 또는 P 전환 시 자동으로 띄울 세션. 한 번 꺼내면 다시 띄우지 않는다. */
    fun takeAutoShow(gear: GearState, pending: PendingOnePaper): String? =
        if (gear.parkedOrUnknown) pending.take() else null
}

interface KeyValueStore {
    fun get(key: String): String?
    fun put(key: String, value: String?)
}

class PrefsKeyValueStore(context: Context, name: String = "pending_onepaper") : KeyValueStore {
    private val prefs = context.applicationContext.getSharedPreferences(name, Context.MODE_PRIVATE)
    override fun get(key: String): String? = prefs.getString(key, null)
    override fun put(key: String, value: String?) {
        prefs.edit().apply { if (value == null) remove(key) else putString(key, value) }.apply()
    }
}

/** 주행 중 끝난 브리핑 세션 하나를 앱 재시작 뒤에도 기억한다. 새 세션이 끝나면 앞의 것을 대체한다. */
class PendingOnePaper(private val store: KeyValueStore) {
    private val mutable = MutableStateFlow(store.get(KEY))
    val sessionId: StateFlow<String?> = mutable

    @Synchronized fun mark(sessionId: String) { store.put(KEY, sessionId); mutable.value = sessionId }

    @Synchronized fun take(): String? = mutable.value?.also { store.put(KEY, null); mutable.value = null }

    companion object {
        private const val KEY = "session_id"
        @Volatile private var shared: PendingOnePaper? = null
        fun get(context: Context): PendingOnePaper = shared ?: synchronized(this) {
            shared ?: PendingOnePaper(PrefsKeyValueStore(context)).also { shared = it }
        }
    }
}

/** 기어 신호 공급원. 실제 차량은 Pleos SDK, 테스트는 고정 값을 쓴다. */
interface GearSource {
    val state: StateFlow<GearState>
    fun close() { }
}

class FixedGearSource(initial: GearState = GearState.UNKNOWN) : GearSource {
    override val state = MutableStateFlow(initial)
}
