@echo off
REM Script untuk setup Windows Task Scheduler otomatis
REM Jalankan sebagai Administrator

echo Setting up Auto Backup Scheduler...

REM Buat task untuk 3x sehari (09:00, 12:00, 16:30)
schtasks /create /tn "AutoBackup_Morning" /tr "C:\BackupApp\run_auto_backup.bat" /sc daily /st 09:00 /f
schtasks /create /tn "AutoBackup_Afternoon" /tr "C:\BackupApp\run_auto_backup.bat" /sc daily /st 12:00 /f
schtasks /create /tn "AutoBackup_Evening" /tr "C:\BackupApp\run_auto_backup.bat" /sc daily /st 16:30 /f

echo.
echo Scheduler setup completed!
echo Tasks created:
echo - AutoBackup_Morning (09:00)
echo - AutoBackup_Afternoon (12:00) 
echo - AutoBackup_Evening (16:30)
echo.
pause