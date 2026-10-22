# Установка и запуск CRM на Windows одной командой.
# Запуск:  powershell -ExecutionPolicy Bypass -File setup.ps1
# Повторный запуск безопасен: .env и данные сохраняются, обновляется только IP для телефона.
$ErrorActionPreference = "Continue"  # Stop ломает вызовы docker в Windows PowerShell 5.1
Set-Location -Path $PSScriptRoot

function Rand([int]$n) { -join ((48..57) + (65..90) + (97..122) | Get-Random -Count $n | ForEach-Object { [char]$_ }) }
$ascii = New-Object System.Text.ASCIIEncoding

# 1. .env: создаём со случайными паролями, если его нет
$envPath = Join-Path $PSScriptRoot ".env"
if (-not (Test-Path $envPath)) {
    $port = 8000
    $busy = Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue
    if ($busy) { $port = 8080 }
    $lines = @(
        "DJANGO_SECRET_KEY=$(Rand 50)",
        "DJANGO_DEBUG=1",
        "DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0",
        "DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:$port",
        "APP_PORT=$port",
        "POSTGRES_DB=crm",
        "POSTGRES_USER=crm",
        "POSTGRES_PASSWORD=$(Rand 24)",
        "PYTHON_IMAGE=mirror.gcr.io/library/python:3.12-slim",
        "POSTGRES_IMAGE=mirror.gcr.io/library/postgres:16-alpine",
        "DEMO_MODE=1",
        "DEMO_PASSWORD=demo12345demo"
    )
    [IO.File]::WriteAllLines($envPath, $lines, $ascii)
    Write-Host "Создан .env со случайными паролями (порт $port)." -ForegroundColor Green
}

# 2. IP компьютера в локальной сети — чтобы открыть с телефона
$cfg = @{}
foreach ($l in [IO.File]::ReadAllLines($envPath)) { if ($l -match '^\s*([A-Z_]+)=(.*)$') { $cfg[$matches[1]] = $matches[2] } }
$port = if ($cfg["APP_PORT"]) { $cfg["APP_PORT"] } else { "8000" }
$ips = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" -and $_.InterfaceAlias -notmatch "vEthernet|WSL|Docker|Loopback" } |
    Select-Object -ExpandProperty IPAddress)
# Ручные добавки (домены туннеля и т.п. — с точкой или звёздочкой) сохраняем
$keepHosts = @(); $keepOrigins = @()
if ($cfg["DJANGO_ALLOWED_HOSTS"]) { $keepHosts = @($cfg["DJANGO_ALLOWED_HOSTS"].Split(",") | Where-Object { $_.StartsWith(".") }) }
if ($cfg["DJANGO_CSRF_TRUSTED_ORIGINS"]) { $keepOrigins = @($cfg["DJANGO_CSRF_TRUSTED_ORIGINS"].Split(",") | Where-Object { $_.Contains("*") }) }
$hosts = @("localhost", "127.0.0.1", "0.0.0.0") + $ips + $keepHosts
$origins = @("http://localhost:$port") + ($ips | ForEach-Object { "http://${_}:$port" }) + $keepOrigins
$out = foreach ($l in [IO.File]::ReadAllLines($envPath)) {
    if ($l -like "DJANGO_ALLOWED_HOSTS=*") { "DJANGO_ALLOWED_HOSTS=" + ($hosts -join ",") }
    elseif ($l -like "DJANGO_CSRF_TRUSTED_ORIGINS=*") { "DJANGO_CSRF_TRUSTED_ORIGINS=" + ($origins -join ",") }
    else { $l }
}
# Настройки, появившиеся в новых версиях, дописываем в старый .env
$defaults = [ordered]@{
    "PYTHON_IMAGE"   = "mirror.gcr.io/library/python:3.12-slim"
    "POSTGRES_IMAGE" = "mirror.gcr.io/library/postgres:16-alpine"
    "APP_PORT"       = $port
}
foreach ($k in $defaults.Keys) { if (-not $cfg.ContainsKey($k)) { $out = @($out) + "$k=$($defaults[$k])"; Write-Host "В .env добавлено: $k" } }
[IO.File]::WriteAllLines($envPath, [string[]]$out, $ascii)

# 3. Сборка и запуск. --wait ждёт, пока база и таблицы будут готовы
Write-Host "Собираю и запускаю (первый раз — несколько минут)..." -ForegroundColor Cyan
docker compose up -d --build --wait
if ($LASTEXITCODE -ne 0) {
    Write-Host "Не запустилось. Пришлите в чат вывод: docker compose logs backend" -ForegroundColor Red
    exit 1
}

# 4. Демо-данные — только в пустую базу
docker compose exec -T backend python manage.py seed_demo 2>$null
if ($LASTEXITCODE -eq 0) { Write-Host "Демо-данные загружены." -ForegroundColor Green }
else { Write-Host "Демо-данные уже есть — не трогаю." }

Write-Host ""
Write-Host "Готово!" -ForegroundColor Green
Write-Host "  Приложение:  http://localhost:$port/   (olga — администратор, manager — управляющий)"
Write-Host "  Админка:     http://localhost:$port/admin/   (superadmin)"
Write-Host "  Пароль демо: $($cfg['DEMO_PASSWORD'])"
foreach ($ip in $ips) { Write-Host "  С телефона:  http://${ip}:$port/" }
if ($ips.Count -gt 0) {
    Write-Host ""
    Write-Host "Для телефона один раз откройте порт (PowerShell от администратора):" -ForegroundColor Yellow
    Write-Host "  New-NetFirewallRule -DisplayName 'CRM' -Direction Inbound -LocalPort $port -Protocol TCP -Action Allow -Profile Private"
}
