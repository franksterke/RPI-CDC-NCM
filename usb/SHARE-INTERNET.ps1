# Run from an elevated Windows PowerShell window. Does not reboot the Pi.
param(
    [string]$Device = '__QUADRA_HOSTNAME__.local',
    [string]$User = '',
    [string]$InternetAdapter = '',
    [string]$UsbAdapter = ''
)
$ErrorActionPreference = 'Stop'
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Open Windows PowerShell as Administrator, then run this script. No settings were changed.'
}
Get-NetAdapter | Format-Table Name, InterfaceDescription, Status
if (-not $InternetAdapter) { $InternetAdapter = Read-Host 'Exact adapter name providing internet (for example Wi-Fi)' }
if (-not $UsbAdapter) { $UsbAdapter = Read-Host 'Exact Quadra USB network adapter name (for example Ethernet 3)' }
$public = @(Get-NetAdapter | Where-Object Name -eq $InternetAdapter)
$private = @(Get-NetAdapter | Where-Object Name -eq $UsbAdapter)
if ($public.Count -ne 1 -or $private.Count -ne 1 -or $public[0].InterfaceGuid -eq $private[0].InterfaceGuid) {
    throw 'Select two distinct adapters by their exact names.'
}
if (-not $User) { $User = Read-Host 'Pi SSH username (for example frank)' }
if ($User -notmatch '^[a-z_][a-z0-9_-]*$' -or $Device -notmatch '^[a-zA-Z0-9.-]+$') { throw 'Invalid SSH destination' }
$manager = New-Object -ComObject HNetCfg.HNetShare
$connections = @($manager.EnumEveryConnection())
$publicConnection = $null
$privateConnection = $null
foreach ($connection in $connections) {
    $props = $manager.NetConnectionProps($connection)
    $config = $manager.INetSharingConfigurationForINetConnection($connection)
    if ([guid]$props.Guid -eq [guid]$public[0].InterfaceGuid) { $publicConnection = $connection }
    elseif ([guid]$props.Guid -eq [guid]$private[0].InterfaceGuid) { $privateConnection = $connection }
    elseif ($config.SharingEnabled) { throw 'Another connection is already shared. Review it in Windows before changing ICS.' }
}
if (-not $publicConnection -or -not $privateConnection) { throw 'Selected adapters are unavailable to Internet Connection Sharing.' }
Write-Host "This shares $InternetAdapter with $UsbAdapter and configures $Device for DHCP on its NEXT boot."
Write-Host 'The current USB connection will drop. Capture is not stopped or restarted.'
if ((Read-Host 'Type SHARE to continue') -cne 'SHARE') { exit 0 }
# Prepare the Pi first; keep its current runtime network unchanged until reboot.
& ssh.exe -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=5 "$User@$Device" 'sudo -n test -f /etc/systemd/system/capture.service.d/20-quadra-time-sync.conf && cd ~/RPI-CDC-NCM && sudo -n python3 tools/install.py install --board rpi-zero --development --gadget ncm-storage --network client'
if ($LASTEXITCODE -ne 0) { throw 'Pi preparation failed; Windows sharing was not changed. Install the time guard and verify SSH/sudo access first.' }
$publicConfig = $manager.INetSharingConfigurationForINetConnection($publicConnection)
$privateConfig = $manager.INetSharingConfigurationForINetConnection($privateConnection)
$beforePublic = $publicConfig.SharingEnabled
$beforePrivate = $privateConfig.SharingEnabled
try {
    $publicConfig.EnableSharing(0)
    $privateConfig.EnableSharing(1)
} catch {
    if (-not $beforePrivate -and $privateConfig.SharingEnabled) { $privateConfig.DisableSharing() }
    if (-not $beforePublic -and $publicConfig.SharingEnabled) { $publicConfig.DisableSharing() }
    throw 'Windows sharing failed. Pi is set to DHCP for next boot; use Wi-Fi/console to restore --network server if needed.'
}
Write-Host 'Sharing enabled. Finish logging, then reboot the Pi manually to receive its address from Windows.'
Write-Host "Use http://$Device/ afterwards; its old fixed USB address will no longer apply."
Write-Host 'Internet access does not enable time synchronization during logging.'
