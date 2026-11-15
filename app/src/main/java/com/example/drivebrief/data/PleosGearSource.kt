package com.example.drivebrief.data

import ai.pleos.playground.vehicle.Vehicle
import ai.pleos.playground.vehicle.constant.control.VehicleGear
import ai.pleos.playground.vehicle.listener.GearSelectionListener
import android.os.Handler
import android.os.Looper
import android.util.Log
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/**
 * Pleos Vehicle SDK의 기어 구독(pleos.car.permission.CAR_DRIVE).
 * SDK가 이 API를 deprecated로 표시했지만 Playground 에뮬레이터와 Virtual Console에서 동작하는 경로라 사용한다.
 * 실패하거나 GEAR_UNKNOWN이면 UNKNOWN으로 둔다.
 */
@Suppress("DEPRECATION")
class PleosGearSource(private val vehicle: Vehicle) : GearSource {
    private val mutable = MutableStateFlow(GearState.CHECKING)
    private val handler = Handler(Looper.getMainLooper())
    override val state: StateFlow<GearState> = mutable
    private val listener = object : GearSelectionListener {
        override fun onSelected(gear: VehicleGear?) { mutable.value = map(gear) }
        override fun onFailed(e: Exception) {
            Log.w("Pleos", "gear subscription failed", e)
            mutable.value = GearState.UNKNOWN
        }
    }

    fun start() {
        // 첫 응답이 3초 안에 오지 않으면 미지원으로 보고 UNKNOWN으로 둔다.
        handler.postDelayed({ mutable.compareAndSet(GearState.CHECKING, GearState.UNKNOWN) }, 3000)
        try {
            vehicle.getGear().getCurrentGearSelectionState(
                onComplete = { mutable.value = map(it) },
                onFailed = { Log.w("Pleos", "gear read failed", it); mutable.value = GearState.UNKNOWN })
            vehicle.getGear().registerGearSelection(listener)
        } catch (e: Exception) {
            Log.w("Pleos", "gear unavailable", e)
            mutable.value = GearState.UNKNOWN
        }
    }

    override fun close() {
        handler.removeCallbacksAndMessages(null)
        try { vehicle.getGear().unregisterGearSelection(listener) } catch (_: Exception) { }
    }

    companion object {
        fun map(gear: VehicleGear?): GearState = when (gear) {
            VehicleGear.GEAR_PARK -> GearState.PARK
            null, VehicleGear.GEAR_UNKNOWN -> GearState.UNKNOWN
            else -> GearState.DRIVING
        }
    }
}
