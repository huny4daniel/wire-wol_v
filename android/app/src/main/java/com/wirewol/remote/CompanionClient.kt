package com.wirewol.remote

import android.util.Log
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * WireWOL 윈도우 컴패니언(wirewol.pyw)의 최소 API를 호출한다 — 평범한 http
 * (같은 LAN 또는 WireGuard 터널로 도달 가능한 사설 주소이므로 TLS 없이도
 * 안전하다고 보고, RouterWol처럼 인증서 처리를 할 필요가 없다). 인증은 트레이
 * "연결 정보 보기" QR로 받은 고정 토큰을 매 요청 헤더에 싣는 것으로 충분하다
 * (브라우저 세션이 아니라 앱이 직접 호출하는 단순 원격 명령이라 쿠키가 필요
 * 없다).
 */
class CompanionClient {

    data class Config(val host: String, val port: String, val token: String)

    sealed class Result {
        data class Success(val mac: String) : Result()
        data class Failure(val message: String) : Result()
    }

    private val client = OkHttpClient.Builder()
        .connectTimeout(4, TimeUnit.SECONDS)
        .readTimeout(4, TimeUnit.SECONDS)
        .build()

    private fun baseUrl(config: Config) = "http://${config.host}:${config.port}"

    fun ping(config: Config): Result {
        return try {
            val request = Request.Builder()
                .url("${baseUrl(config)}/api/ping")
                .header(TOKEN_HEADER, config.token)
                .get()
                .build()
            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) return Result.Failure("HTTP ${response.code}")
                val json = JSONObject(response.body?.string().orEmpty())
                Result.Success(json.optString("mac"))
            }
        } catch (e: Exception) {
            Log.e(TAG, "ping failed", e)
            Result.Failure(e.message ?: "연결할 수 없습니다")
        }
    }

    // delaySeconds가 null이면 컴패니언의 기본 지연(즉시 끄기 버튼용)을 그대로
    // 쓰고, 값을 주면 그만큼 뒤에 종료되도록 예약한다(종료 예약 기능용).
    fun shutdown(config: Config, delaySeconds: Int? = null): Result {
        val body = if (delaySeconds != null) {
            JSONObject().put("delay_seconds", delaySeconds).toString()
                .toRequestBody("application/json".toMediaType())
        } else {
            ByteArray(0).toRequestBody(null)
        }
        return postCommand(config, "/api/shutdown", body)
    }

    fun cancelShutdown(config: Config): Result =
        postCommand(config, "/api/shutdown/cancel", ByteArray(0).toRequestBody(null))

    fun enableAutologin(config: Config, username: String, password: String, domain: String): Result {
        val body = JSONObject().apply {
            put("enable", true)
            put("username", username)
            put("password", password)
            if (domain.isNotBlank()) put("domain", domain)
        }.toString().toRequestBody("application/json".toMediaType())
        return postCommand(config, "/api/autologin", body)
    }

    fun disableAutologin(config: Config): Result {
        val body = JSONObject().put("enable", false).toString().toRequestBody("application/json".toMediaType())
        return postCommand(config, "/api/autologin", body)
    }

    private fun postCommand(config: Config, path: String, body: okhttp3.RequestBody): Result {
        return try {
            val request = Request.Builder()
                .url("${baseUrl(config)}$path")
                .header(TOKEN_HEADER, config.token)
                .post(body)
                .build()
            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) {
                    val message = try {
                        JSONObject(response.body?.string().orEmpty()).optString("error")
                    } catch (e: Exception) {
                        ""
                    }
                    return Result.Failure(message.ifBlank { "HTTP ${response.code}" })
                }
                Result.Success("")
            }
        } catch (e: Exception) {
            Log.e(TAG, "command $path failed", e)
            Result.Failure(e.message ?: "연결할 수 없습니다")
        }
    }

    companion object {
        private const val TOKEN_HEADER = "X-WireWOL-Token"
        private const val TAG = "CompanionClient"
    }
}
