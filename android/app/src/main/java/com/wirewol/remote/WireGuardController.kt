package com.wirewol.remote

import android.content.Context
import android.util.Log
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import com.wireguard.android.backend.GoBackend
import com.wireguard.android.backend.Tunnel
import com.wireguard.config.Config
import java.io.BufferedReader
import java.io.StringReader

/**
 * 별도 WireGuard 앱 없이, 이미 집 공유기에 설정해둔 WireGuard 서버에 이 앱이
 * 직접 클라이언트로 붙는다 — WireGuard 팀이 다른 앱에 embedding하라고 공식
 * 배포하는 `com.wireguard.android:tunnel` 라이브러리(GoBackend)를 그대로 쓴다
 * (mobile-hub-viewer_v의 android/HubWireGuard.kt를 그대로 옮겨 적은 것).
 *
 * 서버 쪽 설정(피어 공개키/엔드포인트 등)은 사용자가 이미 갖고 있는 클라이언트
 * 설정을 그대로 재사용한다 — 공유기가 만들어준 QR(공식 WireGuard 앱이 읽는 것과
 * 동일하게, 표준 wg-quick .conf 텍스트가 QR 안에 그대로 들어있다)을 스캔해서
 * 얻는다.
 */
class WireGuardController(context: Context) {

    private val appContext = context.applicationContext

    private val prefs by lazy {
        val masterKey = MasterKey.Builder(appContext)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            appContext,
            "wireguard_prefs",
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )
    }

    private val backend by lazy { GoBackend(appContext) }

    private val tunnel = object : Tunnel {
        override fun getName() = TUNNEL_NAME
        override fun onStateChange(newState: Tunnel.State) {
            Log.d(TAG, "tunnel state changed: $newState")
        }
    }

    fun hasConfig(): Boolean = !prefs.getString(KEY_CONF, null).isNullOrBlank()

    // QR에서 읽은 원문(.conf 텍스트, 개인키 포함)을 그대로 암호화 저장한다 —
    // 파싱은 실제로 터널을 올릴 때마다 새로 한다(설정이 바뀌어도 항상 최신
    // 내용으로 붙게).
    fun saveConfigText(raw: String) {
        prefs.edit().putString(KEY_CONF, raw).apply()
    }

    fun clearConfig() {
        prefs.edit().remove(KEY_CONF).apply()
    }

    private fun loadParsedConfig(): Config? {
        val raw = prefs.getString(KEY_CONF, null) ?: return null
        return try {
            Config.parse(BufferedReader(StringReader(raw)))
        } catch (e: Exception) {
            Log.e(TAG, "WireGuard 설정 파싱 실패", e)
            null
        }
    }

    fun isUp(): Boolean = try {
        backend.getState(tunnel) == Tunnel.State.UP
    } catch (e: Exception) {
        false
    }

    // 반드시 VpnService.prepare()로 사용자 승인을 먼저 받은 뒤(필요한 경우)에만
    // 호출할 것 — 네트워크/네이티브 호출이 섞여 있으니 백그라운드 스레드에서
    // 호출한다.
    fun bringUp(): Boolean {
        val config = loadParsedConfig() ?: return false
        return try {
            backend.setState(tunnel, Tunnel.State.UP, config)
            true
        } catch (e: Exception) {
            Log.e(TAG, "터널 연결 실패", e)
            false
        }
    }

    fun bringDown() {
        try {
            backend.setState(tunnel, Tunnel.State.DOWN, null)
        } catch (e: Exception) {
            Log.e(TAG, "터널 종료 실패", e)
        }
    }

    companion object {
        private const val TUNNEL_NAME = "wirewol"
        private const val KEY_CONF = "config_text"
        private const val TAG = "WireGuardController"
    }
}
