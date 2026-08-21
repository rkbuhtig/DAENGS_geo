import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
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

fun configured(name: String, fallback: String): String =
    localProperties.getProperty(name)
        ?: providers.environmentVariable(name).orNull
        ?: rootDotEnv[name]
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

    buildTypes {
        debug {
            buildConfigField(
                "String",
                "API_BASE_URL",
                quoted(configured("DAENGS_API_BASE_URL", "http://10.0.2.2:8000")),
            )
        }
        release {
            isMinifyEnabled = false
            buildConfigField(
                "String",
                "API_BASE_URL",
                quoted(configured("DAENGS_API_BASE_URL", "https://daengs.example")),
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

    debugImplementation("androidx.compose.ui:ui-tooling")
    testImplementation("junit:junit:4.13.2")
}
