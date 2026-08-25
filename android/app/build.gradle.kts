import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
    id("com.google.devtools.ksp")
}

val localProperties = Properties().apply {
    val file = rootProject.file("local.properties")
    if (file.exists()) file.inputStream().use(::load)
}

val rootDotEnv = rootProject.file("../.env")
    .takeIf { it.exists() }
    ?.readLines()
    ?.asSequence()
    ?.map(String::trim)
    ?.filter { it.isNotEmpty() && !it.startsWith("#") && "=" in it }
    ?.associate { line ->
        val (name, rawValue) = line.split("=", limit = 2)
        name.trim() to rawValue.substringBefore(" #").trim()
    }
    .orEmpty()

// 빈 값은 "설정 안 함" 으로 본다. `local.properties` 에 `KEY=` 한 줄이 남아 있으면 그 빈
// 문자열이 null 이 아니라서 뒤의 환경변수·`.env` 를 전부 이겼다 — 키가 .env 에 있는데도
// 빈 값으로 빌드되고, 앱은 설정 안내 표면을 띄운다. 이유가 보이지 않는 종류의 실패다.
fun configured(name: String, fallback: String): String =
    localProperties.getProperty(name)?.takeIf { it.isNotBlank() }
        ?: providers.environmentVariable(name).orNull?.takeIf { it.isNotBlank() }
        ?: rootDotEnv[name]?.takeIf { it.isNotBlank() }
        ?: fallback

fun quoted(value: String): String =
    "\"${value.replace("\\", "\\\\").replace("\"", "\\\"")}\""

android {
    namespace = "com.daengs.geo"
    compileSdk = 37

    defaultConfig {
        applicationId = "com.daengs.geo"
        minSdk = 26
        targetSdk = 37
        versionCode = 1
        versionName = "0.1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        buildConfigField(
            "String",
            "NAVER_MAP_NCP_KEY_ID",
            quoted(configured("DAENGS_NAVER_NCP_KEY_ID", "")),
        )
    }

    // Room writes the schema JSON here and it is committed. A table change then shows up as a
    // diff in review, and a migration can be written against a known previous version.
    ksp {
        arg("room.schemaLocation", "$projectDir/schemas")
    }

    testOptions {
        unitTests.isIncludeAndroidResources = true
    }

    buildTypes {
        debug {
            buildConfigField(
                "String",
                "API_BASE_URL",
                quoted(configured("DAENGS_API_BASE_URL", "http://10.0.2.2:8000")),
            )
            // 서버 PERSONAS 의 정식 테스트 객체 id (app/profile/source.py). 지어낸
            // placeholder 가 아니라 계약을 채운 개다. 이 값이 비어 있지 않을 때만
            // 업로더가 돈다 — 산책 사실을 어느 개에 귀속할지 모르는 채로 올리지 않는다.
            buildConfigField(
                "String",
                "DEV_DOG_ID",
                quoted(configured("DAENGS_DEV_DOG_ID", "halmae")),
            )
        }
        release {
            isMinifyEnabled = false
            buildConfigField(
                "String",
                "API_BASE_URL",
                quoted(configured("DAENGS_API_BASE_URL", "https://daengs.example")),
            )
            // release 는 빈 값이 기본이다. 실제 반려견 프로필 연동(결정 #4) 전까지
            // 업로드가 꺼져 있다는 뜻이고, 켜는 쪽이 명시한다 — 기본값에 기대지 않는다.
            buildConfigField(
                "String",
                "DEV_DOG_ID",
                quoted(configured("DAENGS_DEV_DOG_ID", "")),
            )
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

    buildFeatures {
        buildConfig = true
        compose = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2026.06.01")

    implementation(composeBom)
    androidTestImplementation(composeBom)
    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.core:core-ktx:1.19.0")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.11.0")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.11.0")
    implementation("com.google.android.gms:play-services-location:21.4.0")
    implementation("com.naver.maps:map-sdk:3.23.3")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.11.0")
    implementation("androidx.room:room-runtime:2.8.4")
    implementation("androidx.room:room-ktx:2.8.4")
    ksp("androidx.room:room-compiler:2.8.4")

    debugImplementation("androidx.compose.ui:ui-tooling")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.9.0")
    // Runs the real SQLite/Room stack in JVM unit tests — no emulator, no androidTest source set.
    testImplementation("org.robolectric:robolectric:4.16.1")
    testImplementation("androidx.test:core:1.7.0")
}
