param(
    [string]$Device = '__QUADRA_HOSTNAME__.local',
    [string]$User = '',
    [int]$WaitSeconds = 180
)
$ErrorActionPreference = 'Stop'
if (-not $User) { $User = Read-Host 'Pi SSH username (for example frank)' }
if ($User -notmatch '^[a-z_][a-z0-9_-]*$' -or $Device -notmatch '^[a-zA-Z0-9.-]+$') { throw 'Invalid SSH username or device name' }
$ssh = (Get-Command ssh.exe -ErrorAction Stop).Source
Write-Host "Waiting for the pre-logging time window on $Device. No internet is needed."
Write-Host 'Existing SSH key login, a trusted host key and passwordless sudo are required.'
Write-Host 'If Capture is already logging, its clock will not be changed.'
$watch = [Diagnostics.Stopwatch]::StartNew()
do {
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = $ssh
    $info.Arguments = "-o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=2 $User@$Device sudo -n /usr/local/sbin/quadra-time-sync offer"
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardInput = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $info
    try {
        [void]$process.Start()
        $errors = $process.StandardError.ReadToEndAsync()
        $ready = $process.StandardOutput.ReadLineAsync()
        if ($ready.Wait(5000) -and $ready.Result -eq 'READY') {
            $epoch = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000.0
            $process.StandardInput.WriteLine($epoch.ToString('F3', [Globalization.CultureInfo]::InvariantCulture))
            $process.StandardInput.Close()
            $output = $process.StandardOutput.ReadToEndAsync()
            if ($process.WaitForExit(5000)) {
                if ($process.ExitCode -eq 0) { Write-Host $output.Result; exit 0 }
                if ($process.ExitCode -ne 3) { throw ($output.Result + $errors.Result) }
            }
        } elseif ($process.HasExited -and $process.ExitCode -ne 255) {
            throw ('Pi helper unavailable: ' + $errors.Result)
        }
    } finally {
        if (-not $process.HasExited) { $process.Kill(); $process.WaitForExit() }
        $process.Dispose()
    }
    Start-Sleep -Milliseconds 500
} while ($watch.Elapsed.TotalSeconds -lt $WaitSeconds)
Write-Host 'No time update was accepted. Logging was not interrupted.'
Write-Host 'For the next boot, copy this script to the PC and start it before powering on Quadra.'
exit 1
