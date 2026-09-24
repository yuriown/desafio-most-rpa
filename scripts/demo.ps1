# Sobe a API e o túnel público do Cloudflare para a demonstração da Parte 2.
# Uso (na pasta do projeto):  powershell -ExecutionPolicy Bypass -File scripts\demo.ps1
# Ctrl+C encerra os dois.

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz

$python = Join-Path $raiz ".venv\Scripts\python.exe"
$cloudflared = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
if (-not $cloudflared) { $cloudflared = Join-Path $env:LOCALAPPDATA "Programs\cloudflared\cloudflared.exe" }
if (-not (Test-Path $cloudflared)) { throw "cloudflared não encontrado. Veja docs/PARTE2.md, passo 2." }
if (-not (Select-String -Path (Join-Path $raiz ".env") -Pattern "^ROBO_API_KEY=." -Quiet -ErrorAction SilentlyContinue)) {
    throw "Defina ROBO_API_KEY no .env antes de expor a API (docs/PARTE2.md, passo 1)."
}

# O Chromium do Playwright fica fora do projeto (em %LOCALAPPDATA%\ms-playwright). Sem ele,
# toda consulta falha; confere abrindo o navegador uma vez e, se faltar, instala.
$ErrorActionPreference = "Continue"  # stderr de programa externo não pode derrubar o script no PowerShell 5
& $python -c "from playwright.sync_api import sync_playwright as s; p = s().start(); p.chromium.launch(headless=True).close(); p.stop()" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Navegador do Playwright não encontrado; instalando (uns 150 MB)..."
    & $python -m playwright install chromium
    if ($LASTEXITCODE -ne 0) { throw "Falhou a instalação do navegador: python -m playwright install chromium" }
}
$ErrorActionPreference = "Stop"

$log = Join-Path $env:TEMP "robo-tunel.log"
Remove-Item $log -ErrorAction SilentlyContinue

$api = Start-Process $python -ArgumentList "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "8000" -PassThru -NoNewWindow
$tunel = Start-Process $cloudflared -ArgumentList "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:8000" -PassThru -NoNewWindow -RedirectStandardError $log

try {
    $url = $null
    for ($i = 0; $i -lt 60 -and -not $url; $i++) {
        Start-Sleep -Seconds 1
        $url = Select-String -Path $log -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" -ErrorAction SilentlyContinue |
            Select-Object -First 1 | ForEach-Object { $_.Matches[0].Value }
    }
    if (-not $url) { throw "O túnel não informou o endereço. Log: $log" }

    Write-Host ""
    Write-Host "API local:    http://127.0.0.1:8000/   (interface)  e  /docs  (Swagger)"
    Write-Host "API pública:  $url"
    Write-Host "No Make, módulo 2 (HTTP), URL:  $url/consultas"
    Write-Host ""
    Write-Host "O endereço muda sempre que este script reinicia. A rede daqui pode demorar a"
    Write-Host "resolver o nome novo (o Make, na nuvem, não). Ctrl+C para encerrar."
    Wait-Process -Id $api.Id
}
finally {
    foreach ($p in @($tunel, $api)) { if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force } }
}
