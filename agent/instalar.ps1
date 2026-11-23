# Instalação/verificação do ConsoleAgent no PC ao lado do console (Windows).
# Uso (PowerShell, na pasta agent):   powershell -ExecutionPolicy Bypass -File .\instalar.ps1
# Pode ser executado várias vezes: só instala o que falta e no fim mostra o que ainda precisa ser feito.
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $here '..\backend\.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { $py = 'python' }
$pendente = @()

Write-Host "`n== 1/5 Dependências Python do agente ==" -ForegroundColor Cyan
& $py -m pip install --disable-pip-version-check -q -r (Join-Path $here 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar as dependências (veja a mensagem acima).' }
Write-Host 'OK'

Write-Host "`n== 2/5 Driver ViGEmBus (controle virtual) ==" -ForegroundColor Cyan
$vigem = Get-PnpDevice -ErrorAction SilentlyContinue | Where-Object { $_.FriendlyName -like '*Virtual Gamepad Emulation Bus*' }
if ($vigem) { Write-Host 'OK: ViGEmBus instalado' }
else {
  Write-Host 'ViGEmBus NÃO encontrado. O pacote vgamepad costuma abrir o instalador; se não abriu, instale manualmente:' -ForegroundColor Yellow
  Write-Host '  https://github.com/nefarius/ViGEmBus/releases  (ViGEmBus_*.exe, como administrador, e reinicie o PC)'
  $pendente += 'Instalar o driver ViGEmBus'
}
& $py -c "import vgamepad; p = vgamepad.VDS4Gamepad(); p.reset(); p.update(); print('OK: controle virtual DS4 criado com sucesso')" 2>$null
if ($LASTEXITCODE -ne 0) { $pendente += 'Controle virtual não pôde ser criado (ViGEmBus ausente ou PC não reiniciado)' }

Write-Host "`n== 3/5 Formas de conexão ==" -ForegroundColor Cyan
Push-Location $here
$psnOut = & $py -c "from consoleagent.links import DirectLink, load_profiles; d = DirectLink(); print('Remote Play direto (vários consoles por PC):', 'OK' if d.available else d.unavailable_reason); p = load_profiles() if d.available else None; print('  conta PSN vinculada:', ', '.join(p.usernames) if p and p.usernames else 'NENHUMA')"
Pop-Location
$psnOut | ForEach-Object { Write-Host $_ }
$temPsn = -not ($psnOut -match 'NENHUMA')
$chiaki = 'C:\Program Files\chiaki-ng\chiaki.exe'
if (Test-Path $chiaki) { Write-Host "chiaki-ng (opcional, console em outra rede): OK" } else { Write-Host 'chiaki-ng (opcional, só para console em outra rede): não instalado' -ForegroundColor DarkGray }

Write-Host "`n== 4/5 config.json ==" -ForegroundColor Cyan
$cfg = Join-Path $here 'config.json'
if (-not (Test-Path $cfg)) {
  Copy-Item (Join-Path $here 'config.example.json') $cfg
  Write-Host 'config.json criado a partir do exemplo: preencha os tokens e o bloco "consoles".' -ForegroundColor Yellow
}
$c = Get-Content $cfg -Raw | ConvertFrom-Json
if ("$($c.agent_token)" -like 'COLE_*' -or "$($c.api_to_agent_token)" -like 'COLE_*') { $pendente += 'Colar os tokens do painel em config.json (Agentes e dispositivos → Rotacionar tokens)' }
if (-not $temPsn -and -not $c.consoles) { $pendente +='Remote Play direto: rodar "python -m consoleagent --psn-login" e parear cada console (painel → Testes → Pareamento com o PIN). Modo chiaki-ng: preencher "consoles" em config.json' }

Write-Host "`n== 5/5 Consoles registrados no chiaki-ng ==" -ForegroundColor Cyan
Push-Location $here
& $py -m consoleagent --list
Pop-Location

Write-Host "`n== Firewall ==" -ForegroundColor Cyan
Write-Host 'Na primeira execução, permita o Python em redes PRIVADAS quando o Windows perguntar (descoberta, acordar e vídeo WebRTC).'

if ($pendente.Count) {
  Write-Host "`nFALTA FAZER:" -ForegroundColor Yellow
  $pendente | ForEach-Object { Write-Host " - $_" }
} else {
  Write-Host "`nTudo pronto. Próximo passo: python -m consoleagent --check <CONSOLE> --route ... --host ..." -ForegroundColor Green
}
