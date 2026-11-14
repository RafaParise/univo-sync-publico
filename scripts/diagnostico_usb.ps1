# diagnostico_usb.ps1
# Acha o cabo do FortiGate: mostra as portas COM, os USB com problema de driver
# e, com -Antes, o que apareceu de novo depois de ligar o cabo.
#
# Uso:
#   1) Com o cabo DESLIGADO:  powershell -File scripts\diagnostico_usb.ps1 -Antes
#   2) Ligue o cabo e rode:   powershell -File scripts\diagnostico_usb.ps1
param([switch]$Antes)

$foto = Join-Path $env:TEMP 'parise-sync-usb-antes.txt'
$chips = @{ '0403'='FTDI (cabo console)'; '1A86'='CH340 (cabo console)'; '10C4'='CP210x (cabo console)';
            '067B'='Prolific (cabo console)'; '04E8'='Samsung (CELULAR, nao e o FortiGate)' }

function Get-Usb {
    Get-CimInstance Win32_PnPEntity | Where-Object { $_.DeviceID -like 'USB*' } |
        ForEach-Object {
            $vid = if ($_.DeviceID -match 'VID_([0-9A-F]{4})') { $Matches[1] } else { '----' }
            $pid_ = if ($_.DeviceID -match 'PID_([0-9A-F]{4})') { $Matches[1] } else { '----' }
            [pscustomobject]@{ Nome=$_.Name; VID=$vid; PID=$pid_; Erro=$_.ConfigManagerErrorCode
                               Chip=$chips[$vid]; Id=$_.DeviceID }
        }
}

$agora = Get-Usb
if ($Antes) {
    $agora.Id | Set-Content $foto
    Write-Host "Foto dos USB guardada. Agora ligue o cabo e rode de novo sem -Antes."
    exit 0
}

Write-Host "=== Portas COM ==="
Get-CimInstance Win32_PnPEntity | Where-Object { $_.Name -match '\(COM\d+\)' } | ForEach-Object {
    $vid = if ($_.DeviceID -match 'VID_([0-9A-F]{4})') { $Matches[1] } else { '----' }
    $chip = if ($chips[$vid]) { $chips[$vid] } elseif ($vid -eq '----') { 'serial da placa-mae' } else { 'desconhecido' }
    "{0,-45} VID {1}  {2}" -f $_.Name, $vid, $chip
}

Write-Host "`n=== USB com problema de driver ==="
$ruins = $agora | Where-Object { $_.Erro -ne 0 }
if ($ruins) { $ruins | Format-Table Nome, VID, PID, Erro -AutoSize } else { "nenhum" }

if (Test-Path $foto) {
    $velhos = Get-Content $foto
    Write-Host "`n=== Apareceu depois de ligar o cabo ==="
    $novos = $agora | Where-Object { $velhos -notcontains $_.Id }
    if ($novos) { $novos | Format-Table Nome, VID, PID, Erro, Chip -AutoSize } else { "nada novo (cabo sem dados, porta errada ou mal encaixado)" }
}

Write-Host "`nLeitura: erro 43 com VID 0000 = cabo so de energia ou ligado na porta USB tipo A do FortiGate."
Write-Host "Erro 28 = falta driver. COM nova com chip de cabo console = pronto para os scripts."
