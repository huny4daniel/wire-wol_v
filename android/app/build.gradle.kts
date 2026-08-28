plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// 릴리즈 워크플로가 -PreleaseVersionName=vX.Y.Z로 깃 태그를 그대로 넘겨준다.
// 로컬 빌드처럼 이 프로퍼티가 없으면 1.0.0으로 대체한다.
val releaseTag = (project.findProperty("releaseVersionName") as String?)?.removePrefix("v")
val releaseVersionName = releaseTag ?: "1.0.0"
val versionParts = releaseVersionName.split(".").map { it.toIntOrNull() ?: 0 }
val releaseVersionCode = (versionParts.getOrElse(0) { 1 } * 10000) +
    (versionParts.getOrElse(1) { 0 } * 100) +
    versionParts.getOrElse(2) { 0 }

// 릴리즈 서명 — CI가 매번 새 임시 디버그 키로 서명하면 업데이트할 때마다
// "서명이 달라 설치 실패"가 나서, 고정된 키(GitHub Secrets에 base64로 저장,
// CI가 android/keystore/release.keystore로 복원)로 서명하도록 한다. 로컬
// 개발 빌드처럼 이 프로퍼티들이 없으면 release 서명 설정 자체를 만들지
// 않는다(로컬에서는 assembleDebug만 쓰므로 지장 없음).
val envKeystorePath = project.findProperty("releaseKeystorePath") as String?
val envKeystorePassword = project.findProperty("releaseKeystorePassword") as String?
val envKeyAlias = project.findProperty("releaseKeyAlias") as String?
val envKeyPassword = project.findProperty("releaseKeyPassword") as String?
val hasReleaseSigning = !envKeystorePath.isNullOrBlank()

android {
    namespace = "com.wirewol.remote"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.wirewol.remote"
        minSdk = 26
        targetSdk = 35
        versionCode = if (releaseVersionCode > 0) releaseVersionCode else 1
        versionName = releaseVersionName
    }

    if (hasReleaseSigning) {
        signingConfigs {
            create("release") {
                // keystorePath는 프로젝트 루트(android/) 기준 상대경로로 넘어오는데,
                // 이 build.gradle.kts는 app 모듈 안에 있어 file()이 app/ 기준으로
                // 풀려버린다 — rootProject.file()로 풀어야 CI의 android/keystore/...
                // 경로와 실제로 맞는다.
                storeFile = rootProject.file(envKeystorePath!!)
                storePassword = envKeystorePassword
                keyAlias = envKeyAlias
                keyPassword = envKeyPassword
                // PKCS12로 만들면 AGP의 서명 처리기가 "Tag number over 30 is not
                // supported"로 파싱에 실패하는 문제가 있어(mobile-hub-viewer_v에서
                // 실제로 겪음) JKS로 만들어야 한다.
                storeType = "JKS"
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            if (hasReleaseSigning) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
        debug {
            // 정식 릴리즈와 완전히 별개의 앱으로 취급되어 서명이 달라도 충돌 없이
            // 같이 깔려 있을 수 있게 한다. 앱 이름은 src/debug/res/values/strings.xml
            // 에서 따로 겹쳐쓴다(resValue로 하면 main의 app_name과 리소스 이름이
            // 충돌한다).
            applicationIdSuffix = ".debug"
        }
    }

    // AGP 8+부터 BuildConfig 생성이 기본 꺼져 있다 — 화면 하단 버전 표시에
    // BuildConfig.VERSION_NAME을 쓰기 위해 켠다.
    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.activity:activity-ktx:1.9.2")
    // 앱 전체(모든 액티비티)가 백그라운드로 가는/돌아오는 시점을 감지하기 위한
    // ProcessLifecycleOwner — 액티비티별 onStart/onStop만으로는 화면 전환과
    // 실제 백그라운드 진입을 구분할 수 없다.
    implementation("androidx.lifecycle:lifecycle-process:2.8.7")
    implementation("com.google.android.material:material:1.12.0")
    // QR 스캔 — 카메라 미리보기/권한 요청까지 내장된 액티비티를 그대로 씀.
    implementation("com.journeyapps:zxing-android-embedded:4.3.0")
    // 공유기 원격 WOL / WireWOL 컴패니언 API 호출.
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    // 공유기 관리자 ID/비밀번호, 페어링 토큰 등을 안드로이드 키스토어로 암호화해 저장.
    implementation("androidx.security:security-crypto:1.1.0-alpha06")
    // WireGuard 공식 팀이 다른 앱에 임베딩할 수 있도록 배포하는 터널 라이브러리
    // — 별도 WireGuard 앱 없이 우리 앱 안에서 직접 VPN을 붙였다 뗄 수 있다.
    implementation("com.wireguard.android:tunnel:1.0.20230706")
}
