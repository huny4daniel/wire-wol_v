package com.wirewol.remote

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/**
 * WireWOL 윈도우 컴패니언(트레이 "연결 정보 보기")이 보여주는 QR 하나로
 * 종료 명령을 보낼 대상(host/port/token)과 WOL에 쓸 MAC 주소까지 한 번에
 * 저장한다 — PC 쪽 getmac 결과를 그대로 받아오므로 사용자가 직접 MAC을 몰라도
 * 된다(다만 어댑터가 여러 개면 잘못 고를 수 있어 나중에 수동으로 고칠 수 있게
 * [saveMac]을 따로 둔다).
 */
class PairingConfig(context: Context) {

    private val appContext = context.applicationContext

    private val prefs by lazy {
        val masterKey = MasterKey.Builder(appContext)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            appContext,
            "pairing_prefs",
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )
    }

    data class Info(val host: String, val port: String, val token: String, val mac: String)

    fun save(host: String, port: String, token: String, mac: String) {
        prefs.edit()
            .putString(KEY_HOST, host)
            .putString(KEY_PORT, port)
            .putString(KEY_TOKEN, token)
            .putString(KEY_MAC, mac)
            .apply()
    }

    fun saveMac(mac: String) {
        prefs.edit().putString(KEY_MAC, mac).apply()
    }

    fun load(): Info? {
        val host = prefs.getString(KEY_HOST, null)
        val port = prefs.getString(KEY_PORT, null)
        val token = prefs.getString(KEY_TOKEN, null)
        if (host.isNullOrBlank() || port.isNullOrBlank() || token.isNullOrBlank()) return null
        return Info(host, port, token, loadMac())
    }

    fun loadMac(): String = prefs.getString(KEY_MAC, "") ?: ""

    fun clear() {
        prefs.edit().clear().apply()
    }

    companion object {
        private const val KEY_HOST = "host"
        private const val KEY_PORT = "port"
        private const val KEY_TOKEN = "token"
        private const val KEY_MAC = "mac"
    }
}
