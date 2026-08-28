package com.wirewol.remote

import android.os.Bundle
import android.text.InputType
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import org.json.JSONObject

/**
 * 자주 쓰지 않는 설정들을 모아둔 화면 — 연결 정보/WireGuard 설정 스캔, MAC
 * 수동 입력, 원격(공유기) WOL 설정, 전체 초기화. [MainActivity]의 리모컨
 * 화면을 버튼 몇 개로 단순하게 유지하기 위해 여기로 분리했다.
 *
 * 각 항목 아래에 현재 설정 여부를 보여주는 상태 문구를 둔다 — 어떤 게
 * 필수(연결 정보)고 어떤 게 선택(WireGuard/원격 WOL)인지, 그리고 지금
 * 실제로 저장되어 있는 값이 뭔지 한눈에 보이게 하기 위함.
 *
 * 참고: 연결 정보 QR을 스캔하면 MAC 주소도 함께 저장되므로(PC 트레이가 QR에
 * 미리 담아 보냄) "MAC 주소 직접 입력"은 필수 단계가 아니라, 여러 랜카드가
 * 있어 잘못된 어댑터가 잡혔을 때만 쓰는 보정용이다.
 */
class SettingsActivity : AppCompatActivity() {

    private lateinit var pairingConfig: PairingConfig
    private lateinit var routerWol: RouterWol
    private lateinit var wireGuard: WireGuardController

    private lateinit var scanPairingStatus: TextView
    private lateinit var editMacStatus: TextView
    private lateinit var scanWireGuardStatus: TextView
    private lateinit var routerWolStatus: TextView

    private enum class ScanTarget { PAIRING, WIREGUARD }
    private var pendingScanTarget = ScanTarget.PAIRING

    private val qrScanLauncher = registerForActivityResult(ScanContract()) { result ->
        val scanned = result.contents
        if (scanned.isNullOrBlank()) return@registerForActivityResult
        when (pendingScanTarget) {
            ScanTarget.PAIRING -> handlePairingScan(scanned)
            ScanTarget.WIREGUARD -> handleWireGuardScan(scanned)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_settings)

        pairingConfig = PairingConfig(this)
        routerWol = RouterWol(this)
        wireGuard = WireGuardController(this)

        scanPairingStatus = findViewById(R.id.scanPairingStatus)
        editMacStatus = findViewById(R.id.editMacStatus)
        scanWireGuardStatus = findViewById(R.id.scanWireGuardStatus)
        routerWolStatus = findViewById(R.id.routerWolStatus)

        findViewById<Button>(R.id.backButton).setOnClickListener { finish() }
        findViewById<Button>(R.id.scanPairingButton).setOnClickListener { launchScan(ScanTarget.PAIRING) }
        findViewById<Button>(R.id.scanWireGuardButton).setOnClickListener { launchScan(ScanTarget.WIREGUARD) }
        findViewById<Button>(R.id.editMacButton).setOnClickListener { showEditMacDialog() }
        findViewById<Button>(R.id.routerWolSettingsButton).setOnClickListener { showRouterWolSettingsDialog() }
        findViewById<Button>(R.id.clearAllButton).setOnClickListener { showClearAllDialog() }

        refreshStatuses()
    }

    override fun onResume() {
        super.onResume()
        // QR 스캐너 화면에서 돌아왔을 때도 최신 상태를 반영한다.
        refreshStatuses()
    }

    private fun refreshStatuses() {
        val pairing = pairingConfig.load()
        scanPairingStatus.text = if (pairing != null) {
            getString(R.string.settings_status_pairing_set, pairing.host, pairing.port)
        } else {
            getString(R.string.settings_status_pairing_missing)
        }

        val mac = pairingConfig.loadMac()
        editMacStatus.text = if (mac.isNotBlank()) {
            getString(R.string.settings_status_mac_set, mac)
        } else {
            getString(R.string.settings_status_mac_missing)
        }

        scanWireGuardStatus.text = if (wireGuard.hasConfig()) {
            getString(R.string.settings_status_wireguard_set)
        } else {
            getString(R.string.settings_status_wireguard_missing)
        }

        val router = routerWol.loadConfig()
        routerWolStatus.text = if (router != null) {
            getString(R.string.settings_status_router_wol_set, router.host)
        } else {
            getString(R.string.settings_status_router_wol_missing)
        }
    }

    private fun launchScan(target: ScanTarget) {
        pendingScanTarget = target
        val options = ScanOptions()
            .setDesiredBarcodeFormats(ScanOptions.QR_CODE)
            .setPrompt(getString(R.string.scan_qr_prompt))
            .setBeepEnabled(false)
            .setOrientationLocked(false)
        qrScanLauncher.launch(options)
    }

    // PC 트레이의 "연결 정보 보기" QR은 {"host","port","token","mac"} 형태의
    // JSON 텍스트를 담고 있다(wirewol.pyw의 app/tray.py._pairing_payload와 짝).
    private fun handlePairingScan(scanned: String) {
        try {
            val json = JSONObject(scanned)
            val host = json.getString("host")
            val port = json.getInt("port").toString()
            val token = json.getString("token")
            val mac = json.optString("mac", "")
            pairingConfig.save(host, port, token, mac)
            Toast.makeText(this, R.string.pairing_saved, Toast.LENGTH_SHORT).show()
            refreshStatuses()
        } catch (e: Exception) {
            Toast.makeText(this, R.string.pairing_invalid, Toast.LENGTH_SHORT).show()
        }
    }

    // WireGuard 설정 QR(공유기/공식 앱이 만든 것)은 표준 .conf 텍스트가 그대로
    // 들어있어 [Interface]로 시작하는지로 구분한다.
    private fun handleWireGuardScan(scanned: String) {
        if (!scanned.trimStart().startsWith("[Interface]")) {
            Toast.makeText(this, R.string.wireguard_qr_invalid, Toast.LENGTH_SHORT).show()
            return
        }
        wireGuard.saveConfigText(scanned)
        Toast.makeText(this, R.string.wireguard_saved, Toast.LENGTH_SHORT).show()
        refreshStatuses()
    }

    // 공유기 관리자 계정/주소를 입력받는 간단한 설정창 — 별도 화면을 만들 정도로
    // 자주 쓰는 기능이 아니라 다이얼로그로 충분하다고 판단.
    private fun showRouterWolSettingsDialog() {
        val existing = routerWol.loadConfig()
        val padding = (24 * resources.displayMetrics.density).toInt()
        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(padding, padding / 2, padding, 0)
        }

        fun addField(hint: String, value: String?, isPassword: Boolean = false): EditText {
            val field = EditText(this)
            field.hint = hint
            field.setText(value)
            if (isPassword) {
                field.inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            }
            container.addView(field)
            return field
        }

        val hostInput = addField(getString(R.string.router_wol_host_hint), existing?.host)
        val portInput = addField(getString(R.string.router_wol_port_hint), existing?.port ?: "443")
        val idInput = addField(getString(R.string.router_wol_id_hint), existing?.id)
        val pwInput = addField(getString(R.string.router_wol_pw_hint), existing?.password, isPassword = true)

        AlertDialog.Builder(this)
            .setTitle(R.string.router_wol_settings_title)
            .setMessage(R.string.router_wol_settings_desc)
            .setView(container)
            .setPositiveButton(R.string.router_wol_save) { _, _ ->
                val host = hostInput.text.toString().trim()
                val port = portInput.text.toString().trim()
                val id = idInput.text.toString().trim()
                val pw = pwInput.text.toString()
                if (host.isEmpty() || port.isEmpty() || id.isEmpty() || pw.isEmpty()) {
                    Toast.makeText(this, R.string.router_wol_incomplete, Toast.LENGTH_SHORT).show()
                    return@setPositiveButton
                }
                routerWol.saveConfig(RouterWol.Config(host, port, id, pw))
                Toast.makeText(this, R.string.router_wol_saved, Toast.LENGTH_SHORT).show()
                refreshStatuses()
            }
            .setNeutralButton(R.string.router_wol_clear) { _, _ ->
                routerWol.clearConfig()
                Toast.makeText(this, R.string.router_wol_cleared, Toast.LENGTH_SHORT).show()
                refreshStatuses()
            }
            .setNegativeButton(R.string.cancel, null)
            .show()
    }

    // 페어링 QR로 받은 MAC이 잘못된 어댑터를 가리키는 경우(PC에 여러 랜카드가
    // 있는 등)를 대비한 수동 수정 창 — 정상적인 경우엔 쓸 필요가 없다.
    private fun showEditMacDialog() {
        val padding = (24 * resources.displayMetrics.density).toInt()
        val field = EditText(this).apply {
            hint = getString(R.string.edit_mac_hint)
            setText(pairingConfig.loadMac())
        }
        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(padding, padding / 2, padding, 0)
            addView(field)
        }

        AlertDialog.Builder(this)
            .setTitle(R.string.edit_mac_title)
            .setView(container)
            .setPositiveButton(R.string.edit_mac_save) { _, _ ->
                pairingConfig.saveMac(field.text.toString().trim())
                Toast.makeText(this, R.string.mac_saved, Toast.LENGTH_SHORT).show()
                refreshStatuses()
            }
            .setNegativeButton(R.string.cancel, null)
            .show()
    }

    private fun showClearAllDialog() {
        AlertDialog.Builder(this)
            .setTitle(R.string.clear_all_title)
            .setMessage(R.string.clear_all_message)
            .setPositiveButton(R.string.clear_all_ok) { _, _ ->
                pairingConfig.clear()
                wireGuard.clearConfig()
                routerWol.clearConfig()
                Toast.makeText(this, R.string.clear_all_done, Toast.LENGTH_SHORT).show()
                refreshStatuses()
            }
            .setNegativeButton(R.string.cancel, null)
            .show()
    }
}
