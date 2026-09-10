param(
  [string]$ProjectPath = "D:\AI-Agent-Command-Center",
  [string]$TaskName = "AI Agent Command Center"
)

$pythonExe = Join-Path $ProjectPath ".venv\Scripts\python.exe"
$action = New-ScheduledTaskAction -Execute $pythonExe -Argument "main.py" -WorkingDirectory $ProjectPath
$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Force
Write-Host "Registered $TaskName to start at logon from $ProjectPath"
