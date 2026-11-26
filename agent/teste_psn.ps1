# Teste do Remote Play pela PSN (console em outra rede) — roda sozinho, sem precisar do assistente conectado.
# Uso: clique com o botão direito > "Executar com o PowerShell"  (ou: powershell -ExecutionPolicy Bypass -File .\teste_psn.ps1)
# 1) Rode o script na rede da casa.  2) Quando ele pedir, troque o PC para o 5G/hotspot.
# 3) Ele detecta a troca, faz o teste e grava o resultado.  4) Volte ao Wi-Fi da casa.
param([string]$Console = 'PS4-118', [string]$ConsoleIp = '192.168.1.122')
$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $here '..\backend\.venv\Scripts\python.exe'
$logDir = Join-Path $here 'logs'; New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir 'teste_psn.log'
function Write-Log($m) { $line = "$(Get-Date -Format 'HH:mm:ss') $m"; Write-Host $line; Add-Content -Path $log -Value $line -Encoding utf8 }
Set-Content -Path $log -Value "=== Teste PSN $(Get-Date -Format 'dd/MM/yyyy HH:mm') ===" -Encoding utf8
Set-Location $here
Get-Process chiaki -ErrorAction SilentlyContinue | Stop-Process -ErrorAction SilentlyContinue

Write-Host ''
Write-Host 'AGORA: troque o PC para o 5G / roteador do celular. O PS4 continua no Wi-Fi da casa, LIGADO.' -ForegroundColor Yellow
Write-Host 'Aguardando a troca de rede (até 3 minutos)...' -ForegroundColor Yellow
$deadline = (Get-Date).AddMinutes(3)
$fora = $false
while ((Get-Date) -lt $deadline) {
  $r = & $py -m consoleagent --discover $ConsoleIp 2>&1 | Select-Object -Last 1
  if ("$r" -match 'Nenhum') { $fora = $true; break }
  Start-Sleep 3
}
if (-not $fora) { Write-Log 'FALHOU: o PC continuou enxergando o PS4 na rede local (não trocou de rede a tempo).'; Read-Host 'Enter para fechar'; exit 1 }
# O PC não pode continuar na rede da casa por OUTRA placa (ex.: cabo de rede ligado): o teste não provaria a internet.
$prefixo = ($ConsoleIp -split '\.')[0..2] -join '.'
$ativas = (Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object Status -eq 'Up').ifIndex       # só placas conectadas
$naCasa = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
  Where-Object { $_.IPAddress -like "$prefixo.*" -and $_.AddressState -eq 'Preferred' -and $ativas -contains $_.InterfaceIndex }
if ($naCasa) {
  Write-Log "FALHOU: o PC ainda está na rede da casa por '$($naCasa[0].InterfaceAlias)' ($($naCasa[0].IPAddress)). Desconecte o CABO de rede (ou desative essa placa) e rode o teste de novo."
  Read-Host 'Enter para fechar'; exit 1
}
$ip = (Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway } | ForEach-Object { "$($_.InterfaceAlias) $($_.IPv4Address.IPAddress)" }) -join '; '
Write-Log "PC fora da rede do PS4 (rede atual: $ip). Iniciando o teste pela PSN..."
Write-Host 'NÃO mexa no mouse nem no teclado até terminar (o agente usa o teclado no chiaki-ng).' -ForegroundColor Cyan
Start-Sleep 8      # a internet do celular pode levar alguns segundos para estabilizar

$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [Text.Encoding]::UTF8     # acentos corretos no log
cmd /c "`"$py`" -m consoleagent --check $Console --mode chiaki --route internet_psn < nul 2>&1" | ForEach-Object { Write-Log $_ }

Write-Host ''
Write-Host 'TERMINADO. Volte o PC para o Wi-Fi da casa e avise o assistente.' -ForegroundColor Green
Write-Log 'Fim do teste.'
Read-Host 'Enter para fechar'
