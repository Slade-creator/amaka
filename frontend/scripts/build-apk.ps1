# Builds the AMAKA debug APK.
# Wired to `npm run apk`. Keeps JDK 21 and the Android SDK explicit so the
# Capacitor 8 / Gradle 8.14 toolchain does not accidentally use the system JDK.

$ErrorActionPreference = "Stop"
$frontend = Split-Path -Parent $PSScriptRoot
Set-Location $frontend

function Test-Jdk21([string]$jdkHome) {
    if (-not $jdkHome) { return $false }
    $java = Join-Path $jdkHome "bin\java.exe"
    $release = Join-Path $jdkHome "release"
    if (-not (Test-Path $java) -or -not (Test-Path $release)) { return $false }
    $line = Select-String -Path $release -Pattern '^JAVA_VERSION="(\d+)' | Select-Object -First 1
    return ($line -and $line.Matches[0].Groups[1].Value -eq "21")
}

$jdkCandidates = @(
    $env:JAVA_HOME,
    "C:\Program Files\Android\Android Studio\jbr"
) | Where-Object { $_ }

$jdk = $jdkCandidates | Where-Object { Test-Jdk21 $_ } | Select-Object -First 1
if (-not $jdk) {
    throw "JDK 21 not found. Install JDK 21 or set JAVA_HOME to a JDK 21 (Android Studio's bundled jbr works)."
}
$env:JAVA_HOME = $jdk

$sdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } else { Join-Path $env:LOCALAPPDATA "Android\Sdk" }
if (-not (Test-Path $sdk)) {
    throw "Android SDK not found. Set ANDROID_HOME or install it with Android Studio."
}
$env:ANDROID_HOME = $sdk
$env:ANDROID_SDK_ROOT = $sdk

# Gradle reads the SDK path from local.properties when ANDROID_HOME is absent.
$sdkDir = $sdk -replace "\\", "/"
"sdk.dir=$sdkDir" | Set-Content -Path "android\local.properties" -Encoding ASCII

Write-Host "JDK:  $jdk" -ForegroundColor DarkGray
Write-Host "SDK:  $sdk" -ForegroundColor DarkGray

# aapt2 is normally downloaded from Google Maven. That download is unreliable on
# this connection, so prefer the copy shipped with the Android SDK build-tools.
$buildTools = Get-ChildItem (Join-Path $sdk "build-tools") -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -notmatch "-" } |
    Sort-Object Name -Descending |
    Select-Object -First 1
if (-not $buildTools) {
    $buildTools = Get-ChildItem (Join-Path $sdk "build-tools") -Directory -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending |
        Select-Object -First 1
}
$gradleArgs = @(":app:assembleDebug", "--no-daemon", "--max-workers=1")
if ($buildTools) {
    $aapt2 = Join-Path $buildTools.FullName "aapt2.exe"
    if (Test-Path $aapt2) {
        $gradleArgs += "-Pandroid.aapt2FromMavenOverride=$aapt2"
        Write-Host "AAPT2: $aapt2" -ForegroundColor DarkGray
    }
}

npm run build:mobile
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

npx cap sync android
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Push-Location android
try {
    .\gradlew.bat @gradleArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}

$apk = Join-Path $frontend "android\app\build\outputs\apk\debug\app-debug.apk"
if (-not (Test-Path $apk)) { throw "Gradle finished but $apk was not produced." }

Write-Host ""
Write-Host "APK: $apk" -ForegroundColor Green
Write-Host "Install with: adb install -r `"$apk`"" -ForegroundColor Gray
