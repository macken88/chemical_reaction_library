[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [switch]$SkipInstall,
    [switch]$SmokeTest,
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backendProcess = $null
$frontendProcess = $null
$logRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("chemical-reaction-library-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null

function Stop-ChildTree([System.Diagnostics.Process]$process) {
    if ($null -ne $process) {
        # uv/npm may create a child process; terminate the complete, targeted tree.
        & taskkill.exe /PID $process.Id /T /F 2>$null | Out-Null
    }
}

function Wait-Http([string]$uri, [string]$label, [int]$timeoutSeconds = 30) {
    $deadline = (Get-Date).AddSeconds($timeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -Uri $uri -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) { return $response.StatusCode }
        } catch { }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    throw "$label の起動を確認できませんでした: $uri"
}

Push-Location $root
try {
    $uvCommand = Get-Command uv -ErrorAction SilentlyContinue
    $pythonPath = Join-Path $root ".venv\Scripts\python.exe"
    if (-not $SkipInstall) {
        if ($null -eq $uvCommand) { throw "uv が見つかりません。uv をインストールするか -SkipInstall を指定してください。" }
        if (-not (Test-Path (Join-Path $root ".venv"))) { & $uvCommand.Source sync }
        $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
        if ($null -eq $npmCommand) { $npmCommand = Get-Command npm -ErrorAction SilentlyContinue }
        if ($null -eq $npmCommand) { throw "npm が見つかりません。Node.js をインストールするか -SkipInstall を指定してください。" }
        if (-not (Test-Path (Join-Path $root "frontend\node_modules"))) {
            Push-Location (Join-Path $root "frontend")
            try { & $npmCommand.Source install } finally { Pop-Location }
        }
    }

    if ($null -ne $uvCommand) {
        $backendFile = $uvCommand.Source
        $backendArguments = @("run", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", $BackendPort)
    } elseif (Test-Path $pythonPath) {
        $backendFile = $pythonPath
        $backendArguments = @("-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", $BackendPort)
    } else {
        throw "uv または .venv\\Scripts\\python.exe が必要です。依存を構築するか -SkipInstall を外してください。"
    }
    $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($null -eq $npmCommand) { $npmCommand = Get-Command npm -ErrorAction SilentlyContinue }
    if ($null -eq $npmCommand) { throw "npm が見つかりません。Node.js をインストールしてください。" }
    $npmPath = $npmCommand.Source
    if ($npmPath -match "\.cmd$") {
        $frontendFile = $env:ComSpec
        $frontendArguments = @("/d", "/c", ('call "{0}" run dev -- --host 127.0.0.1 --port {1}' -f $npmPath, $FrontendPort))
    } else {
        $frontendFile = $npmPath
        $frontendArguments = @("run", "dev", "--", "--host", "127.0.0.1", "--port", $FrontendPort)
    }

    $backendLog = Join-Path $logRoot "backend.log"
    $frontendLog = Join-Path $logRoot "frontend.log"
    $backendProcess = Start-Process -FilePath $backendFile -ArgumentList $backendArguments -WorkingDirectory $root -RedirectStandardOutput $backendLog -RedirectStandardError ($backendLog + ".err") -WindowStyle Hidden -PassThru
    $frontendProcess = Start-Process -FilePath $frontendFile -ArgumentList $frontendArguments -WorkingDirectory (Join-Path $root "frontend") -RedirectStandardOutput $frontendLog -RedirectStandardError ($frontendLog + ".err") -WindowStyle Hidden -PassThru

    # /api/schema-version is a lightweight backend readiness/health request.
    $backendStatus = Wait-Http "http://127.0.0.1:$BackendPort/api/schema-version" "FastAPI"
    $frontendStatus = Wait-Http "http://127.0.0.1:$FrontendPort/" "Vite"
    Write-Host "FastAPI: http://127.0.0.1:$BackendPort (HTTP $backendStatus)"
    Write-Host "Vite:    http://127.0.0.1:$FrontendPort (HTTP $frontendStatus)"
    if ($SmokeTest) { return }
    if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$FrontendPort/" | Out-Null }
    Write-Host "終了するには Ctrl+C を押してください。"
    while (-not $backendProcess.HasExited -and -not $frontendProcess.HasExited) { Start-Sleep -Seconds 1 }
    if ($backendProcess.HasExited) { throw "FastAPI プロセスが終了しました。ログ: $backendLog" }
    throw "Vite プロセスが終了しました。ログ: $frontendLog"
} finally {
    Stop-ChildTree $frontendProcess
    Stop-ChildTree $backendProcess
    Pop-Location
    if (Test-Path $logRoot) { Remove-Item -LiteralPath $logRoot -Recurse -Force -ErrorAction SilentlyContinue }
}
