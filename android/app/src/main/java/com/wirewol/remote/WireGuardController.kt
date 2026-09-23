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

    // GoBackend와 Tunnel은 반드시 프로세스 전체에서 하나만 써야 한다 —
    // GoBackend.getState()는 "자기 인스턴스가 올린 터널 객체와 같은가"만 보고,
    // 올린 터널 핸들도 인스턴스 필드에 들고 있다. MainActivity/SettingsActivity/
    // WireWolApplication이 각자 인스턴스를 만들면, 실제로는 터널이 떠 있는데도
    // 다른 인스턴스에서는 isUp()이 false로 보이고, 그 상태로 bringUp()을 부르면
    // 같은 개인키로 두 번째 wg 장치가 떠서 서버 쪽 엔드포인트가 둘 사이를
    // 오가며 연결이 됐다 안 됐다 한다.
    private val backend get() = sharedBackend(appContext)
    private val tunnel get() = sharedTunnel

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

    // 메인 스레드에서도 부르므로 lock을 잡지 않는다 — getState는 필드 비교뿐이라
    // 가볍고, bringUp이 서비스 기동을 기다리는 동안(최대 수 초) 화면이 멈추면 안 된다.
    fun isUp(): Boolean = try {
        backend.getState(tunnel) == Tunnel.State.UP
    } catch (e: Exception) {
        false
    }

    // 반드시 VpnService.prepare()로 사용자 승인을 먼저 받은 뒤(필요한 경우)에만
    // 호출할 것 — 네트워크/네이티브 호출이 섞여 있으니 백그라운드 스레드에서
    // 호출한다.
    fun bringUp(): Boolean = synchronized(lock) {
        val config = loadParsedConfig() ?: return false
        // 이미 떠 있으면 다시 올리지 않는다(WireWolApplication의 복귀 시 재연결과
        // 버튼/자동 연결이 동시에 들어오는 경우).
        if (isUp()) return true
        try {
            backend.setState(tunnel, Tunnel.State.UP, config)
            true
        } catch (e: Exception) {
            Log.e(TAG, "터널 연결 실패", e)
            false
        }
    }

    fun bringDown() = synchronized(lock) {
        try {
            backend.setState(tunnel, Tunnel.State.DOWN, null)
        } catch (e: Exception) {
            Log.e(TAG, "터널 종료 실패", e)
        }
    }

    companion object {
        // bringUp/bringDown이 동시에 들어오지 않게 막는 락(백엔드 생성도 겸한다).
        private val lock = Any()

        @Volatile
        private var backendInstance: GoBackend? = null

        private fun sharedBackend(appContext: Context): GoBackend =
            backendInstance ?: synchronized(lock) {
                backendInstance ?: GoBackend(appContext).also { backendInstance = it }
            }

        private val sharedTunnel = object : Tunnel {
            override fun getName() = TUNNEL_NAME
            override fun onStateChange(newState: Tunnel.State) {
                Log.d(TAG, "tunnel state changed: $newState")
            }
        }

        private const val TUNNEL_NAME = "wirewol"
        private const val KEY_CONF = "config_text"
        private const val TAG = "WireGuardController"
    }
}
