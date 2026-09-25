@echo off
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | Where-Object { $_.CommandLine -like '*run.py --loop*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host 'Бот остановлен' }"
pause
