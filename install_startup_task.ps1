param(
    [switch]$System,
    [string]$TaskName = "LumiereDimmerStartup",
    [string]$ScriptPath = "$PSScriptRoot\run_hidden.vbs"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -Path $ScriptPath)) {
    throw "Launcher script not found: $ScriptPath"
}

$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument ('"' + $ScriptPath + '"')
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

if ($System) {
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $description = "Start Lumiere dimmer at Windows startup"
} else {
    $userId = "$env:USERDOMAIN\$env:USERNAME"
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
    $principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
    $description = "Start Lumiere dimmer at Windows sign-in"
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -TaskPath "\" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description $description `
    -Force | Out-Null

Get-ScheduledTask -TaskName $TaskName |
    Select-Object TaskName, State |
    Format-Table -AutoSize
