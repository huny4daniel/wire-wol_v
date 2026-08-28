package com.wirewol.remote

import android.app.Application
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.ProcessLifecycleOwner

/**
 * 앱 전체(모든 액티비티)가 백그라운드로 가면 와이어가드를 끄고, 앱이 완전히
 * 종료됐다가 새로 켜진 게 아니라 백그라운드에 살아있다가 다시 포그라운드로
 * 돌아오면 되살린다 — 단, 백그라운드로 가기 직전에 실제로 켜져 있던 경우에만
 * 되살리고, 이미 꺼져 있었거나 켠 적이 없으면 그대로 꺼진 채 둔다.
 *
 * MainActivity/SettingsActivity 각각의 onStart/onStop이 아니라
 * ProcessLifecycleOwner를 쓰는 이유는, 두 액티비티 사이를 전환할 때(예: 설정
 * 화면 진입)는 앱을 나간 게 아니므로 여기서 반응하면 안 되기 때문이다.
 */
class WireWolApplication : Application(), DefaultLifecycleObserver {

    private val wireGuard by lazy { WireGuardController(this) }
    private var suspendedByBackground = false

    override fun onCreate() {
        super<Application>.onCreate()
        ProcessLifecycleOwner.get().lifecycle.addObserver(this)
    }

    override fun onStop(owner: LifecycleOwner) {
        if (wireGuard.hasConfig() && wireGuard.isUp()) {
            suspendedByBackground = true
            Thread { wireGuard.bringDown() }.start()
        }
    }

    override fun onStart(owner: LifecycleOwner) {
        if (suspendedByBackground) {
            suspendedByBackground = false
            Thread { wireGuard.bringUp() }.start()
        }
    }
}
