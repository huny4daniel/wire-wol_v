package com.wirewol.remote

import org.json.JSONObject
import java.security.SecureRandom
import java.util.Base64
import javax.crypto.AEADBadTagException
import javax.crypto.Cipher
import javax.crypto.Mac
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/**
 * 설정 전체(PC 등록/WireGuard/원격 WOL/자동 종료)를 비밀번호로 암호화한 파일
 * 하나로 내보내고 다시 불러온다. **wire-wol-pc_v(윈도우판 리모컨)의
 * `app/settings_backup.py`와 같은 형식**이라 어느 쪽에서 내보낸 파일이든 서로
 * 불러올 수 있다 — 형식이나 내용 필드를 바꾸면 양쪽을 함께 고칠 것.
 *
 * 파일(겉): {"format":"wirewol-settings","version":1,
 *   "kdf":{"name":"PBKDF2-HMAC-SHA256","iterations":N,"salt":b64},
 *   "cipher":{"name":"AES-256-GCM","nonce":b64},"data":b64(암호문+태그)}
 * 내용(속, UTF-8 JSON): {"pairing":{host,port,token,mac}|null,
 *   "wireguard_conf":str|null,"router_wol":{host,port,id,password}|null,
 *   "auto_shutdown":{"enabled":bool,"delay_minutes":int}}
 *
 * 공유기 인증서 지문(TOFU)은 담지 않는다 — 기기마다 첫 연결 때 새로 기억한다.
 * 예약된 종료 시각처럼 그 기기에서만 의미 있는 진행 상태도 담지 않는다.
 *
 * PBKDF2는 플랫폼 SecretKeyFactory 대신 HmacSHA256으로 직접 계산한다 — 안드로이드
 * 버전/제공자에 따라 비ASCII 비밀번호를 바이트로 바꾸는 방식이 달라질 수 있는데,
 * 여기선 항상 UTF-8로 고정해야 파이썬 쪽(hashlib.pbkdf2_hmac)과 같은 키가 나온다.
 */
object SettingsBackup {

    class InvalidFileException : Exception()
    class WrongPasswordException : Exception()

    data class Contents(
        val pairing: PairingConfig.Info?,
        val wireGuardConf: String?,
        val routerWol: RouterWol.Config?,
        val autoShutdownEnabled: Boolean,
        val autoShutdownDelayMinutes: Int,
    )

    fun collect(
        pairingConfig: PairingConfig,
        wireGuard: WireGuardController,
        routerWol: RouterWol,
        autoShutdown: AutoShutdownConfig,
    ) = Contents(
        pairing = pairingConfig.load(),
        wireGuardConf = wireGuard.loadConfigText(),
        routerWol = routerWol.loadConfig(),
        autoShutdownEnabled = autoShutdown.enabled,
        autoShutdownDelayMinutes = autoShutdown.delayMinutes,
    )

    // 불러온 내용으로 현재 설정을 통째로 바꾼다 — 파일에 없는 항목은 지운다
    // (내보낸 쪽과 똑같은 상태가 되도록).
    fun apply(
        contents: Contents,
        pairingConfig: PairingConfig,
        wireGuard: WireGuardController,
        routerWol: RouterWol,
        autoShutdown: AutoShutdownConfig,
    ) {
        val pairing = contents.pairing
        if (pairing != null) pairingConfig.save(pairing.host, pairing.port, pairing.token, pairing.mac) else pairingConfig.clear()
        val conf = contents.wireGuardConf
        if (conf != null) wireGuard.saveConfigText(conf) else wireGuard.clearConfig()
        val router = contents.routerWol
        if (router != null) routerWol.saveConfig(router) else routerWol.clearConfig()
        autoShutdown.enabled = contents.autoShutdownEnabled
        autoShutdown.delayMinutes = contents.autoShutdownDelayMinutes
    }

    // 키 유도(PBKDF2)가 수십만 번 반복되므로 반드시 백그라운드 스레드에서 호출할 것.
    fun export(contents: Contents, password: String): String {
        val plain = toJson(contents).toString().toByteArray(Charsets.UTF_8)
        val random = SecureRandom()
        val salt = ByteArray(SALT_BYTES).also { random.nextBytes(it) }
        val nonce = ByteArray(NONCE_BYTES).also { random.nextBytes(it) }
        val key = deriveKey(password, salt, ITERATIONS)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(TAG_BITS, nonce))
        val encrypted = cipher.doFinal(plain)
        return JSONObject()
            .put("format", FORMAT)
            .put("version", VERSION)
            .put("kdf", JSONObject().put("name", KDF_NAME).put("iterations", ITERATIONS).put("salt", b64(salt)))
            .put("cipher", JSONObject().put("name", CIPHER_NAME).put("nonce", b64(nonce)))
            .put("data", b64(encrypted))
            .toString(2)
    }

    // 백그라운드 스레드에서 호출할 것. 형식이 다르면 InvalidFileException,
    // 비밀번호가 틀리면(GCM 태그 불일치) WrongPasswordException.
    fun import(fileText: String, password: String): Contents {
        val envelope = try {
            JSONObject(fileText)
        } catch (e: Exception) {
            throw InvalidFileException()
        }
        if (envelope.optString("format") != FORMAT || envelope.optInt("version") != VERSION) throw InvalidFileException()
        val (salt, iterations, nonce, encrypted) = try {
            val kdf = envelope.getJSONObject("kdf")
            val cipher = envelope.getJSONObject("cipher")
            if (kdf.getString("name") != KDF_NAME || cipher.getString("name") != CIPHER_NAME) throw InvalidFileException()
            Quad(unb64(kdf.getString("salt")), kdf.getInt("iterations"), unb64(cipher.getString("nonce")), unb64(envelope.getString("data")))
        } catch (e: InvalidFileException) {
            throw e
        } catch (e: Exception) {
            throw InvalidFileException()
        }
        if (iterations !in 1..MAX_ITERATIONS) throw InvalidFileException()
        val key = deriveKey(password, salt, iterations)
        val plain = try {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(TAG_BITS, nonce))
            cipher.doFinal(encrypted)
        } catch (e: AEADBadTagException) {
            throw WrongPasswordException()
        } catch (e: Exception) {
            throw InvalidFileException()
        }
        return try {
            fromJson(JSONObject(String(plain, Charsets.UTF_8)))
        } catch (e: Exception) {
            throw InvalidFileException()
        }
    }

    private data class Quad(val salt: ByteArray, val iterations: Int, val nonce: ByteArray, val data: ByteArray)

    private fun toJson(c: Contents): JSONObject = JSONObject()
        .put("pairing", c.pairing?.let {
            JSONObject().put("host", it.host).put("port", it.port).put("token", it.token).put("mac", it.mac)
        } ?: JSONObject.NULL)
        .put("wireguard_conf", c.wireGuardConf ?: JSONObject.NULL)
        .put("router_wol", c.routerWol?.let {
            JSONObject().put("host", it.host).put("port", it.port).put("id", it.id).put("password", it.password)
        } ?: JSONObject.NULL)
        .put("auto_shutdown", JSONObject()
            .put("enabled", c.autoShutdownEnabled)
            .put("delay_minutes", c.autoShutdownDelayMinutes))

    // port는 문자열/숫자 어느 쪽이 와도 받아준다(페어링 QR은 숫자로 담는다).
    private fun fromJson(json: JSONObject): Contents {
        val pairing = json.optJSONObject("pairing")?.let {
            val host = it.getString("host")
            val port = it.get("port").toString()
            val token = it.getString("token")
            if (host.isBlank() || port.isBlank() || token.isBlank()) null
            else PairingConfig.Info(host, port, token, it.optString("mac", ""))
        }
        val conf = if (json.isNull("wireguard_conf")) null else json.optString("wireguard_conf").ifBlank { null }
        val router = json.optJSONObject("router_wol")?.let {
            RouterWol.Config(it.getString("host"), it.get("port").toString(), it.getString("id"), it.getString("password"))
        }
        val auto = json.optJSONObject("auto_shutdown")
        val delay = auto?.optInt("delay_minutes", 0) ?: 0
        return Contents(
            pairing = pairing,
            wireGuardConf = conf,
            routerWol = router,
            autoShutdownEnabled = auto?.optBoolean("enabled", false) ?: false,
            autoShutdownDelayMinutes = if (delay in 1..MAX_DELAY_MINUTES) delay else AutoShutdownConfig.DEFAULT_DELAY_MINUTES,
        )
    }

    private fun deriveKey(password: String, salt: ByteArray, iterations: Int): ByteArray {
        // 출력 길이(32바이트)가 HMAC-SHA256 출력과 같아 PBKDF2 블록 하나(i=1)로 끝난다.
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(password.toByteArray(Charsets.UTF_8), "HmacSHA256"))
        mac.update(salt)
        var u = mac.doFinal(byteArrayOf(0, 0, 0, 1))
        val result = u.copyOf()
        for (i in 1 until iterations) {
            u = mac.doFinal(u)
            for (j in result.indices) result[j] = (result[j].toInt() xor u[j].toInt()).toByte()
        }
        return result
    }

    private fun b64(bytes: ByteArray): String = Base64.getEncoder().encodeToString(bytes)
    private fun unb64(text: String): ByteArray = Base64.getDecoder().decode(text)

    const val FILE_NAME = "wirewol_settings.json"
    private const val FORMAT = "wirewol-settings"
    private const val VERSION = 1
    private const val KDF_NAME = "PBKDF2-HMAC-SHA256"
    private const val CIPHER_NAME = "AES-256-GCM"
    private const val ITERATIONS = 200_000
    private const val MAX_ITERATIONS = 10_000_000
    private const val SALT_BYTES = 16
    private const val NONCE_BYTES = 12
    private const val TAG_BITS = 128
    private const val MAX_DELAY_MINUTES = 23 * 60 + 59
}
