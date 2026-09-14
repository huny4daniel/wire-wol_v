package com.wirewol.remote

import android.graphics.BitmapFactory
import android.os.Bundle
import android.text.InputType
import android.widget.Button
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import com.google.zxing.BarcodeFormat
import com.google.zxing.BinaryBitmap
import com.google.zxing.MultiFormatReader
import com.google.zxing.RGBLuminanceSource
import com.google.zxing.common.HybridBinarizer
import com.journeyapps.barcodescanner.BarcodeEncoder
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
        findViewById<Button>(R.id.showPairingQrButton).setOnClickListener { showPairingQrDialog() }
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
        AlertDialog.Builder(this)
            .setTitle(R.string.scan_source_title)
            .setItems(arrayOf(getString(R.string.scan_source_camera), getString(R.string.scan_source_gallery))) { _, which ->
                if (which == 0) launchCameraScan() else galleryImageLauncher.launch("image/*")
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

    // 이미 폰에 저장된 설정을 통째로 QR로 보여준다 — 컴퓨터용 클라이언트 앱을
    // 새로 설정할 때, PC 트레이나 공유기 QR을 다시 찾지 않고 폰 화면만 비춰서
    // 한 번에 페어링할 수 있게 한다. 연결 정보({host, port, token, mac})는 PC
    // 트레이 QR과 완전히 같은 스키마이고, 그 위에 WireGuard 설정/원격 WOL
    // 자격 증명이 있으면 선택적으로 덧붙인다 — 컴퓨터 클라이언트 쪽
    // `_apply_pairing_json`이 이 확장 필드까지 함께 읽는다.
    //
    // 원격 WOL은 공유기 관리자 아이디/비밀번호라 QR에 실리는 순간 노출
    // 위험이 커진다는 걸 사용자가 감수하고 요청한 것 — 신뢰할 수 있는
    // 화면에서만 띄우고 바로 닫도록 안내한다.
    private fun showPairingQrDialog() {
        val pairing = pairingConfig.load()
        if (pairing == null) {
            Toast.makeText(this, R.string.show_pairing_qr_missing, Toast.LENGTH_SHORT).show()
            return
        }
        val payload = JSONObject().apply {
            put("host", pairing.host)
            put("port", pairing.port.toIntOrNull() ?: pairing.port)
            put("token", pairing.token)
            put("mac", pairing.mac)
            wireGuard.loadConfigText()?.let { put("wireguard_conf", it) }
            routerWol.loadConfig()?.let { router ->
                put("router_wol", JSONObject().apply {
                    put("host", router.host)
                    put("port", router.port)
                    put("id", router.id)
                    put("password", router.password)
                })
            }
        }.toString()

        val size = (240 * resources.displayMetrics.density).toInt()
        val bitmap = BarcodeEncoder().encodeBitmap(payload, BarcodeFormat.QR_CODE, size, size)
        val padding = (16 * resources.displayMetrics.density).toInt()
        val imageView = ImageView(this).apply {
            setImageBitmap(bitmap)
            setPadding(padding, padding, padding, 0)
        }
        val warningText = TextView(this).apply {
            text = getString(R.string.show_pairing_qr_warning)
            setPadding(padding, padding / 2, padding, padding / 2)
        }
        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(imageView)
            addView(warningText)
        }

        AlertDialog.Builder(this)
            .setTitle(R.string.show_pairing_qr)
            .setView(container)
            .setPositiveButton(android.R.string.ok, null)
            .show()
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
