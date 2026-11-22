param(
    [switch]$Dev,
    [switch]$Lan,
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$bindAddress = if ($Lan) { "0.0.0.0" } else { "127.0.0.1" }
$localUrl = if ($Lan) { "http://<this-pc-lan-ip>:$Port" } else { "http://127.0.0.1:$Port" }

if ($Lan) {
    Write-Host ""
    Write-Host "  LAN mode - the API is exposed to other devices on this network." -ForegroundColor Yellow
    Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
        ForEach-Object { Write-Host "    http://$($_.IPAddress):$Port  ($($_.InterfaceAlias))" -ForegroundColor Cyan }
    Write-Host "  Put that origin in frontend\.env.mobile.local as VITE_API_BASE_URL," -ForegroundColor Gray
    Write-Host "  then run: cd frontend; npm run apk" -ForegroundColor Gray
    Write-Host "  If Windows Firewall prompts, allow Python on private networks." -ForegroundColor Gray
    Write-Host ""
}

if (-not (Test-Path "frontend\node_modules")) {
    Write-Host "Installing frontend dependencies (first run only)..." -ForegroundColor Yellow
    Push-Location frontend
    npm install --no-fund --no-audit
    Pop-Location
}

if ($Dev) {
    Write-Host "Starting Vite dev server on http://127.0.0.1:5173" -ForegroundColor Cyan
    Start-Process powershell -ArgumentList @(
        "-NoExit", "-Command", "Set-Location -LiteralPath '$root\frontend'; npm run dev"
    )
    Write-Host "Starting AMAKA API on $localUrl" -ForegroundColor Cyan
    python -m uvicorn backend.app:app --host $bindAddress --port $Port
}
else {
    Write-Host "Building dashboard..." -ForegroundColor Cyan
    Push-Location frontend
    npm run build
    Pop-Location

    Write-Host ""
    Write-Host "  AMAKA // ENERGY COMMAND" -ForegroundColor Green
    Write-Host "  $localUrl" -ForegroundColor Green
    Write-Host "  Sign in with an account (demo passwords: config/users.seed.json)." -ForegroundColor DarkGray
    Write-Host "  Press Ctrl+C to stop." -ForegroundColor DarkGray
    Write-Host ""
    python -m uvicorn backend.app:app --host $bindAddress --port $Port
}
