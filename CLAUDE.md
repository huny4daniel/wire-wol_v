# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 개요

집에 있는 PC를 폰이나 다른 컴퓨터에서 리모컨처럼 켜고(Wake-on-LAN), 끄고(원격 종료), WireGuard VPN을 켰다 끌 수 있게 해주는 세 부분짜리 프로젝트다.

- **`android/`**: 실제로 사용자가 만지는 앱. 버튼 네 개(PC 켜기 / PC 끄기 / 와이어가드 켜기 / 와이어가드 끄기)가 전부인 단일 화면 리모컨 + 자주 안 쓰는 것들을 모은 별도 설정 화면.
- **`windows/`**: PC 켜기(WOL)는 매직 패킷을 폰이 직접 브로드캐스트하므로 PC 쪽에 아무 프로그램이 없어도 되지만, **PC 끄기는 PC가 뭔가 받아서 실행해줘야 하므로** 최소한의 상주 프로그램이 필요하다 — 그 역할을 하는 트레이 상주 프로그램.
- **`client/`**: 노트북 등 다른 컴퓨터에서 쓰는 리모컨(Windows 전용). android 앱과 같은 기능(PC 켜기/끄기, 와이어가드 켜기/끄기)을 제공하지만, "명령을 받는" `windows/`와 달리 이쪽은 android 앱처럼 "명령을 보내는" 쪽이다 — `windows/`와는 반대 역할이라 코드도 완전히 별개다.

이 프로젝트는 `mobile-hub-viewer_v`(같은 개발자의 다른 프로젝트)의 WireGuard 임베딩 코드와 WOL 코드, 그리고 `hub.pyw`의 3모드 실행 구조/자동 시작 등록 방식을 그대로 참고해 만들었지만, **완전히 독립된 프로젝트**다 — `mobile-hub-viewer_v`의 hub 서버가 떠 있을 필요가 전혀 없다.

## 실행

**Windows 컴패니언** (WOL 대상 PC에서 실행):
```
python windows/wirewol.pyw
```
의존성: `pip install -r windows/requirements.txt` (Flask, qrcode, Pillow, pystray, pywin32).

**Android 앱**: `android/`를 Android Studio로 열거나 `cd android && ./gradlew assembleDebug`(Windows는 `gradlew.bat`)로 빌드한다. compileSdk/targetSdk 35, minSdk 26, Kotlin + AGP 8.7.3 + Gradle 8.9 — `mobile-hub-viewer_v/android`와 동일한 툴체인.

**컴퓨터용 클라이언트** (다른 컴퓨터에서 실행):
```
python client/wirewol_client.pyw
```
의존성: `pip install -r client/requirements.txt` (PyQt5, requests, pywin32, opencv-python, pyzbar). WireGuard 켜기/끄기를 쓰려면 [공식 WireGuard for Windows 클라이언트](https://www.wireguard.com/install/)가 별도로 설치되어 있어야 한다.

## 아키텍처

### Windows 컴패니언 (`windows/`)
`wirewol.pyw`는 `mobile-hub-viewer_v`의 `hub.pyw`와 완전히 동일한 3모드 구조를 쓴다(`main()`의 `sys.argv` 분기, 각 모드는 서로 다른 이름의 뮤텍스로 중복 실행 방지):

- **인자 없음(`main_combined`)**: 더블클릭 실행 시 기본 동작 — 서버+트레이가 한 프로세스에서 같이 뜬다.
- **`--server`(`main_server`)**: 트레이 없이 서버만. 트레이의 "자동 시작 등록"이 작업 스케줄러에 이 모드로 등록해두면, **로그인 여부와 상관없이 컴퓨터가 켜지자마자** SYSTEM 계정으로 실행된다 — 그래야 아무도 로그인하지 않은 PC도 폰에서 원격 종료 명령을 받을 수 있다. 시작 시 `app/process_utils.py`가 PID를 `wirewol_server.pid`에 적어 트레이 프로세스가 나중에 이 프로세스를 찾아 끌 수 있게 한다.
- **`--tray`(`main_tray`)**: 트레이 아이콘만 — 로그인 시 시작프로그램으로 뜬다. 서버가 아직 안 떠 있으면(포트가 비어있으면) 이 프로세스 안에 즉석으로 내장 서버를 하나 띄운다.

"자동 시작 등록"(`app/tray.py`)이 SYSTEM 계정 부팅 작업(`schtasks /SC ONSTART /RU SYSTEM`)과 로그인 시 시작프로그램 바로가기를 동시에 등록하는 방식, UAC 승격(`_run_elevated_schtasks`), PID 파일 기반 원격 종료(`app/process_utils.py`)까지 전부 `mobile-hub-viewer_v/app/tray.py`·`app/process_utils.py`를 그대로 옮겨 적은 것이다 — **그쪽에서 이 패턴이 바뀌면(예: UAC 승격 방식 변경) 이쪽도 함께 확인할 것.**

PyInstaller로 빌드된(`frozen`) exe에서는 등록이 실제 exe 경로를 직접 가리키지 않고, `_write_launcher()`가 exe와 같은 폴더에 만들어두는 고정 경로의 VBScript(`wirewol_launcher.vbs`)를 가리킨다 — 이 런처가 실행될 때마다 같은 폴더에서 `WireWOL_v*.exe` 패턴에 맞는 파일 중 가장 최근에 수정된(최신 버전) 것을 찾아 인자를 그대로 넘겨 대신 실행한다. 릴리즈 exe 파일명 자체에 버전이 들어있어(`WireWOL_vX.Y.Z.exe`) 새 버전을 받을 때마다 파일명이 바뀌는데, 등록이 exe 경로를 직접 박아두면 그때마다 "자동 시작 등록"을 다시 눌러야 하는 문제가 생긴다 — mobile-hub-viewer_v의 `hub_launcher.vbs`와 동일한 해법을 그대로 적용했다(**그쪽 구현이 바뀌면 이쪽도 함께 확인할 것**).

`app/server.py`는 Flask 앱 하나로 최소한의 API만 제공한다. 브라우저 세션이 아니라 앱이 직접 호출하는 단순 명령이라 쿠키 기반 페어링 대신 **고정 토큰**(`X-WireWOL-Token` 헤더)으로 인증한다 — `before_request`에서 모든 요청에 대해 검사한다.
- `GET /api/ping`: 헬스체크 + `get_primary_mac()`(mobile-hub-viewer_v의 `app/routes/system.py`에서 그대로 옮긴, `getmac` CSV 파싱으로 Wi-Fi 어댑터 MAC을 우선 찾는 로직)로 알아낸 MAC을 같이 반환한다.
- `POST /api/shutdown`: `shutdown /s /f /t 10`(10초 지연 종료, `/f`로 실행 중인 앱 강제 종료 — 폰에서의 오조작이 곧바로 작업을 날리지 않도록).
- `POST /api/shutdown/cancel`: `shutdown /a`로 취소.

트레이 "연결 정보 보기"(`_pairing_payload`)는 `{"host","port","token","mac"}` 형태의 **JSON 텍스트**를 QR로 보여준다 — mobile-hub-viewer_v의 페어링 QR(URL 형식)과 다르게, 여기는 감쌀 웹앱이 없어 순수 데이터만 필요하기 때문이다. **이 JSON 스키마가 안드로이드 쪽 `PairingConfig`/`MainActivity.handlePairingScan`과의 계약이다 — 필드를 추가/변경하면 양쪽을 함께 고칠 것.**

### Android 앱 (`android/`)
WebView가 전혀 없는 순수 네이티브 단일 화면(`MainActivity`) — 감쌀 PWA가 없으니 mobile-hub-viewer_v의 android 앱과 달리 버튼 UI 자체가 화면의 전부다.

- **`WireGuardController.kt`**: mobile-hub-viewer_v의 `HubWireGuard.kt`를 그대로 옮긴 것 — WireGuard 공식 임베딩 라이브러리(`com.wireguard.android:tunnel`, GoBackend)로 별도 앱 없이 VPN을 붙였다 뗀다. 설정(.conf 텍스트, 공유기가 만들어준 QR을 스캔해서 얻음)은 암호화된 SharedPreferences에 저장.
- **`RouterWol.kt`**: mobile-hub-viewer_v와 동일 — 공유기(iptime 등)에 내장된 원격 WOL API를 문서화되지 않은 로그인→wol/signal 흐름으로 직접 호출한다(TOFU 인증서 고정). 집 밖에서 WireGuard 없이도 PC를 켤 수 있는 대안 경로.
- **`PairingConfig.kt`**: 이 프로젝트에서 새로 추가한 것 — Windows 컴패니언 QR에서 받은 host/port/token/mac을 암호화 저장한다. MAC은 PC의 `getmac` 결과를 그대로 받아오지만, 어댑터가 여러 개라 잘못 고른 경우를 위해 `saveMac()`으로 수동 덮어쓰기도 가능하다.
- **`CompanionClient.kt`**: 이 프로젝트에서 새로 추가한 것 — Windows 컴패니언의 `/api/ping`·`/api/shutdown`·`/api/shutdown/cancel`을 호출하는 얇은 OkHttp 클라이언트. RouterWol과 달리 TLS 인증서 처리가 없다(같은 LAN 또는 WireGuard 터널 안의 평범한 http로만 통신한다고 가정).
- **`MainActivity.kt`**: 버튼 4개(PC 켜기/PC 끄기/와이어가드 켜기/와이어가드 끄기) + 상태 카드(연결 대상, MAC, WireGuard 상태) + 설정 화면으로 가는 버튼 하나가 전부. **와이어가드는 토글 버튼 하나가 아니라 켜기/끄기 버튼을 따로 둔다** — 리모컨의 다른 버튼들처럼 사용자가 누른 상태를 그대로 유지하고(`onStart`/`onStop`에 걸어 자동으로 올리고 내리지 않음), mobile-hub-viewer_v의 android 앱과 달리 "화면을 보는 동안만 연결"이라는 전제 자체가 없다(감쌀 웹 콘텐츠가 없기 때문). PC 끄기는 확인 다이얼로그 → 컴패니언 API 호출 → 성공 시 10초짜리 Snackbar("취소" 액션 포함)로 진행한다.
- **`SettingsActivity.kt`**: 자주 안 쓰는 것들(연결 정보 스캔, MAC 수동 입력, WireGuard 설정 스캔, 원격 WOL 설정, 전체 초기화)을 모은 별도 화면 — `MainActivity`의 "설정" 버튼으로 진입한다. 각 항목 아래에 현재 설정 여부를 보여주는 상태 문구가 있다(`refreshStatuses()`) — 필수(연결 정보)와 선택(WireGuard/원격 WOL)을 구분해서 표시한다.

### 컴퓨터용 클라이언트 (`client/`)

Windows 전용 PyQt5 데스크톱 앱. `android/`가 하는 일을 그대로 옮긴 것이라 `MainActivity.kt`/`SettingsActivity.kt`의 버튼 구성·플로우와 최대한 대응시켰다 — 한쪽 동작을 바꾸면 다른 쪽도 확인할 것.

- **`app/config.py`**: 안드로이드의 EncryptedSharedPreferences에 대응 — Windows DPAPI(`win32crypt.CryptProtectData`/`CryptUnprotectData`, 같은 윈도우 계정으로 로그인해야 복호화됨)로 페어링 정보/원격 WOL 자격 증명/WireGuard `.conf`를 한 파일(`wirewol_client_secrets.dat`)에 암호화해 저장한다. 안드로이드처럼 굳이 파일을 나누지 않았다 — 어차피 같은 로컬 사용자 하나만 접근 가능해 격리 이점이 없다. 저장 위치는 프로그램 폴더가 아니라 `%LOCALAPPDATA%\WireWOL Client\`(사용자별 숨김 폴더) — exe를 옮기거나 재설치해도 설정이 남고, 탐색기에서 파일 존재 자체가 바로 눈에 띄지 않는다. 구버전(프로그램 폴더 저장)에서 올라온 파일은 처음 실행 시 자동으로 새 위치로 옮겨진다.
- **`app/wol.py`**: `MainActivity.kt`의 `sendWakeOnLan`과 동일 — 매직 패킷을 `255.255.255.255:9`로 브로드캐스트한다.
- **`app/router_wol.py`**: `RouterWol.kt`와 동일한 로그인→`wol/signal` 흐름, TOFU 인증서 고정(지문을 `ClientConfig`에 저장). OkHttp 대신 `http.client.HTTPSConnection`을 직접 써서 피어 인증서 원문을 확보한다 — `requests`로는 검증을 우회하면서 인증서 자체를 손에 넣기 까다롭다.
- **`app/wireguard_client.py`**: 안드로이드는 GoBackend를 앱에 내장하지만 Windows엔 그런 손쉬운 임베딩 라이브러리가 없다 — 대신 사용자가 이미 설치한 **공식 WireGuard for Windows 클라이언트**(`wireguard.exe`)의 터널 서비스 관리 기능을 빌린다. 켤 때마다 `.conf`를 임시 파일로 써서 `/installtunnelservice`(설치+기동을 동시에 함), 끌 때 `/uninstalltunnelservice`(중지+제거를 동시에 함)를 고정된 터널 이름(`wirewolclient`)으로 호출한다 — 설정이 바뀌었을 수 있으니 매번 새로 설치하는 편이 오래된 서비스가 남아 꼬이는 것보다 낫다. 터널 서비스 설치/제거는 관리자 권한이 필요해 `windows/app/tray.py`의 `_run_elevated_schtasks`와 동일한 패턴(PowerShell `Start-Process -Verb RunAs`)으로 그 순간만 상승시킨다.
- **`app/companion_client.py`**: `CompanionClient.kt`와 동일한 계약(`X-WireWOL-Token` 헤더, `/api/ping`·`/api/shutdown`·`/api/shutdown/cancel`)으로 `windows/` 컴패니언을 호출한다.
- **`app/qr_scan.py`**: 웹캠으로 QR을 스캔하는 모달(OpenCV + pyzbar) — 안드로이드처럼 카메라로 직접 페어링할 수 있는 경로. `app/settings_dialog.py`에서 붙여넣기와 함께 두 가지 입력 방식을 모두 제공한다. `generate_qr_pixmap()`은 반대 방향(저장된 설정을 QR로 내보내기)을 위한 것 — `qrcode` 패키지로 만든 PNG를 `QPixmap`으로 변환한다.
- **`app/main_window.py`**: 안드로이드 `MainActivity`에 대응하는 메인 창. HTTP/공유기/WireGuard 호출은 전부 `run_async`(백그라운드 스레드 + Qt 시그널로 결과를 메인 스레드에 전달)로 실행해 창이 멈추지 않게 한다. 창이 떠 있는 동안 5초 간격으로 PC 전원 상태를 자동 재확인하는 타이머(`_auto_refresh_timer`)와, 예약된 종료 시각을 `ClientConfig`에 저장해 창을 닫았다 다시 열어도 상태 카드에 남아있게 하는 로직(`_update_pending_shutdown_status`)이 `MainActivity.kt`의 `startAutoRefresh`/`shutdownPrefs`와 각각 대응한다.

안드로이드 `SettingsActivity.kt`의 `showPairingQrDialog`(저장된 연결 정보를 PC 트레이 `_pairing_payload`와 **완전히 같은 JSON 스키마**로 다시 QR로 보여주는 기능)는 `client/app/settings_dialog.py`의 `_on_show_pairing_qr`로도 옮겨져 있다 — 스키마를 바꾸면 트레이/안드로이드/데스크톱 클라이언트의 스캔·표시·파싱을 전부 함께 고칠 것.

## 코드 관례
- Windows 쪽 페어링 QR JSON 스키마와 안드로이드 쪽 파싱은 서로의 계약이다 — 한쪽만 고치면 깨진다(위 아키텍처 절 참고).
- `mobile-hub-viewer_v`의 코드를 옮겨 적은 파일(`WireGuardController.kt`/`RouterWol.kt`/`app/tray.py`/`app/process_utils.py`)은 그쪽 구현이 바뀌어도 자동 동기화되지 않는 의도적인 복제다 — 원본에서 버그를 고쳤다면 여기도 확인할 것.
- `mobile-hub-viewer_v`와 달리 이 프로젝트는 **PC에 실제로 쓰기 동작(종료 명령)을 수행한다** — 새 API를 추가할 때 인증(토큰 검사)을 빠뜨리지 않을 것.
