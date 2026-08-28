package com.wirewol.remote

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/**
 * 부팅 시 자동 로그인(Autologon) 설정 여부만 로컬에 기억해둔다 — 비밀번호는
 * 켤 때 한 번 컴패니언 서버로 보내 Windows LSA Secret에 저장시키고 나면 앱이
 * 다시 쓸 일이 없으므로(껐다 켜려면 다시 입력받는다) 폰에는 저장하지 않는다.
 * 사용자 이름은 설정 화면에 "지금 어떤 계정으로 자동 로그인되게 해뒀는지"
 * 보여주기 위한 표시용으로만 저장한다.
 */
class AutoLoginConfig(context: Context) {

    private val appContext = context.applicationContext

    private val prefs by lazy {
        val masterKey = MasterKey.Builder(appContext)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            appContext,
            "autologin_prefs",
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )
    }

    fun saveEnabled(username: String) {
        prefs.edit().putBoolean(KEY_ENABLED, true).putString(KEY_USERNAME, username).apply()
    }

    fun saveDisabled() {
        prefs.edit().putBoolean(KEY_ENABLED, false).remove(KEY_USERNAME).apply()
    }

    fun isEnabled(): Boolean = prefs.getBoolean(KEY_ENABLED, false)

    fun loadUsername(): String = prefs.getString(KEY_USERNAME, "") ?: ""

    companion object {
        private const val KEY_ENABLED = "enabled"
        private const val KEY_USERNAME = "username"
    }
}
