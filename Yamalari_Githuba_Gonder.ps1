# =====================================================================
# Yamalari_Githuba_Gonder.ps1
# -----------------------------------------------------------------
# C:\ENTEGRE_MUHASEBE_2026 dizinindeki değişiklikleri GitHub'a gönderir.
# Token .env dosyasından okunur; script içine YAZILMAZ, ekrana YAZDIRILMAZ.
#
# Kullanim: PowerShell'de proje dizininden calistirin:
#   .\Yamalari_Githuba_Gonder.ps1
#
# On kosul: C:\ENTEGRE_MUHASEBE_2026\.env icinde su satir olmali:
#   GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
# =====================================================================

$ErrorActionPreference = "Stop"

$ProjeDizini = "C:\ENTEGRE_MUHASEBE_2026"
$RepoUrl     = "https://github.com/karyenic/ENTEGRE-MUHASEBE.git"
$Branch      = "main"

Set-Location $ProjeDizini

# ---------------------------------------------------------------------
# 1) .env dosyasindan GITHUB_TOKEN oku
# ---------------------------------------------------------------------
$envPath = Join-Path $ProjeDizini ".env"
if (-not (Test-Path $envPath)) {
    Write-Error ".env dosyasi bulunamadi: $envPath"
    exit 1
}

$envVars = @{}
Get-Content $envPath | ForEach-Object {
    $satir = $_.Trim()
    if ($satir -and -not $satir.StartsWith("#") -and $satir.Contains("=")) {
        $parcalar = $satir -split "=", 2
        $anahtar = $parcalar[0].Trim()
        $deger   = $parcalar[1].Trim().Trim('"').Trim("'")
        $envVars[$anahtar] = $deger
    }
}

$token = $envVars["GITHUB_TOKEN"]
if (-not $token) {
    Write-Error ".env icinde GITHUB_TOKEN bulunamadi. Ornek satir: GITHUB_TOKEN=ghp_xxx..."
    exit 1
}

# ---------------------------------------------------------------------
# 2) .gitignore icinde .env kontrolu (guvenlik: token asla commitlenmemeli)
# ---------------------------------------------------------------------
$gitignorePath = Join-Path $ProjeDizini ".gitignore"
$envKorumali = $false
if (Test-Path $gitignorePath) {
    $envKorumali = (Get-Content $gitignorePath) -match '^\s*\.env\s*$' | Measure-Object | Select-Object -ExpandProperty Count
}
if (-not $envKorumali) {
    Write-Warning ".gitignore icinde '.env' bulunamadi! Token'in commitlenmesini onlemek icin ekleniyor..."
    Add-Content -Path $gitignorePath -Value "`n.env`n*.env`n.env.*"
}

# ---------------------------------------------------------------------
# 3) Git deposu yoksa baslat
# ---------------------------------------------------------------------
if (-not (Test-Path (Join-Path $ProjeDizini ".git"))) {
    Write-Host "Git deposu bulunamadi, olusturuluyor..."
    git init | Out-Null
    git branch -M $Branch
}

# ---------------------------------------------------------------------
# 4) 'origin' remote kontrolu
# ---------------------------------------------------------------------
$mevcutRemotelar = git remote 2>$null
if ($mevcutRemotelar -notcontains "origin") {
    git remote add origin $RepoUrl
    Write-Host "Remote 'origin' eklendi: $RepoUrl"
} else {
    git remote set-url origin $RepoUrl
}

# ---------------------------------------------------------------------
# 5) GUVENLIK KONTROLU: .env daha once yanlislikla stage edilmis mi?
# ---------------------------------------------------------------------
$stagedEnv = git ls-files --cached | Select-String -Pattern '^\.env$'
if ($stagedEnv) {
    Write-Warning ".env dosyasi git tarafindan takip ediliyor! Takipten cikariliyor (dosya diskten SILINMEZ)..."
    git rm --cached .env | Out-Null
}

# ---------------------------------------------------------------------
# 6) Degisiklikleri commit'le
# ---------------------------------------------------------------------
git add -A
$commitMesaji = "Otomatik guncelleme: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
git commit -m $commitMesaji
if ($LASTEXITCODE -ne 0) {
    Write-Host "Commit edilecek yeni degisiklik yok, push adimina geciliyor..."
}

# ---------------------------------------------------------------------
# 7) Token'i diske/config'e YAZMADAN push et (HTTP header ile, tek seferlik)
# ---------------------------------------------------------------------
$basicAuthBytes = [Text.Encoding]::ASCII.GetBytes("x-access-token:$token")
$basicAuth = [Convert]::ToBase64String($basicAuthBytes)

Write-Host "GitHub'a gonderiliyor: $RepoUrl ($Branch)..."
git -c http.extraHeader="AUTHORIZATION: Basic $basicAuth" push -u origin $Branch

if ($LASTEXITCODE -ne 0) {
    Write-Warning "Normal push reddedildi (uzak depoda farkli/eski icerik olabilir)."
    $cevap = Read-Host "Uzak depodaki icerigi GORMEDEN uzerine yazmak (force push) ister misiniz? Bu islem GERI ALINAMAZ! (evet/hayir)"
    if ($cevap -eq "evet") {
        Write-Host "Force push yapiliyor..."
        git -c http.extraHeader="AUTHORIZATION: Basic $basicAuth" push -u origin $Branch --force
    } else {
        Write-Host "Force push iptal edildi. Once 'git fetch origin' ve 'git log origin/$Branch --oneline' ile uzak icerigi inceleyin."
        exit 1
    }
}

if ($LASTEXITCODE -eq 0) {
    Write-Host "BASARILI: Degisiklikler GitHub'a gonderildi." -ForegroundColor Green
} else {
    Write-Error "Push basarisiz oldu. Token'in gecerliligini ve repo yetkilerini kontrol edin."
    exit 1
}
