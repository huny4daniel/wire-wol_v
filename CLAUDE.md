# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 개요

집에 있는 PC를 폰에서 리모컨처럼 켜고(Wake-on-LAN), 끄고(원격 종료), WireGuard VPN을 켰다 끌 수 있게 해주는 두 부분짜리 프로젝트다.

- **`android/`**: 실제로 사용자가 만지는 앱. 버튼 네 개(PC 켜기 / PC 끄기 / 와이어가드 켜기 / 와이어가드 끄기)가 전부인 단일 화면 리모컨 + 자주 안 쓰는 것들을 모은 별도 설정 화면.
- **`windows/`**: PC 켜기(WOL)는 매직 패킷을 폰이 직접 브로드캐스트하므로 PC 쪽에 아무 프로그램이 없어도 되지만, **PC 끄기는 PC가 뭔가 받아서 실행해줘야 하므로** 최소한의 상주 프로그램이 필요하다 — 그 역할을 하는 트레이 상주 프로그램.

이 프로젝트는 `mobile-hub-viewer_v`(같은 개발자의 다른 프로젝트)의 WireGuard 임베딩 코드와 WOL 코드, 그리고 `hub.pyw`의 3모드 실행 구조/자동 시작 등록 방식을 그대로 참고해 만들었지만, **완전히 독립된 프로젝트**다 — `mobile-hub-viewer_v`의 hub 서버가 떠 있을 필요가 전혀 없다.

## 실행

**Windows 컴패니언** (WOL 대상 PC에서 실행):
```
python windows/wirewol.pyw
```
의존성: `pip install -r windows/requirements.txt` (Flask, qrcode, Pillow, pystray, pywin32).

**Android 앱**: `android/`를 Android Studio로 열거나 `cd android && ./gradlew assembleDebug`(Windows는 `gradlew.bat`)로 빌드한다. compileSdk/targetSdk 35, minSdk 26, Kotlin + AGP 8.7.3 + Gradle 8.9 — `mobile-hub-viewer_v/android`와 동일한 툴체인.

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
- `POST /api/shutdown`: `shutdown /s /f /t <delay>`(`/f`로 실행 중인 앱 강제 종료). JSON 바디의 `delay_seconds`가 없으면 기본 10초 지연(즉시 끄기 — 폰에서의 오조작이 곧바로 작업을 날리지 않도록), 있으면 그만큼 뒤로 예약한다(예약 끄기, 0~24시간 범위 검증). Windows는 예약이 걸린 채로 `shutdown /s /t`를 다시 부르면 갱신 없이 실패하므로, 매번 `shutdown /a`로 기존 예약을 먼저 지운 뒤 건다 — 즉시 끄기/예약 끄기 중 무엇을 다시 눌러도 최신 요청으로 덮어써진다.
- `POST /api/shutdown/cancel`: `shutdown /a`로 취소.

트레이 "연결 정보 보기"(`_pairing_payload`)는 `{"host","port","token","mac"}` 형태의 **JSON 텍스트**를 QR로 보여준다 — mobile-hub-viewer_v의 페어링 QR(URL 형식)과 다르게, 여기는 감쌀 웹앱이 없어 순수 데이터만 필요하기 때문이다. **이 JSON 스키마가 안드로이드 쪽 `PairingConfig`/`SettingsActivity.handlePairingScan`과의 계약이다 — 필드를 추가/변경하면 양쪽을 함께 고칠 것.**

### Android 앱 (`android/`)
WebView가 전혀 없는 순수 네이티브 단일 화면(`MainActivity`) — 감쌀 PWA가 없으니 mobile-hub-viewer_v의 android 앱과 달리 버튼 UI 자체가 화면의 전부다.

- **`WireGuardController.kt`**: mobile-hub-viewer_v의 `HubWireGuard.kt`를 그대로 옮긴 것 — WireGuard 공식 임베딩 라이브러리(`com.wireguard.android:tunnel`, GoBackend)로 별도 앱 없이 VPN을 붙였다 뗀다. 설정(.conf 텍스트, 공유기가 만들어준 QR을 스캔해서 얻음)은 암호화된 SharedPreferences에 저장. **GoBackend와 Tunnel 객체는 companion object에 둔 프로세스 전역 싱글턴**이다 — `getState()`가 자기 인스턴스가 올린 터널인지만 보므로, 액티비티/Application마다 따로 만들면 이미 떠 있는 터널을 못 보고 같은 개인키로 두 번째 장치를 올려 연결이 오락가락한다. `bringUp`/`bringDown`은 같은 락으로 직렬화하고, `bringUp`은 이미 떠 있으면 아무것도 하지 않는다.
- **`RouterWol.kt`**: mobile-hub-viewer_v와 동일 — 공유기(iptime 등)에 내장된 원격 WOL API를 문서화되지 않은 로그인→wol/signal 흐름으로 직접 호출한다(TOFU 인증서 고정). 집 밖에서 WireGuard 없이도 PC를 켤 수 있는 대안 경로.
- **`PairingConfig.kt`**: 이 프로젝트에서 새로 추가한 것 — Windows 컴패니언 QR에서 받은 host/port/token/mac을 암호화 저장한다. MAC은 PC의 `getmac` 결과를 그대로 받아오지만, 어댑터가 여러 개라 잘못 고른 경우를 위해 `saveMac()`으로 수동 덮어쓰기도 가능하다.
- **`CompanionClient.kt`**: 이 프로젝트에서 새로 추가한 것 — Windows 컴패니언의 `/api/ping`·`/api/shutdown`(선택적 `delay_seconds`)·`/api/shutdown/cancel`을 호출하는 얇은 OkHttp 클라이언트. RouterWol과 달리 TLS 인증서 처리가 없다(같은 LAN 또는 WireGuard 터널 안의 평범한 http로만 통신한다고 가정). 타임아웃을 8초로 넉넉히 둔 것은 와이어가드를 막 켠 직후 첫 요청이 핸드셰이크(유실 시 5초 뒤 재시도)를 기다려야 하기 때문이다.
- **`NetworkProbe.kt`**: "지금 집 안인가"를 SSID 비교(위치 권한 필요, 같은 이름의 다른 망에 속을 수 있음) 대신 컴패니언 포트로 짧은 TCP 연결을 찔러 실제 도달 여부로 판단한다.
- **`WireWolApplication.kt`**: `ProcessLifecycleOwner`로 **앱 전체**가 백그라운드로 가면 켜져 있던 와이어가드를 끄고, 다시 포그라운드로 오면 직전에 켜져 있던 경우에만 되살린다 — 액티비티 각각의 `onStart`/`onStop`이 아닌 이유는 메인↔설정 화면 전환은 앱을 나간 게 아니기 때문.
- **`MainActivity.kt`**: 버튼 4개(PC 켜기/PC 끄기/와이어가드 켜기/와이어가드 끄기) + 예약 끄기 버튼 + 상태 카드(PC 전원 상태, 연결 대상, MAC, WireGuard 상태, 예약된 종료) + 설정 화면으로 가는 버튼 하나가 전부. **와이어가드는 토글 버튼 하나가 아니라 켜기/끄기 버튼을 따로 둔다** — 리모컨의 다른 버튼들처럼 사용자가 누른 상태를 그대로 유지하고(이 액티비티의 `onStart`/`onStop`에 걸어 자동으로 올리고 내리지 않음 — 앱 전체 백그라운드 처리는 `WireWolApplication` 담당), mobile-hub-viewer_v의 android 앱과 달리 "화면을 보는 동안만 연결"이라는 전제 자체가 없다(감쌀 웹 콘텐츠가 없기 때문).
  - **전원 상태**: 화면이 떠 있는 동안 5초마다 `/api/ping`으로 자동 재확인(`startAutoRefresh`, `onPause`에서 정지). `onResume` 후 첫 확인에만 "확인 중…"을 띄우고 이후 반복 확인은 결과가 올 때까지 직전 상태를 유지한다(`hasCheckedPowerOnce`). 와이어가드 설정이 있는데 꺼져 있는 상태의 무응답은 "꺼짐"이 아니라 "응답 없음(와이어가드 필요)"으로 구분한다.
  - **`ensureConnectivity`**: PC 켜기/끄기 앞에 거친다 — `NetworkProbe`로 직접 닿지 않으면 와이어가드를 자동으로 켜고(필요 시 VPN 권한 요청), `waitForTunnelReady`로 터널이 자리 잡을 시간을 번 뒤 원래 동작을 이어간다.
  - **PC 켜기**: 매직 패킷을 `255.255.255.255`뿐 아니라 PC 주소 기준 /24 지정 브로드캐스트와 PC 주소 유니캐스트로도 보낸다(제한 브로드캐스트는 터널을 넘지 못함). 집 안에서 PC가 꺼져 있으면 탐지 실패로 와이어가드가 켜져 브로드캐스트가 터널로 빠지므로, `ensureConnectivity` **전에** 한 번 먼저 보낸다. 이후 원격 WOL(설정 시)과 전원 상태 폴링(처음엔 빠르게, 이후 느리게)을 시작한다.
  - **PC 끄기/예약 끄기**: 확인 다이얼로그(예약은 시/분 NumberPicker) → 컴패니언 API 호출 → 즉시 끄기는 10초짜리 Snackbar("취소" 액션), 예약은 토스트. 컴패니언이 응답하지 않으면 절전일 수 있으므로 매직 패킷으로 깨운 뒤 ping이 살아날 때까지 기다렸다가 **한 번만** 재시도한다(`wakeThenRetryShutdown`). 예약 시각은 `shutdown_prefs`에 저장해 앱을 다시 열어도 상태 카드에 남고(탭하면 취소), 시각이 지나면 화면을 켜둔 채로도 스스로 숨긴다.
  - **종료 후 와이어가드 자동 끄기**: 끄기 성공 시 와이어가드가 켜져 있었다면 예약 시각부터 ping을 반복해 **실제로 꺼진 것(무응답)을 확인한 뒤에만** 터널을 내린다(`armWireGuardOffWatch`) — 시각이 됐다고 바로 끄면 PC 쪽에서 종료가 취소된 경우에도 터널이 끊기기 때문. 감시 시작 시각을 prefs에 남겨 프로세스가 죽었다 살아나도 `onResume`에서 이어가며, 종료 취소·와이어가드 켜기/끄기·PC 켜기를 누르면 해제한다(`clearWireGuardOffWatch`).
  - **PC 켜기 후 자동 종료**(`AutoShutdownConfig`가 켜져 있을 때): PC 켜기를 누른 시각을 `shutdown_prefs`에 남기고, 전원 폴링이 켜짐을 확인하는 순간 설정된 지연으로 `/api/shutdown`을 호출한다(`scheduleAutoShutdownIfPending`) — 이후는 예약 끄기와 같은 경로(`recordScheduledShutdown`: 상태 카드 표시 + 와이어가드 끄기 감시). 사용자가 걸어둔 예약이 남아있으면 덮어쓰지 않는다. 폴링이 `onPause`에서 멈추므로, 대기 시간(10분) 안에 돌아오면 `onResume`에서 폴링을 다시 시작해 이어서 확인한다(`resumeAutoShutdownWait`).
- **`AutoShutdownConfig.kt`**: "PC 켜기 후 자동 종료" 사용 여부(기본 꺼짐)와 지연(분)을 담는 평범한(비암호화) prefs.
- **`SettingsActivity.kt`**: 자주 안 쓰는 것들(PC 등록, WireGuard 설정 스캔, 원격 WOL 설정, PC 켜기 후 자동 종료, 저장된 정보 초기화)을 모은 별도 화면 — `MainActivity`의 "설정" 버튼으로 진입한다. "PC 등록"은 카메라 스캔 / 갤러리 이미지 디코딩(ZXing `MultiFormatReader`) / 직접 입력 중 고르게 하며, 직접 입력 창이 host/port/token/mac을 전부 고칠 수 있어 예전의 별도 "MAC 주소 직접 입력" 버튼을 흡수했다. WireGuard는 카메라/갤러리만 지원한다. 각 항목 아래에 현재 설정 여부를 보여주는 상태 문구가 있다(`refreshStatuses()`) — 필수(연결 정보)와 선택(WireGuard/원격 WOL)을 구분해서 표시한다.

## 코드 관례
- Windows 쪽 페어링 QR JSON 스키마와 안드로이드 쪽 파싱은 서로의 계약이다 — 한쪽만 고치면 깨진다(위 아키텍처 절 참고).
- `mobile-hub-viewer_v`의 코드를 옮겨 적은 파일(`WireGuardController.kt`/`RouterWol.kt`/`app/tray.py`/`app/process_utils.py`)은 그쪽 구현이 바뀌어도 자동 동기화되지 않는 의도적인 복제다 — 원본에서 버그를 고쳤다면 여기도 확인할 것.
- `mobile-hub-viewer_v`와 달리 이 프로젝트는 **PC에 실제로 쓰기 동작(종료 명령)을 수행한다** — 새 API를 추가할 때 인증(토큰 검사)을 빠뜨리지 않을 것.
