package com.wirewol.remote

import android.graphics.BitmapFactory
import android.os.Bundle
import android.text.InputType
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import com.google.zxing.BinaryBitmap
import com.google.zxing.MultiFormatReader
import com.google.zxing.RGBLuminanceSource
import com.google.zxing.common.HybridBinarizer
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import org.json.JSONObject

/**
 * 자주 쓰지 않는 설정들을 모아둔 화면 — PC 등록(연결 정보 QR/수동 입력),
 * WireGuard 설정 스캔, 원격(공유기) WOL 설정, 전체 초기화. [MainActivity]의
 * 리모컨 화면을 버튼 몇 개로 단순하게 유지하기 위해 여기로 분리했다.
 *
 * 각 항목 아래에 현재 설정 여부를 보여주는 상태 문구를 둔다 — 어떤 게
 * 필수(연결 정보)고 어떤 게 선택(WireGuard/원격 WOL)인지, 그리고 지금
 * 실제로 저장되어 있는 값이 뭔지 한눈에 보이게 하기 위함.
 *
 * "PC 등록"은 원래 "연결 정보 스캔"과 "MAC 주소 직접 입력" 두 버튼이었다 —
 * 후자는 QR로 받은 MAC이 잘못된 어댑터를 가리킬 때만 쓰는 보정용이라 굳이
 * 따로 둘 필요가 없어서, QR 스캔(카메라/갤러리)과 함께 "직접 입력" 옵션
 * 하나로 합쳤다(직접 입력 창에서 host/port/token/mac을 전부 고칠 수 있어
 * 예전 MAC 전용 입력의 상위 호환이다).
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
        dispatchScanResult(scanned)
    }

    // 카메라 대신 이미 갖고 있는 QR 이미지(스크린샷, 전달받은 사진 등)를
    // 갤러리에서 골라 스캔한다 — 예를 들어 공유기 관리 화면을 캡처해둔
    // 스크린샷에서 바로 WireGuard 설정을 읽어올 수 있다.
    private val galleryImageLauncher = registerForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri == null) return@registerForActivityResult
        val decoded = try {
            decodeQrFromImage(uri)
        } catch (e: Exception) {
            null
        }
        if (decoded.isNullOrBlank()) {
            Toast.makeText(this, R.string.gallery_qr_not_found, Toast.LENGTH_SHORT).show()
            return@registerForActivityResult
        }
        dispatchScanResult(decoded)
    }

    private fun dispatchScanResult(scanned: String) {
        when (pendingScanTarget) {
            ScanTarget.PAIRING -> handlePairingScan(scanned)
            ScanTarget.WIREGUARD -> handleWireGuardScan(scanned)
        }
    }

    private fun decodeQrFromImage(uri: android.net.Uri): String? {
        val bitmap = contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it) } ?: return null
        val width = bitmap.width
        val height = bitmap.height
        val pixels = IntArray(width * height)
        bitmap.getPixels(pixels, 0, width, 0, 0, width, height)
        val source = RGBLuminanceSource(width, height, pixels)
        val binaryBitmap = BinaryBitmap(HybridBinarizer(source))
        return MultiFormatReader().decode(binaryBitmap).text
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

    // PAIRING(=PC 등록)은 QR이 없어도 host/port/token/mac을 직접 입력할 수
    // 있는 항목을 하나 더 둔다 — 예전에 별도 버튼이었던 "MAC 주소 직접 입력"을
    // 이 안으로 흡수한 것(전체 필드를 고칠 수 있으니 상위 호환).
    // WIREGUARD는 QR 입력만 지원한다(.conf 텍스트를 손으로 치는 건 비현실적).
    private fun launchScan(target: ScanTarget) {
        pendingScanTarget = target
        val items = mutableListOf(getString(R.string.scan_source_camera), getString(R.string.scan_source_gallery))
        if (target == ScanTarget.PAIRING) items.add(getString(R.string.scan_source_manual))
        AlertDialog.Builder(this)
            .setTitle(R.string.scan_source_title)
            .setItems(items.toTypedArray()) { _, which ->
                when (which) {
                    0 -> launchCameraScan()
                    1 -> galleryImageLauncher.launch("image/*")
                    else -> showManualPairingDialog()
                }
            }
            .show()
    }

    private fun launchCameraScan() {
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

    // QR 없이 PC 연결 정보를 직접 입력하는 창 — "PC 등록" 버튼의 세 번째
    // 옵션. 예전에 있던 "MAC 주소 직접 입력"(잘못 잡힌 랜카드 보정용)을
    // 이 창의 mac 필드 하나로 흡수했다. 기존 값이 있으면 채워둬서 일부
    // 필드만(예: MAC만) 고치는 용도로도 쓸 수 있다.
    private fun showManualPairingDialog() {
        val existing = pairingConfig.load()
        val padding = (24 * resources.displayMetrics.density).toInt()
        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(padding, padding / 2, padding, 0)
        }

        fun addField(hint: String, value: String?): EditText {
            val field = EditText(this)
            field.hint = hint
            field.setText(value)
            container.addView(field)
            return field
        }

        val hostInput = addField(getString(R.string.pairing_host_hint), existing?.host)
        val portInput = addField(getString(R.string.pairing_port_hint), existing?.port)
        val tokenInput = addField(getString(R.string.pairing_token_hint), existing?.token)
        val macInput = addField(getString(R.string.pairing_mac_hint), pairingConfig.loadMac())

        AlertDialog.Builder(this)
            .setTitle(R.string.pairing_manual_title)
            .setView(container)
            .setPositiveButton(R.string.pairing_manual_save) { _, _ ->
                val host = hostInput.text.toString().trim()
                val port = portInput.text.toString().trim()
                val token = tokenInput.text.toString().trim()
                val mac = macInput.text.toString().trim()
                if (host.isEmpty() || port.isEmpty() || token.isEmpty()) {
                    Toast.makeText(this, R.string.pairing_manual_incomplete, Toast.LENGTH_SHORT).show()
                    return@setPositiveButton
                }
                pairingConfig.save(host, port, token, mac)
                Toast.makeText(this, R.string.pairing_saved, Toast.LENGTH_SHORT).show()
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
