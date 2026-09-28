import java.util.Properties
import groovy.json.JsonSlurper

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("rust")
}

val tauriProperties = Properties().apply {
    val propFile = file("tauri.properties")
    if (propFile.exists()) {
        propFile.inputStream().use { load(it) }
    }
}

val releaseKeystorePath = System.getenv("LAMTOOLS_ANDROID_KEYSTORE_PATH")?.trim().orEmpty()
val releaseKeystorePassword = System.getenv("LAMTOOLS_ANDROID_KEYSTORE_PASSWORD")?.trim().orEmpty()
val releaseKeyAlias = System.getenv("LAMTOOLS_ANDROID_KEY_ALIAS")?.trim().orEmpty()
val releaseKeyPassword = System.getenv("LAMTOOLS_ANDROID_KEY_PASSWORD")?.trim().orEmpty()
val releaseSigningReady = listOf(
    releaseKeystorePath,
    releaseKeystorePassword,
    releaseKeyAlias,
    releaseKeyPassword,
).all { it.isNotEmpty() }
val signDebugWithRelease = System.getenv("LAMTOOLS_ANDROID_SIGN_DEBUG_WITH_RELEASE") == "1"

// Resolve the bundled Android verifier from Cargo's locked dependency graph.
val rustlsAndroidPackage = run {
    val metadata = providers.exec {
        workingDir = file("../../..")
        commandLine(
            "cargo", "metadata", "--locked", "--format-version", "1",
            "--filter-platform", "aarch64-linux-android",
            "--manifest-path", file("../../../Cargo.toml").absolutePath,
        )
    }.standardOutput.asText.get()
    val packages = (JsonSlurper().parseText(metadata) as Map<*, *>)["packages"] as List<*>
    packages.map { it as Map<*, *> }
        .single { it["name"] == "rustls-platform-verifier-android" }
}

repositories {
    exclusiveContent {
        forRepository {
            maven {
                url = uri(file(rustlsAndroidPackage["manifest_path"] as String).parentFile.resolve("maven"))
                metadataSources { mavenPom(); artifact() }
            }
        }
        filter { includeGroup("rustls") }
    }
}
if (signDebugWithRelease) {
    require(releaseSigningReady) {
        "Debug signing requested, but Android release signing credentials are incomplete."
    }
    require(file(releaseKeystorePath).isFile) {
        "Debug signing requested, but the Android release keystore does not exist."
    }
}

android {
    compileSdk = 36
    namespace = "com.lamtools.mobile"
    defaultConfig {
        manifestPlaceholders["usesCleartextTraffic"] = "true"
        applicationId = "com.lamtools.mobile"
        minSdk = 26
        targetSdk = 36
        versionCode = tauriProperties.getProperty("tauri.android.versionCode", "1044").toInt()
        versionName = tauriProperties.getProperty("tauri.android.versionName", "0.1.44")
    }
    signingConfigs {
        if (releaseSigningReady) {
            create("release") {
                storeFile = file(releaseKeystorePath)
                storePassword = releaseKeystorePassword
                keyAlias = releaseKeyAlias
                keyPassword = releaseKeyPassword
            }
        }
    }
    buildTypes {
        getByName("debug") {
            if (signDebugWithRelease) {
                signingConfig = signingConfigs.getByName("release")
            }
            manifestPlaceholders["usesCleartextTraffic"] = "true"
            isDebuggable = true
            isJniDebuggable = true
            isMinifyEnabled = false
            packaging {                jniLibs.keepDebugSymbols.add("*/arm64-v8a/*.so")
                jniLibs.keepDebugSymbols.add("*/armeabi-v7a/*.so")
                jniLibs.keepDebugSymbols.add("*/x86/*.so")
                jniLibs.keepDebugSymbols.add("*/x86_64/*.so")
            }
        }
        getByName("release") {
            isMinifyEnabled = true
            proguardFiles(
                *fileTree(".") { include("**/*.pro") }
                    .plus(getDefaultProguardFile("proguard-android-optimize.txt"))
                .toList().toTypedArray()
            )
            if (releaseSigningReady) {
                signingConfig = signingConfigs.getByName("release")
            } else {
                logger.lifecycle("Release signing credentials are incomplete; release APK will remain unsigned.")
            }
        }
    }
    kotlinOptions {
        jvmTarget = "1.8"
    }
    buildFeatures {
        buildConfig = true
    }
}

rust {
    rootDirRel = "../../../"
}

dependencies {
    implementation("rustls:rustls-platform-verifier:${rustlsAndroidPackage["version"]}")
    implementation("androidx.webkit:webkit:1.14.0")
    implementation("androidx.appcompat:appcompat:1.7.1")
    implementation("androidx.activity:activity-ktx:1.10.1")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.lifecycle:lifecycle-process:2.10.0")
    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.1.4")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.5.0")
}

apply(from = "tauri.build.gradle.kts")
