package com.wirewol.remote

import java.net.Inet4Address
import java.net.InetAddress
import java.net.NetworkInterface

/**
 * 터널이 집 PC로 가는 트래픽만 맡게 한다 — remote-file-manager_v(tunnelRoutes/splitConf)와
 * 같은 규칙. 예전처럼 공유기 QR의 AllowedIPs(보통 0.0.0.0/0)를 그대로 쓰면 폰의 모든
 * 통신이 집을 거치고, 집 안에서 터널이 잘못 켜졌거나(NAT 헤어핀 미지원) 핸드셰이크가
 * 막히면 인터넷 전체가 끊긴다. PC 대역만 맡기면 터널이 막혀도 영향은 PC 접속에만 있다.
 */
object SplitTunnel {
    private class LocalNet(val addr: Int, val mask: Int)

    private fun toInt(a: Inet4Address): Int = a.address.fold(0) { n, b -> (n shl 8) or (b.toInt() and 0xFF) }
    private fun maskOf(prefix: Int): Int = if (prefix <= 0) 0 else -1 shl (32 - prefix)
    private fun format(ip: Int) = "${(ip ushr 24) and 0xFF}.${(ip ushr 16) and 0xFF}.${(ip ushr 8) and 0xFF}.${ip and 0xFF}"

    private fun isPrivate(ip: Int): Boolean {
        val a = (ip ushr 24) and 0xFF
        val b = (ip ushr 16) and 0xFF
        return a == 10 || (a == 192 && b == 168) || (a == 172 && b in 16..31)
    }

    // 폰이 지금 붙어 있는 망(와이파이/모바일 데이터)의 IPv4 대역 — VPN(tun) 장치는 뺀다.
    private fun localNets(): List<LocalNet> = try {
        NetworkInterface.getNetworkInterfaces()?.toList().orEmpty()
            .filter { it.isUp && !it.isLoopback && !it.name.startsWith("tun") }
            .flatMap { ni ->
                ni.interfaceAddresses.mapNotNull { ia ->
                    (ia.address as? Inet4Address)?.let { LocalNet(toInt(it), maskOf(ia.networkPrefixLength.toInt())) }
                }
            }
    } catch (e: Exception) {
        emptyList()
    }

    /**
     * 터널이 맡을 주소(AllowedIPs) — PC의 사설 /24 대역(지정 브로드캐스트 WOL 포함). 폰이 이미
     * 그 대역 안에 있으면 빈 목록이다: 집 안이면 PC에 바로 닿고, 우연히 같은 대역을 쓰는 다른
     * 망이면 터널로 보내 봐야 그 망의 기기와 충돌만 한다 — 그래서 집 안에서는 PC가 꺼져 있어도
     * 터널을 켜지 않는다. 대역이 폰의 망과 겹치면 PC 주소(/32)만 넣는다. 해석 못 한 주소는
     * 건너뛴다. 이름 풀이가 있으니 백그라운드 스레드에서 호출할 것.
     */
    fun routesFor(hosts: List<String>): List<String> {
        val local = localNets()
        val routes = sortedSetOf<String>()
        for (host in hosts) {
            val addr = try {
                InetAddress.getAllByName(host).firstOrNull { it is Inet4Address } as Inet4Address?
            } catch (e: Exception) {
                null
            } ?: continue
            val ip = toInt(addr)
            if (local.any { ((ip xor it.addr) and it.mask) == 0 }) continue
            val net24 = ip and 0xFFFFFF00.toInt()
            val overlaps = local.any { (it.addr and 0xFFFFFF00.toInt()) == net24 }
            routes += if (isPrivate(ip) && !overlaps) "${format(net24)}/24" else "${format(ip)}/32"
        }
        return routes.toList()
    }

    /**
     * .conf 원문을 터널용으로 고친다(저장된 원본은 그대로) — 첫 [Peer]의 AllowedIPs를
     * allowedIps로 바꾸고 나머지 피어의 AllowedIPs는 뺀다. [Interface]의 DNS도 뺀다 — 터널
     * DNS(보통 집 공유기)를 쓰면 터널이 막혔을 때 이름 풀이 전체가 막힌다(없으면 안드로이드는
     * 원래 망의 DNS를 쓴다).
     */
    fun apply(conf: String, allowedIps: List<String>): String {
        var section = ""
        var peers = 0
        val out = mutableListOf<String>()
        for (line in conf.lines()) {
            val trimmed = line.trim()
            if (trimmed.startsWith("[") && trimmed.contains("]")) {
                section = trimmed.substring(1, trimmed.indexOf(']')).trim().lowercase()
                out += line
                if (section == "peer" && ++peers == 1) out += "AllowedIPs = ${allowedIps.joinToString(", ")}"
                continue
            }
            val key = trimmed.substringBefore('=').trim().lowercase()
            if (section == "peer" && key == "allowedips") continue
            if (section == "interface" && key == "dns") continue
            out += line
        }
        return out.joinToString("\n")
    }
}
