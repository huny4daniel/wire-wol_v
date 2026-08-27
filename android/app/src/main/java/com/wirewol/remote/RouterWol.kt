package com.wirewol.remote

import android.content.Context
import android.util.Log
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import okhttp3.Cookie
import okhttp3.CookieJar
import okhttp3.HttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest
import java.security.SecureRandom
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

/**
 * 집 공유기(iptime 등)에 내장된 WOL 기능을 그 관리자 웹 API로 직접 호출한다
 * (mobile-hub-viewer_v의 android/RouterWol.kt를 그대로 옮겨 적은 것).
 *
 * 로컬 매직 패킷(UDP 브로드캐스트)은 PC가 오래 꺼져있으면 공유기의 ARP 캐시가
 * 만료돼 실패할 수 있는데, 공유기 자신에게 "네가 대신 브로드캐스트로 깨워줘"라고
 * 시키면 이 문제가 없다 — 또한 폰이 집 와이파이 밖에 있어도(공유기의 원격 관리
 * 포트가 열려있다면) 똑같이 작동해서, WireGuard 없이도 외부망에서 PC를 켜는
 * 방법이 된다.
 *
 * 공식 앱이 쓰는 문서화되지 않은 내부 API(로그인 → wol/signal)를 그대로
 * 재현한 것이라, 공유기 펌웨어가 업데이트되면 요청 형식이 바뀌어 깨질 수 있다.
 */
class RouterWol(context: Context) {

    private val appContext = context.applicationContext

    private val prefs by lazy {
        val masterKey = MasterKey.Builder(appContext)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            appContext,
            "router_wol_prefs",
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )
    }

    data class Config(val host: String, val port: String, val id: String, val password: String)

    sealed class Result {
        object Success : Result()
        data class Failure(val message: String) : Result()
    }

    fun saveConfig(config: Config) {
        prefs.edit()
            .putString(KEY_HOST, config.host)
            .putString(KEY_PORT, config.port)
            .putString(KEY_ID, config.id)
            .putString(KEY_PASSWORD, config.password)
            .apply()
    }

    fun loadConfig(): Config? {
        val host = prefs.getString(KEY_HOST, null)
        val port = prefs.getString(KEY_PORT, null)
        val id = prefs.getString(KEY_ID, null)
        val password = prefs.getString(KEY_PASSWORD, null)
        if (host.isNullOrBlank() || port.isNullOrBlank() || id.isNullOrBlank() || password.isNullOrBlank()) {
            return null
        }
        return Config(host, port, id, password)
    }

    fun clearConfig() {
        prefs.edit().clear().apply()
    }

    // 공유기가 자체 서명 인증서를 쓰므로 일반적인 CA 검증은 통과할 수 없다.
    // 대신 "신뢰 우선 사용"(TOFU) 방식으로 처리한다 — 최초 연결 때 인증서
    // 지문(SHA-256)을 저장해두고, 그다음부터는 그 지문과 정확히 일치할 때만
    // 통신을 허용한다.
    private fun buildClient(host: String): OkHttpClient {
        val fingerprintKey = "cert_fp_$host"
        val trustManager = object : X509TrustManager {
            override fun checkClientTrusted(chain: Array<out X509Certificate>, authType: String) {}
            override fun checkServerTrusted(chain: Array<out X509Certificate>, authType: String) {
                val cert = chain.firstOrNull() ?: throw CertificateException("공유기가 인증서를 제공하지 않았습니다")
                val digest = MessageDigest.getInstance("SHA-256").digest(cert.encoded)
                val fingerprint = digest.joinToString(":") { "%02X".format(it) }
                val pinned = prefs.getString(fingerprintKey, null)
                if (pinned == null) {
                    prefs.edit().putString(fingerprintKey, fingerprint).apply()
                } else if (pinned != fingerprint) {
                    throw CertificateException("공유기 인증서가 이전과 달라 신뢰할 수 없습니다(공유기를 교체했다면 원격 WOL 설정을 다시 저장해주세요)")
                }
            }

            override fun getAcceptedIssuers(): Array<X509Certificate> = arrayOf()
        }
        // "TLS"로 두면 기기가 TLS 1.3을 우선 협상하려 드는데, 이런 임베디드
        // 관리 웹서버는 TLS 1.3 처리가 불안정해 응답 없이 소켓만 끊어버리는
        // 경우가 있어 TLS 1.2로 고정한다.
        val sslContext = SSLContext.getInstance("TLSv1.2")
        sslContext.init(null, arrayOf<TrustManager>(trustManager), SecureRandom())

        val cookieJar = object : CookieJar {
            @Volatile private var savedCookies: List<Cookie> = emptyList()
            override fun saveFromResponse(url: HttpUrl, cookies: List<Cookie>) {
                if (cookies.isNotEmpty()) savedCookies = cookies
            }
            override fun loadForRequest(url: HttpUrl): List<Cookie> = savedCookies
        }

        return OkHttpClient.Builder()
            .sslSocketFactory(sslContext.socketFactory, trustManager)
            .hostnameVerifier { _, _ -> true }
            .protocols(listOf(okhttp3.Protocol.HTTP_1_1))
            .cookieJar(cookieJar)
            .connectTimeout(8, TimeUnit.SECONDS)
            .readTimeout(8, TimeUnit.SECONDS)
            .build()
    }

    private fun commonHeaders(builder: Request.Builder, host: String, port: String): Request.Builder {
        val origin = "https://$host:$port"
        return builder
            .header("User-Agent", "Mozilla/5.0 (Linux; Android) WireWOL")
            .header("Accept", "application/json, text/plain, */*")
            .header("Connection", "close")
            .header("Origin", origin)
            .header("Referer", "$origin/")
    }

    // 로그인 → wol/signal 순서로 실행한다. 네트워크 호출이 포함되어 있으니
    // 반드시 백그라운드 스레드에서 호출할 것.
    fun triggerRemoteWake(config: Config, mac: String): Result {
        val baseUrl = "https://${config.host}:${config.port}/cgi/service.cgi"
        val client = buildClient(config.host)
        return try {
            val loginBody = JSONObject().apply {
                put("method", "session/login")
                put("params", JSONObject().apply {
                    put("id", config.id)
                    put("pw", config.password)
                })
            }.toString().toRequestBody(JSON_MEDIA_TYPE)

            client.newCall(commonHeaders(Request.Builder().url(baseUrl), config.host, config.port).post(loginBody).build()).execute().use { response ->
                val bodyText = response.body?.string().orEmpty()
                if (!response.isSuccessful) {
                    return Result.Failure("공유기 로그인 요청 실패 (HTTP ${response.code})")
                }
                val json = JSONObject(bodyText)
                if (json.optString("result") != "done") {
                    return Result.Failure("공유기 로그인 실패 — ID/비밀번호를 확인해주세요")
                }
            }

            val wolBody = JSONObject().apply {
                put("method", "wol/signal")
                put("params", JSONArray().put(mac))
            }.toString().toRequestBody(JSON_MEDIA_TYPE)

            client.newCall(commonHeaders(Request.Builder().url(baseUrl), config.host, config.port).post(wolBody).build()).execute().use { response ->
                if (!response.isSuccessful) {
                    return Result.Failure("깨우기 요청 실패 (HTTP ${response.code})")
                }
            }
            Result.Success
        } catch (e: Exception) {
            Log.e(TAG, "triggerRemoteWake failed", e)
            val certCause = generateSequence(e as Throwable?) { it.cause }
                .firstOrNull { it is CertificateException }
            Result.Failure(certCause?.message ?: "공유기에 연결할 수 없습니다: ${e.message}")
        }
    }

    companion object {
        private const val KEY_HOST = "host"
        private const val KEY_PORT = "port"
        private const val KEY_ID = "id"
        private const val KEY_PASSWORD = "password"
        private val JSON_MEDIA_TYPE = "application/json".toMediaType()
        private const val TAG = "RouterWol"
    }
}
