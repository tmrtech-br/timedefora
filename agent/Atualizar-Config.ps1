param([string]$Arquivo)

$ErrorActionPreference = 'Stop'
$destino = Join-Path $PSScriptRoot 'config.json'

if (-not $Arquivo) {
    Add-Type -AssemblyName System.Windows.Forms
    $janela = New-Object System.Windows.Forms.OpenFileDialog
    try {
        $janela.Title = 'Selecione o config.json baixado do painel'
        $janela.Filter = 'Arquivo JSON (*.json)|*.json'
        $downloads = Join-Path $env:USERPROFILE 'Downloads'
        if (Test-Path -LiteralPath $downloads) { $janela.InitialDirectory = $downloads }
        if ($janela.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { return }
        $Arquivo = $janela.FileName
    } finally {
        $janela.Dispose()
    }
}

$origem = (Resolve-Path -LiteralPath $Arquivo).Path
if ($origem -eq $destino) { throw 'Selecione o arquivo baixado do painel, fora da pasta do agente.' }

try {
    $novo = [IO.File]::ReadAllText($origem) | ConvertFrom-Json
    $atual = [IO.File]::ReadAllText($destino) | ConvertFrom-Json
} catch {
    throw 'Confira se o arquivo baixado e o config.json do agente contêm JSON válido.'
}
if ($atual -isnot [pscustomobject] -or $novo -isnot [pscustomobject]) {
    throw 'Os dois arquivos precisam conter uma configuração JSON.'
}
foreach ($campo in @('agent_token', 'api_to_agent_token')) {
    $token = $novo.$campo
    if ($token -isnot [string] -or $token -notmatch '^[A-Za-z0-9_-]{43}$') {
        throw 'O arquivo baixado não contém os dois tokens gerados pelo painel.'
    }
    $atual | Add-Member -NotePropertyName $campo -NotePropertyValue $token -Force
}

$temporario = Join-Path $PSScriptRoot ('.config-' + [Guid]::NewGuid().ToString('N') + '.tmp')
try {
    [IO.File]::WriteAllText($temporario, ($atual | ConvertTo-Json -Depth 100), [Text.UTF8Encoding]::new($false))
    [IO.File]::Replace($temporario, $destino, [System.Management.Automation.Language.NullString]::Value)
} finally {
    if (Test-Path -LiteralPath $temporario) { Remove-Item -LiteralPath $temporario }
}
Write-Host 'Tokens atualizados no config.json. Reinicie o ConsoleAgent.'
