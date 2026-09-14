package com.wirewol.remote

import java.net.InetSocketAddress
import java.net.Socket

/**
 * "지금 집 안인가 밖인가"를 SSID 비교 대신 실제 도달 여부로 판단한다 —
 * WireGuard 없이 컴패니언 포트로 짧게 TCP 연결을 찔러봐서 열리면 같은
 * LAN(또는 이미 다른 경로로 도달 가능한 상태)이라 "내부", 실패하면 "외부"로
 * 본다. SSID 비교는 위치 권한이 필요하고 같은 이름의 다른 네트워크에도
 * 속을 수 있는데, 이 방식은 권한이 필요 없고 "실제로 닿는가"만 보므로 더
 * 정확하다. 반드시 백그라운드 스레드에서 호출할 것(네트워크 I/O).
 */
object NetworkProbe {
    private const val TIMEOUT_MS = 1_500

    fun isReachableDirectly(host: String, port: Int): Boolean {
        if (port <= 0) return false
        return try {
            Socket().use { socket ->
                socket.connect(InetSocketAddress(host, port), TIMEOUT_MS)
                true
            }
        } catch (e: Exception) {
            false
        }
    }
}
