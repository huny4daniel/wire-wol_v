package com.wirewol.remote

import android.content.Intent
import android.net.VpnService
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.snackbar.Snackbar

/**
 * WireWOL 리모컨 화면 — 버튼 네 개(PC 켜기/PC 끄기/와이어가드 켜기/와이어가드
 * 끄기)와 상태 표시가 전부인 화면. 연결 정보/WireGuard 설정 스캔, MAC 수동
 * 입력, 원격 WOL 설정, 초기화처럼 자주 쓰지 않는 것들은 [SettingsActivity]로
 * 분리했다.
 *
 * 와이어가드는 하나의 토글 버튼이 아니라 PC 켜기/끄기처럼 켜기·끄기 버튼을
 * 따로 둔다 — 리모컨의 다른 버튼들과 마찬가지로 사용자가 누른 상태를 그대로
 * 유지한다(onStart/onStop에 걸어 자동으로 올리고 내리지 않음).
 */
class MainActivity : AppCompatActivity() {

    private lateinit var rootView: View
    private lateinit var statusHostText: TextView
    private lateinit var statusMacText: TextView
    private lateinit var statusWireGuardText: TextView
    private lateinit var versionText: TextView

    private lateinit var pairingConfig: PairingConfig
    private lateinit var routerWol: RouterWol
    private lateinit var wireGuard: WireGuardController
    private val companionClient = CompanionClient()
    private val handler = Handler(Looper.getMainLooper())

    private val vpnPermissionLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        Thread {
            val ok = wireGuard.bringUp()
            handler.post {
                if (!ok) Toast.makeText(this, R.string.wireguard_failed, Toast.LENGTH_LONG).show()
                updateStatus()
            }
        }.start()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        pairingConfig = PairingConfig(this)
        routerWol = RouterWol(this)
        wireGuard = WireGuardController(this)

        rootView = findViewById(R.id.root)
        statusHostText = findViewById(R.id.statusHostText)
        statusMacText = findViewById(R.id.statusMacText)
        statusWireGuardText = findViewById(R.id.statusWireGuardText)
        versionText = findViewById(R.id.versionText)
        versionText.text = getString(R.string.version_label, BuildConfig.VERSION_NAME)

        findViewById<Button>(R.id.powerOnButton).setOnClickListener { onPowerOnClicked() }
        findViewById<Button>(R.id.powerOffButton).setOnClickListener { onPowerOffClicked() }
        findViewById<Button>(R.id.wireGuardOnButton).setOnClickListener { onWireGuardOnClicked() }
        findViewById<Button>(R.id.wireGuardOffButton).setOnClickListener { onWireGuardOffClicked() }
        findViewById<Button>(R.id.settingsButton).setOnClickListener {
            startActivity(Intent(this, SettingsActivity::class.java))
        }
    }

    override fun onResume() {
        super.onResume()
        // 설정 화면에서 연결 정보/WireGuard/MAC을 바꾸고 돌아왔을 수 있으니
        // 매번 다시 읽는다.
        updateStatus()
    }

    private fun updateStatus() {
        val pairing = pairingConfig.load()
        statusHostText.text = if (pairing != null) {
            getString(R.string.status_target, pairing.host, pairing.port)
        } else {
            getString(R.string.status_target_missing)
        }

        val mac = pairingConfig.loadMac()
        statusMacText.text = if (mac.isNotBlank()) getString(R.string.status_mac, mac) else getString(R.string.status_mac_missing)

        statusWireGuardText.text = when {
            !wireGuard.hasConfig() -> getString(R.string.status_wireguard_missing)
            wireGuard.isUp() -> getString(R.string.status_wireguard_up)
            else -> getString(R.string.status_wireguard_down)
        }
    }

    // PC가 꺼져있어도 눌러서 깨울 수 있도록 매직 패킷을 보낸다(Wake-on-LAN).
    // 폰이 PC와 같은 LAN(와이파이)에 있거나, WireGuard로 붙어있어 브로드캐스트가
    // 도달할 수 있어야 한다.
    private fun onPowerOnClicked() {
        val mac = pairingConfig.loadMac()
        if (mac.isBlank()) {
            Toast.makeText(this, R.string.mac_missing_for_wake, Toast.LENGTH_LONG).show()
            return
        }
        sendWakeOnLan(mac)
        Toast.makeText(this, R.string.wake_sent, Toast.LENGTH_SHORT).show()
        triggerRemoteWakeIfConfigured(mac)
    }

    private fun sendWakeOnLan(mac: String) {
        Thread {
            try {
                val macBytes = mac.split(Regex("[:\\-]")).map { it.toInt(16).toByte() }.toByteArray()
                require(macBytes.size == 6)
                val packet = ByteArray(6 + 16 * 6)
                for (i in 0 until 6) packet[i] = 0xFF.toByte()
                for (i in 6 until packet.size step 6) macBytes.copyInto(packet, i)
                val socket = java.net.DatagramSocket()
                socket.broadcast = true
                val address = java.net.InetAddress.getByName("255.255.255.255")
                socket.send(java.net.DatagramPacket(packet, packet.size, address, 9))
                socket.close()
            } catch (e: Exception) {
                android.util.Log.e("WireWOL", "매직 패킷 전송 실패", e)
            }
        }.start()
    }

    private fun triggerRemoteWakeIfConfigured(mac: String) {
        val config = routerWol.loadConfig() ?: return
        Thread {
            val result = routerWol.triggerRemoteWake(config, mac)
            handler.post {
                when (result) {
                    is RouterWol.Result.Success ->
                        Toast.makeText(this, R.string.router_wol_sent, Toast.LENGTH_SHORT).show()
                    is RouterWol.Result.Failure ->
                        Toast.makeText(this, getString(R.string.router_wol_failed, result.message), Toast.LENGTH_LONG).show()
                }
            }
        }.start()
    }

    // PC 끄기 — WireWOL 컴패니언(wirewol.pyw)에 종료 명령을 보낸다. 서버가
    // 곧바로 끄지 않고 10초 지연 후 종료를 예약하므로, 그사이 Snackbar의
    // "취소" 액션으로 되돌릴 수 있다(오조작으로 저장 안 된 작업이 날아가는
    // 것을 막기 위한 안전장치 — mobile-hub-viewer_v의 종료 API와 동일한 이유).
    private fun onPowerOffClicked() {
        val pairing = pairingConfig.load()
        if (pairing == null) {
            Toast.makeText(this, R.string.pairing_missing, Toast.LENGTH_LONG).show()
            return
        }
        AlertDialog.Builder(this)
            .setTitle(R.string.shutdown_confirm_title)
            .setMessage(R.string.shutdown_confirm_message)
            .setPositiveButton(R.string.shutdown_confirm_ok) { _, _ -> requestShutdown(pairing) }
            .setNegativeButton(R.string.cancel, null)
            .show()
    }

    private fun requestShutdown(pairing: PairingConfig.Info) {
        Toast.makeText(this, R.string.shutdown_requesting, Toast.LENGTH_SHORT).show()
        val config = CompanionClient.Config(pairing.host, pairing.port, pairing.token)
        Thread {
            val result = companionClient.shutdown(config)
            handler.post {
                when (result) {
                    is CompanionClient.Result.Success -> showShutdownScheduledSnackbar(config)
                    is CompanionClient.Result.Failure ->
                        Toast.makeText(this, getString(R.string.shutdown_failed, result.message), Toast.LENGTH_LONG).show()
                }
            }
        }.start()
    }

    private fun showShutdownScheduledSnackbar(config: CompanionClient.Config) {
        Snackbar.make(rootView, R.string.shutdown_scheduled, 10_000)
            .setAction(R.string.cancel) {
                Thread {
                    val result = companionClient.cancelShutdown(config)
                    handler.post {
                        when (result) {
                            is CompanionClient.Result.Success ->
                                Toast.makeText(this, R.string.shutdown_cancelled, Toast.LENGTH_SHORT).show()
                            is CompanionClient.Result.Failure ->
                                Toast.makeText(this, getString(R.string.shutdown_cancel_failed, result.message), Toast.LENGTH_LONG).show()
                        }
                    }
                }.start()
            }
            .show()
    }

    private fun onWireGuardOnClicked() {
        if (!wireGuard.hasConfig()) {
            Toast.makeText(this, R.string.wireguard_missing, Toast.LENGTH_SHORT).show()
            return
        }
        if (wireGuard.isUp()) {
            updateStatus()
            return
        }
        Toast.makeText(this, R.string.wireguard_connecting, Toast.LENGTH_SHORT).show()
        val prepareIntent = VpnService.prepare(this)
        if (prepareIntent != null) {
            vpnPermissionLauncher.launch(prepareIntent)
        } else {
            Thread {
                val ok = wireGuard.bringUp()
                handler.post {
                    if (!ok) Toast.makeText(this, R.string.wireguard_failed, Toast.LENGTH_LONG).show()
                    updateStatus()
                }
            }.start()
        }
    }

    private fun onWireGuardOffClicked() {
        if (!wireGuard.hasConfig() || !wireGuard.isUp()) {
            updateStatus()
            return
        }
        Thread {
            wireGuard.bringDown()
            handler.post { updateStatus() }
        }.start()
    }
}
