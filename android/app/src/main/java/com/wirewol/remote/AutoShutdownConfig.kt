package com.wirewol.remote

import android.content.Context

/**
 * "PC 켜기 후 자동 종료" 옵션 — 원격으로 PC를 켜놓고 깜빡 잊고 못 끄는 경우를
 * 막기 위해, PC 켜기 버튼으로 켠 PC가 실제로 켜진 것이 확인되면 지정한 시간
 * 뒤로 종료 예약을 자동으로 걸어둔다(예약 끄기 버튼을 대신 눌러주는 것과 같다).
 * 기본값은 사용 안 함.
 *
 * 민감 정보가 아니라서 PairingConfig처럼 암호화하지 않고 평범한 prefs에 둔다.
 */
class AutoShutdownConfig(context: Context) {

    private val prefs = context.applicationContext.getSharedPreferences("auto_shutdown_prefs", Context.MODE_PRIVATE)

    var enabled: Boolean
        get() = prefs.getBoolean(KEY_ENABLED, false)
        set(value) = prefs.edit().putBoolean(KEY_ENABLED, value).apply()

    var delayMinutes: Int
        get() = prefs.getInt(KEY_DELAY_MINUTES, DEFAULT_DELAY_MINUTES)
        set(value) = prefs.edit().putInt(KEY_DELAY_MINUTES, value).apply()

    fun clear() {
        prefs.edit().clear().apply()
    }

    companion object {
        private const val KEY_ENABLED = "enabled"
        private const val KEY_DELAY_MINUTES = "delay_minutes"
        private const val DEFAULT_DELAY_MINUTES = 60
    }
}
