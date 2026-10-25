<#
.SYNOPSIS
    Setup inicial completo del entorno local (equivalente a bootstrap.sh para Windows).

.DESCRIPTION
    1. Crea .env desde .env.example y genera los secretos vacíos.
    2. Levanta Supabase, Redis y Ollama con Docker Compose.
    3. Espera a que los servicios estén healthy.
    4. Aplica las migraciones pendientes.
    5. Carga datos de ejemplo.
    6. Crea el usuario administrador de demostración.
    7. Descarga el modelo de Ollama.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
    powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1 -SkipModel -WithTests
    powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1 -TestOnly
#>
[CmdletBinding()]
param(
    [switch]$SkipModel,
    [switch]$NoSeed,
    [switch]$WithTests,
    [switch]$MigrateOnly,
    [switch]$TestOnly
)

$ErrorActionPreference = 'Stop'
$RootDir = Split-Path -Parent $PSScriptRoot
Set-Location $RootDir

$EnvFile = Join-Path $RootDir '.env'
# Modo self-hosted: Supabase y Ollama en contenedores (perfiles del compose)
$ComposeArgs = @('compose', '-f', 'docker-compose.yml', '-f', 'docker-compose.dev.yml', '--profile', 'supabase-local', '--profile', 'ollama-local')
$ContainerSupabaseDir = '/workspace/supabase'
$Utf8NoBom = New-Object System.Text.UTF8Encoding $false

# ---------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------
function Write-Step([string]$Message) { Write-Host "[bootstrap] $Message" -ForegroundColor Cyan }
function Write-Ok([string]$Message)   { Write-Host "[bootstrap] OK  $Message" -ForegroundColor Green }
function Write-Warn([string]$Message) { Write-Host "[bootstrap] !!  $Message" -ForegroundColor Yellow }
function Stop-WithError([string]$Message) { Write-Host "[bootstrap] ERROR $Message" -ForegroundColor Red; exit 1 }

function Test-NativeCommand([scriptblock]$Command) {
    # En PS 5.1 redirigir el stderr de un ejecutable nativo con
    # ErrorActionPreference=Stop lanza una excepción: se relaja localmente.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Command *> $null
        return ($LASTEXITCODE -eq 0)
    } finally {
        $ErrorActionPreference = $previous
    }
}

function Invoke-Compose {
    & docker @ComposeArgs @args
    if ($LASTEXITCODE -ne 0) { throw "docker compose $($args -join ' ') falló (código $LASTEXITCODE)" }
}

function Invoke-Psql {
    & docker @ComposeArgs exec -T supabase-db psql -h localhost -U postgres -d postgres -v ON_ERROR_STOP=1 -q @args
    if ($LASTEXITCODE -ne 0) { throw "psql falló (código $LASTEXITCODE)" }
}

function Read-EnvLines {
    if (-not (Test-Path $EnvFile)) { return @() }
    return [IO.File]::ReadAllText($EnvFile).Replace("`r", '').TrimEnd("`n").Split("`n")
}

function Get-EnvValue([string]$Key) {
    $value = ''
    foreach ($line in Read-EnvLines) {
        if ($line.StartsWith("$Key=")) { $value = $line.Substring($Key.Length + 1) }
    }
    return $value
}

function Set-EnvValue([string]$Key, [string]$Value) {
    $lines = [System.Collections.Generic.List[string]](Read-EnvLines)
    $found = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i].StartsWith("$Key=")) { $lines[$i] = "$Key=$Value"; $found = $true }
    }
    if (-not $found) { $lines.Add("$Key=$Value") }
    # LF + UTF-8 sin BOM: lo lee docker compose y los contenedores Linux
    [IO.File]::WriteAllText($EnvFile, (($lines -join "`n") + "`n"), $Utf8NoBom)
}

function New-RandomHex([int]$Bytes) {
    $buffer = New-Object byte[] $Bytes
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buffer)
    return -join ($buffer | ForEach-Object { $_.ToString('x2') })
}

function ConvertTo-Base64Url([byte[]]$Bytes) {
    return [Convert]::ToBase64String($Bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function New-SupabaseJwt([string]$Role, [string]$Secret) {
    # JWT HS256 compatible con Supabase (role = anon | service_role), 10 años
    $iat = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $exp = $iat + 10 * 365 * 24 * 3600
    $utf8 = [Text.Encoding]::UTF8
    $header = ConvertTo-Base64Url $utf8.GetBytes('{"alg":"HS256","typ":"JWT"}')
    $payload = ConvertTo-Base64Url $utf8.GetBytes(('{{"role":"{0}","iss":"supabase","iat":{1},"exp":{2}}}' -f $Role, $iat, $exp))
    $hmac = New-Object Security.Cryptography.HMACSHA256 (, $utf8.GetBytes($Secret))
    $signature = ConvertTo-Base64Url $hmac.ComputeHash($utf8.GetBytes("$header.$payload"))
    return "$header.$payload.$signature"
}

function Wait-Healthy([string]$Service, [int]$TimeoutSeconds = 240) {
    $cid = (& docker @ComposeArgs ps -q $Service | Select-Object -First 1)
    if (-not $cid) { Stop-WithError "El servicio $Service no está creado" }
    $elapsed = 0
    while ($true) {
        $status = & docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $cid
        if ($status -eq 'healthy') { Write-Ok "$Service healthy"; return }
        if ($elapsed -ge $TimeoutSeconds) {
            Stop-WithError "$Service no alcanzó estado healthy en ${TimeoutSeconds}s (estado: $status). Revisa: docker compose logs $Service"
        }
        Start-Sleep -Seconds 3
        $elapsed += 3
    }
}

function Wait-Http([string]$Url, [string]$Name, [hashtable]$Headers = @{}, [int]$TimeoutSeconds = 120) {
    $elapsed = 0
    while ($true) {
        try {
            Invoke-WebRequest -Uri $Url -Headers $Headers -UseBasicParsing -TimeoutSec 5 | Out-Null
            Write-Ok "$Name responde"
            return
        } catch {
            if ($elapsed -ge $TimeoutSeconds) { Stop-WithError "$Name no responde en $Url" }
            Start-Sleep -Seconds 3
            $elapsed += 3
        }
    }
}

# ---------------------------------------------------------------------
# Pasos
# ---------------------------------------------------------------------
function Test-Prerequisites {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Stop-WithError 'Falta Docker. Instala Docker Desktop: https://docs.docker.com/desktop/setup/install/windows-install/'
    }
    if (-not (Test-NativeCommand { docker compose version })) {
        Stop-WithError "Se requiere Docker Compose v2 ('docker compose')."
    }
    if (-not (Test-NativeCommand { docker info })) {
        Stop-WithError 'El daemon de Docker no está corriendo. Inicia Docker Desktop.'
    }
}

function Initialize-EnvFile {
    if (-not (Test-Path $EnvFile)) {
        $content = [IO.File]::ReadAllText((Join-Path $RootDir '.env.example')).Replace("`r", '')
        [IO.File]::WriteAllText($EnvFile, $content, $Utf8NoBom)
        Write-Ok '.env creado desde .env.example'
    }

    $jwtSecret = Get-EnvValue 'SUPABASE_JWT_SECRET'
    if (-not $jwtSecret) {
        if (Test-NativeCommand { docker volume inspect soporte-bancario-rag_supabase-db-data }) {
            Write-Warn 'Se generará un nuevo JWT secret pero ya existe el volumen de la BD.'
            Write-Warn 'Si algo falla con la autenticación: docker compose down -v; y vuelve a ejecutar bootstrap.'
        }
        $jwtSecret = New-RandomHex 32
        Set-EnvValue 'SUPABASE_JWT_SECRET' $jwtSecret
        Set-EnvValue 'SUPABASE_ANON_KEY' ''
        Set-EnvValue 'SUPABASE_SERVICE_ROLE_KEY' ''
        Write-Ok 'SUPABASE_JWT_SECRET generado'
    }

    $anonKey = Get-EnvValue 'SUPABASE_ANON_KEY'
    if (-not $anonKey) {
        $anonKey = New-SupabaseJwt 'anon' $jwtSecret
        Set-EnvValue 'SUPABASE_ANON_KEY' $anonKey
        Write-Ok 'SUPABASE_ANON_KEY generada'
    }
    if (-not (Get-EnvValue 'SUPABASE_SERVICE_ROLE_KEY')) {
        Set-EnvValue 'SUPABASE_SERVICE_ROLE_KEY' (New-SupabaseJwt 'service_role' $jwtSecret)
        Write-Ok 'SUPABASE_SERVICE_ROLE_KEY generada'
    }
    Set-EnvValue 'VITE_SUPABASE_ANON_KEY' $anonKey

    if (-not (Get-EnvValue 'SECRET_KEY_BASE'))    { Set-EnvValue 'SECRET_KEY_BASE' (New-RandomHex 32) }
    if (-not (Get-EnvValue 'PG_META_CRYPTO_KEY')) { Set-EnvValue 'PG_META_CRYPTO_KEY' (New-RandomHex 16) }

    $internalKey = Get-EnvValue 'INTERNAL_API_KEY'
    if (-not $internalKey -or $internalKey -eq 'cambiar-en-produccion') {
        Set-EnvValue 'INTERNAL_API_KEY' (New-RandomHex 24)
        Write-Ok 'INTERNAL_API_KEY generada'
    }

    $pgPass = Get-EnvValue 'POSTGRES_PASSWORD'
    Set-EnvValue 'SUPABASE_DB_URL' "postgresql://postgres:$pgPass@localhost:54322/postgres"
    if ($pgPass -eq 'postgres') { Write-Warn 'POSTGRES_PASSWORD usa el valor por defecto (aceptable solo en desarrollo).' }
}

function Start-Stack {
    Write-Step 'Descargando imágenes y levantando la infraestructura (la primera vez tarda varios minutos)...'
    Invoke-Compose up -d
    Wait-Healthy 'supabase-db'
    Wait-Healthy 'supabase-auth'
    Wait-Healthy 'supabase-storage'
    Wait-Healthy 'redis'
    Wait-Healthy 'ollama'
    Wait-Http 'http://localhost:54321/auth/v1/health' 'Supabase API (Kong)' @{ apikey = (Get-EnvValue 'SUPABASE_ANON_KEY') }
}

function Invoke-Migrations {
    Write-Step 'Aplicando migraciones...'
    Invoke-Psql -c 'create schema if not exists supabase_migrations; create table if not exists supabase_migrations.schema_migrations (version text primary key, statements text[], name text);'

    foreach ($file in Get-ChildItem (Join-Path $RootDir 'supabase\migrations') -Filter '*.sql' | Sort-Object Name) {
        $name = $file.BaseName
        $version = $name.Split('_')[0]
        $suffix = $name.Substring($version.Length + 1)
        $applied = (& docker @ComposeArgs exec -T supabase-db psql -h localhost -U postgres -d postgres -tA -c "select 1 from supabase_migrations.schema_migrations where version = '$version'")
        if ("$applied".Trim() -eq '1') {
            Write-Step "  $name (ya aplicada)"
            continue
        }
        Write-Step "  -> $name"
        Invoke-Psql --single-transaction -f "$ContainerSupabaseDir/migrations/$($file.Name)" `
            -c "insert into supabase_migrations.schema_migrations (version, name) values ('$version', '$suffix')"
    }
    Invoke-Psql -c "notify pgrst, 'reload schema';"
    Write-Ok 'Migraciones al día'
}

function Invoke-Seed {
    Write-Step 'Cargando seed.sql...'
    Invoke-Psql -f "$ContainerSupabaseDir/seed.sql"
    Write-Ok 'Datos de ejemplo cargados'
}

function New-DemoAdmin {
    $email = Get-EnvValue 'DEMO_ADMIN_EMAIL'
    $password = Get-EnvValue 'DEMO_ADMIN_PASSWORD'
    $serviceKey = Get-EnvValue 'SUPABASE_SERVICE_ROLE_KEY'
    if (-not $email -or -not $password) { Write-Warn 'DEMO_ADMIN_EMAIL/PASSWORD vacíos: se omite el usuario demo'; return }

    Write-Step "Creando usuario administrador de demostración ($email)..."
    $body = @{
        email         = $email
        password      = $password
        email_confirm = $true
        app_metadata  = @{ role = 'admin'; area = 'general' }
        user_metadata = @{ full_name = 'Administrador Demo' }
    } | ConvertTo-Json -Depth 4
    $headers = @{ apikey = $serviceKey; Authorization = "Bearer $serviceKey" }
    try {
        Invoke-RestMethod -Method Post -Uri 'http://localhost:54321/auth/v1/admin/users' `
            -Headers $headers -ContentType 'application/json' -Body ([Text.Encoding]::UTF8.GetBytes($body)) | Out-Null
        Write-Ok 'Usuario demo creado'
    } catch {
        $code = 0
        if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
        if ($code -eq 422) { Write-Step '  El usuario demo ya existe' }
        else { Write-Warn "No se pudo crear el usuario demo: $($_.Exception.Message)" }
    }
    Invoke-Psql -c "update public.profiles set role = 'admin', area = 'general' where email = '$email';"
}

function Get-OllamaModel {
    $model = Get-EnvValue 'OLLAMA_MODEL'
    if (-not $model) { $model = 'qwen3:4b-instruct' }
    Write-Step "Descargando modelo Ollama '$model' (puede tardar varios minutos)..."
    Invoke-Compose exec -T ollama ollama pull $model
    Write-Ok "Modelo $model disponible"
}

function Invoke-DbTests {
    Write-Step 'Ejecutando tests pgTAP de la base de datos...'
    $failed = $false
    foreach ($file in Get-ChildItem (Join-Path $RootDir 'supabase\tests\database') -Filter '*.test.sql' | Sort-Object Name) {
        $output = & docker @ComposeArgs exec -T supabase-db psql -h localhost -U postgres -d postgres -v ON_ERROR_STOP=1 -q -tA -f "$ContainerSupabaseDir/tests/database/$($file.Name)"
        if ($LASTEXITCODE -ne 0) { $failed = $true }
        $output | ForEach-Object { Write-Host $_ }
        if ($output | Where-Object { $_ -match '^not ok' }) { $failed = $true }
    }
    if ($failed) { Stop-WithError 'Hay tests fallidos' }
    Write-Ok 'Todos los tests pasaron'
}

function Show-Summary {
    Write-Host ''
    Write-Host '=====================================================================' -ForegroundColor Green
    Write-Host '  Entorno listo' -ForegroundColor Green
    Write-Host '=====================================================================' -ForegroundColor Green
    Write-Host '  Supabase Studio   http://localhost:54323'
    Write-Host '  Supabase API      http://localhost:54321'
    Write-Host '  PostgreSQL        postgresql://postgres:****@localhost:54322/postgres'
    Write-Host '  Redis             redis://localhost:6379'
    Write-Host '  Ollama            http://localhost:11434'
    Write-Host "  Admin demo        $(Get-EnvValue 'DEMO_ADMIN_EMAIL') / (ver DEMO_ADMIN_PASSWORD en .env)"
    Write-Host ''
    Write-Host '  Verificación rápida:'
    Write-Host '    Invoke-RestMethod http://localhost:11434/api/tags'
    Write-Host '    powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1 -TestOnly'
}

# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------
Test-Prerequisites

if ($TestOnly) { Invoke-DbTests; exit 0 }
if ($MigrateOnly) {
    Invoke-Migrations
    if (-not $NoSeed) { Invoke-Seed }
    exit 0
}

Initialize-EnvFile
Start-Stack
Invoke-Migrations
if (-not $NoSeed) { Invoke-Seed }
New-DemoAdmin
if (-not $SkipModel) { Get-OllamaModel }
if ($WithTests) { Invoke-DbTests }
Show-Summary
